"""
Module: routers.reports

Report generation endpoints: PDF (R-F-01) and CSV (R-F-02) exports of a
project's requirements, with custom Markdown sections (R-G-01, R-G-02),
requirement filters (R-G-03), organisation shared resource files rendered
as additional report sections (R-G-04), and images embedded in those
Markdown sections via `_resolve_report_images` (see its docstring for the
tenant-isolation check it performs before any image reaches the PDF).
"""

from __future__ import annotations

import re
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.file import FileAsset
from app.models.organization import Organization, ReportTemplate
from app.models.project import Project, ProjectCategory, ProjectComponent
from app.models.requirement import Requirement, RequirementKeyword
from app.models.user import User
from app.schemas.report import ReportRequest
from app.services.files import read_file
from app.services.rbac import require_project_view
from app.services.reports import (
    ReportBranding,
    ReportRequirementRow,
    default_chapters_per_component,
    generate_csv_report,
    generate_pdf_report,
    resolve_report_config_with_template,
)
from app.services.requirements import get_current_version

router = APIRouter(prefix="/api/v1/projects/{project_id}/reports", tags=["reports"])


def _collect_rows(db: Session, project_id: UUID, payload: ReportRequest) -> list[ReportRequirementRow]:
    """Collects requirement rows for a report, applying R-G-03 filters."""
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
        if payload.keyword is not None:
            keywords = db.scalars(
                select(RequirementKeyword.keyword).where(RequirementKeyword.requirement_id == req.id)
            ).all()
            if payload.keyword.lower() not in keywords:
                continue
        component = components.get(req.component_id)
        category = categories.get(req.category_id)
        rows.append(ReportRequirementRow(
            unique_code=req.unique_code, name=version.name, reasoning=version.reasoning,
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


def _chapters_markdown(chapters: list[dict]) -> str:
    return "\n\n".join(f"# {c['title']}\n\n{c['body']}" for c in chapters if c.get("title"))


_ATTACHMENT_REF = re.compile(r"attachment:([0-9a-fA-F-]{36})")


def _resolve_report_images(db: Session, organization_id: UUID, *markdown_texts: str) -> dict[str, bytes]:
    """Scans one or more Markdown strings for `attachment:<uuid>` image
    references (inserted via the report content editor's attachment panel,
    `RichTextEditor`'s "Insert image") and resolves each to its bytes.

    Every resolved reference is checked against `organization_id` *and*
    restricted to `is_org_resource=True` assets before its bytes are read.
    Org scoping alone isn't enough: within a multi-project org, a direct
    (non-shared) `FileAsset` — most importantly a requirement attachment —
    is gated by *project*-level access in its own right
    (`routers/files.py::download_file` requires `get_effective_project_roles`
    for exactly that reason), which report content is never itself scoped
    to check. Without this restriction, a user with report-edit rights on
    Project A could hand-type `attachment:<id>` for a requirement
    attachment belonging to Project B in the same org — one they may have
    no project-level access to at all — and have its bytes embedded into
    Project A's report. Org shared resources have no such finer-grained
    gate (any org member can already see them, `orgs.py::list_org_resources`),
    matching what the attachment picker UI actually offers (org shared
    resources only, never a raw requirement-attachment id) — so this isn't
    a functional restriction on the real feature, only on hand-crafted
    references that were never a legitimate use of it. A reference that
    doesn't resolve — wrong org, not a shared resource, not found, not
    actually an image content type — is simply left out of the returned
    mapping; `_markdown_to_flowables` already treats a missing entry as
    "skip this image" rather than an error, so a bad reference never breaks
    report generation.
    """
    resolved: dict[str, bytes] = {}
    for text in markdown_texts:
        for match in _ATTACHMENT_REF.finditer(text):
            ref = match.group(0)
            if ref in resolved:
                continue
            try:
                file_id = UUID(match.group(1))
            except ValueError:
                continue
            asset = db.get(FileAsset, file_id)
            if (
                asset is None
                or asset.organization_id != organization_id
                or not asset.is_org_resource
                or not asset.content_type.startswith("image/")
            ):
                continue
            resolved[ref] = read_file(asset)
    return resolved


def _filename_safe(name: str) -> str:
    """Strips characters that would break a quoted `Content-Disposition`
    filename (or be awkward on a filesystem) out of a project name before
    it's used to build a downloaded report's filename."""
    return re.sub(r'[\\"/\r\n\t]', "", name).strip() or "project"


@router.post("/pdf")
def generate_pdf(
    project_id: UUID, payload: ReportRequest,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Generates a PDF requirements report (R-F-01). Falls back to the
    project's *effective* report structure (intro/chapters/appendices,
    mock's "Report Setup" — the project's own content, or the owning
    organisation's default per-field, see `resolve_report_config`) when
    the request doesn't override it with ad-hoc pre_markdown/post_markdown.

    A selected `report_template_id` sits one tier more specific than that:
    per field, the template's own intro/chapters/appendices (if it set any)
    take precedence over the project/org-resolved content — same
    independent-per-field fallback shape, just one more tier on top."""
    project = db.get(Project, project_id)
    org = db.get(Organization, project.organization_id)
    rows = _collect_rows(db, project_id, payload)
    resource_markdown = _resource_sections_markdown(db, project, payload.resource_file_ids)

    template = None
    if payload.report_template_id is not None:
        template = db.get(ReportTemplate, payload.report_template_id)
        if template is None or template.organization_id != project.organization_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid report_template_id for this project's organisation.")

    report_config = resolve_report_config_with_template(project, org, template)

    pre_markdown = payload.pre_markdown or "\n\n".join(
        s for s in [report_config.intro, _chapters_markdown([c.model_dump() for c in report_config.chapters])] if s
    )
    post_markdown = payload.post_markdown or _chapters_markdown([c.model_dump() for c in report_config.appendices])
    post_markdown = f"{post_markdown}\n\n{resource_markdown}".strip()

    branding = None
    if template is not None:
        logo_bytes = None
        if template.include_logo:
            logo_asset = db.get(FileAsset, org.logo_file_id) if org and org.logo_file_id else None
            if logo_asset is not None:
                logo_bytes = read_file(logo_asset)
        branding = ReportBranding(
            accent_color_hex=template.accent_color_hex, include_cover_page=template.include_cover_page,
            footer_text=template.footer_text, logo_bytes=logo_bytes,
        )

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

    images = _resolve_report_images(db, project.organization_id, pre_markdown, post_markdown)
    pdf_bytes = generate_pdf_report(
        project_name=project.name, pre_markdown=pre_markdown, rows=rows, post_markdown=post_markdown,
        branding=branding, images=images, chapters_per_component=chapters_per_component,
    )
    return Response(
        content=pdf_bytes, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{_filename_safe(project.name)}-requirements.pdf"'},
    )


@router.post("/csv")
def generate_csv(
    project_id: UUID, payload: ReportRequest,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Generates a CSV requirements export (R-F-02)."""
    project = db.get(Project, project_id)
    rows = _collect_rows(db, project_id, payload)
    csv_bytes = generate_csv_report(rows)
    return Response(
        content=csv_bytes, media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{_filename_safe(project.name)}-requirements.csv"'},
    )
