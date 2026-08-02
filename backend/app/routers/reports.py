"""
Module: routers.reports

Report generation endpoints: PDF (R-F-01) and CSV (R-F-02) exports of a
project's requirements, with custom Markdown sections (R-G-01, R-G-02),
requirement filters (R-G-03), and organisation shared resource files
rendered as additional report sections (R-G-04).
"""

from __future__ import annotations

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
from app.services.reports import ReportBranding, ReportRequirementRow, generate_csv_report, generate_pdf_report
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
        rows.append(ReportRequirementRow(
            unique_code=req.unique_code, name=version.name, reasoning=version.reasoning,
            clarification=version.clarification, status=version.status.value,
            component_name=components[req.component_id].name if req.component_id in components else "",
            category_name=categories[req.category_id].name if req.category_id in categories else "",
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


@router.post("/pdf")
def generate_pdf(
    project_id: UUID, payload: ReportRequest,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Generates a PDF requirements report (R-F-01). Falls back to the
    project's persisted report structure (intro/chapters/appendices, mock's
    "Report Setup") when the request doesn't override it with ad-hoc
    pre_markdown/post_markdown."""
    project = db.get(Project, project_id)
    rows = _collect_rows(db, project_id, payload)
    resource_markdown = _resource_sections_markdown(db, project, payload.resource_file_ids)

    pre_markdown = payload.pre_markdown or "\n\n".join(
        s for s in [project.report_intro, _chapters_markdown(project.report_chapters)] if s
    )
    post_markdown = payload.post_markdown or _chapters_markdown(project.report_appendices)
    post_markdown = f"{post_markdown}\n\n{resource_markdown}".strip()

    branding = None
    if payload.report_template_id is not None:
        template = db.get(ReportTemplate, payload.report_template_id)
        if template is None or template.organization_id != project.organization_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid report_template_id for this project's organisation.")
        logo_bytes = None
        if template.include_logo:
            org = db.get(Organization, project.organization_id)
            logo_asset = db.get(FileAsset, org.logo_file_id) if org and org.logo_file_id else None
            if logo_asset is not None:
                logo_bytes = read_file(logo_asset)
        branding = ReportBranding(
            accent_color_hex=template.accent_color_hex, include_cover_page=template.include_cover_page,
            footer_text=template.footer_text, logo_bytes=logo_bytes,
        )

    pdf_bytes = generate_pdf_report(
        project_name=project.name, pre_markdown=pre_markdown, rows=rows, post_markdown=post_markdown,
        branding=branding,
    )
    return Response(
        content=pdf_bytes, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{project.name}-requirements.pdf"'},
    )


@router.post("/csv")
def generate_csv(
    project_id: UUID, payload: ReportRequest,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Generates a CSV requirements export (R-F-02)."""
    rows = _collect_rows(db, project_id, payload)
    csv_bytes = generate_csv_report(rows)
    return Response(
        content=csv_bytes, media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="requirements.csv"'},
    )
