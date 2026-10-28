"""
Module: routers.reports

Report generation: a single `POST /api/v1/projects/{project_id}/reports`
endpoint generating a PDF (R-F-01), Word (DOCX) or CSV (R-F-02) export of a
project's requirements, selected via `ReportRequest.format` — merged from
two separate `/reports/pdf`/`/reports/csv` endpoints on 2026-09-22 (see
docs/decisions.md) since they differed only in output format, not in data
collection, and a single parameterized endpoint leaves one place for a
future report-type/template parameter to land. Supports requirement filters (R-G-03), organisation
shared resource files rendered as additional report sections (R-G-04), and
images embedded in those Markdown sections via `report_document.resolve_report_images`
(see its docstring for the tenant-isolation check it performs before any
image reaches the PDF).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.file import FileAsset
from app.models.organization import Organization
from app.models.project import Project, ProjectCategory, ProjectComponent
from app.models.requirement import Requirement
from app.models.user import User
from app.schemas.report import ReportRequest
from app.services.codes import display_code
from app.services.downloads import file_response, filename_safe
from app.services.files import read_file
from app.services.rbac import require_project_view
from app.services.report_document import load_report_template, resolve_branding, resolve_report_images
from app.services.reports import (
    ReportRequirementRow,
    default_chapters_per_component,
    generate_csv_report,
    generate_docx_report,
    generate_pdf_report,
)
from app.services.requirements import get_current_version, get_keywords

router = APIRouter(prefix="/api/v1/projects/{project_id}/reports", tags=["reports"])


def _collect_rows(db: Session, project_id: UUID, payload: ReportRequest) -> list[ReportRequirementRow]:
    """Collects requirement rows for a report, applying R-G-03 filters.

    The ID is shown as the project's own report rule says (bare, or qualified by the project code when the
    organisation enforces it); the viewer's preference is not applied, so a saved report reads the same for everyone.
    """
    project = db.get(Project, project_id)
    enforced = db.get(Organization, project.organization_id).enforce_code_everywhere
    components = {c.id: c for c in db.scalars(select(ProjectComponent).where(ProjectComponent.project_id == project_id)).all()}
    categories = {c.id: c for c in db.scalars(select(ProjectCategory).where(ProjectCategory.project_id == project_id)).all()}
    query = select(Requirement).where(Requirement.project_id == project_id)
    if not payload.include_archived:
        query = query.where(Requirement.is_archived.is_(False))
    if payload.component_id is not None:
        query = query.where(Requirement.component_id == payload.component_id)
    if payload.category_id is not None:
        query = query.where(Requirement.category_id == payload.category_id)
    requirements = db.scalars(query).all()

    rows = []
    for req in requirements:
        version = get_current_version(db, req.id)
        if payload.status is not None and version.status != payload.status:
            continue
        keywords = get_keywords(db, req.id)
        if payload.keyword is not None and payload.keyword.casefold() not in {k.casefold() for k in keywords}:
            continue
        component = components.get(req.component_id)
        category = categories.get(req.category_id)
        rows.append(ReportRequirementRow(
            unique_code=display_code(req.unique_code, project.code, own_project_code=project.code, enforced=enforced),
            tags=", ".join(keywords) if keywords else "", name=version.name, reasoning=version.reasoning,
            clarification=version.clarification, status=version.status.value,
            component_name=component.name if component else "",
            category_name=category.name if category else "",
            component_sort_order=component.sort_order if component else 0,
            category_sort_order=category.sort_order if category else 0,
        ))
    rows.sort(key=lambda r: r.unique_code)
    return rows


def _resource_sections_markdown(db: Session, project: Project, resource_file_ids: list[UUID]) -> str:
    """Renders selected org shared resource files as additional Markdown
    report sections (R-G-04). Only text/markdown content can be rendered
    as text; other content types are noted but not embedded."""
    if not resource_file_ids:
        return ""
    sections = []
    for file_id in resource_file_ids:
        asset = db.get(FileAsset, file_id)
        if asset is None or asset.organization_id != project.organization_id or not asset.is_org_resource:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{file_id} is not a shared resource in this organisation.")
        sections.append(f"# {asset.filename}\n")
        if asset.content_type.startswith("text/"):
            sections.append(read_file(asset).decode("utf-8", errors="replace"))
        else:
            sections.append(f"*(binary file '{asset.filename}', not rendered inline)*")
    return "\n\n".join(sections)


@router.post("")
def generate_report(
    project_id: UUID, payload: ReportRequest,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Generates a requirements report in `payload.format` — PDF (R-F-01),
    DOCX or CSV (R-F-02). Requirement collection/filtering (R-G-03) is
    identical for every format; only CSV's branching below is genuinely
    format-specific (no branding/markdown/chapters concept for a flat
    export). PDF and DOCX are rendered from the same neutral document
    (`services.report_model`).

    The selected resource files (R-G-04) follow the requirement tables. An
    introduction, chapters or appendices belong to a report layout, not here."""
    project = db.get(Project, project_id)
    rows = _collect_rows(db, project_id, payload)

    if payload.format == "csv":
        csv_bytes = generate_csv_report(rows, terminology=project.terminology)
        return file_response(csv_bytes, f"{filename_safe(project.name, fallback='project')}-requirements", "csv")

    org = db.get(Organization, project.organization_id)
    resource_markdown = _resource_sections_markdown(db, project, payload.resource_file_ids)

    template = None
    if payload.report_template_id is not None:
        template = load_report_template(db, project.organization_id, payload.report_template_id)
        if template is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid report_template_id for this project's organisation.")


    branding = resolve_branding(db, org, template)

    # Precedence: an explicit per-generation choice always wins; failing
    # that, a selected template's own setting; failing that (no template),
    # the sparse-chapter heuristic. See ReportRequest.chapters_per_component
    # and default_chapters_per_component's docstrings.
    if payload.chapters_per_component is not None:
        chapters_per_component = payload.chapters_per_component
    elif template is not None:
        chapters_per_component = template.chapters_per_component
    else:
        chapters_per_component = default_chapters_per_component(rows)

    images = resolve_report_images(db, project.organization_id, resource_markdown)
    generate = generate_docx_report if payload.format == "docx" else generate_pdf_report
    document_bytes = generate(
        project_name=project.name, rows=rows, post_markdown=resource_markdown,
        branding=branding, images=images, chapters_per_component=chapters_per_component,
    )
    return file_response(document_bytes, f"{filename_safe(project.name, fallback='project')}-requirements", payload.format)
