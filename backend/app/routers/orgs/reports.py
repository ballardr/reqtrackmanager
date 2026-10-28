"""
Module: routers.orgs.reports

Organisation report templates (R-G-05): create/list/update/delete a named
report branding preset (accent colour, cover page, logo, footer).

Split out of the former flat `routers/orgs.py` as a pure code-organization
refactor — see `routers/orgs/__init__.py`'s module docstring for the
package layout.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.enums import OrgRole
from app.models.organization import ReportTemplate
from app.models.user import User
from app.schemas.org import ReportTemplateCreate, ReportTemplateOut
from app.services.audit import log_event
from app.services.rbac import require_org_role

router = APIRouter(tags=["organizations-reports"])


def template_out(template: ReportTemplate) -> ReportTemplateOut:
    """A template as the API returns it."""
    return ReportTemplateOut(
        id=template.id, organization_id=template.organization_id, name=template.name,
        accent_color_hex=template.accent_color_hex, include_cover_page=template.include_cover_page,
        include_logo=template.include_logo, footer_text=template.footer_text,
        chapters_per_component=template.chapters_per_component,
    )


@router.post("/{organization_id}/report-templates", response_model=ReportTemplateOut, status_code=status.HTTP_201_CREATED)
def create_report_template(
    organization_id: UUID, payload: ReportTemplateCreate,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)), db: Session = Depends(get_db),
):
    """Creates a named report branding preset for this organisation (R-G-05)."""
    template = ReportTemplate(
        organization_id=organization_id, name=payload.name, accent_color_hex=payload.accent_color_hex,
        include_cover_page=payload.include_cover_page, include_logo=payload.include_logo,
        footer_text=payload.footer_text, created_by=current_user.id,
        chapters_per_component=payload.chapters_per_component,
    )
    db.add(template)
    db.flush()
    log_event(db, entity_type="report_template", entity_id=template.id, action="created",
              actor_id=current_user.id, organization_id=organization_id, detail={"name": template.name})
    db.commit()
    db.refresh(template)
    return template_out(template)


@router.get("/{organization_id}/report-templates", response_model=list[ReportTemplateOut])
def list_report_templates(
    organization_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN, OrgRole.PROJECT_CREATOR, OrgRole.MEMBER)),
    db: Session = Depends(get_db),
):
    """Lists an organisation's report templates — any org member may select
    one when generating a report, so listing isn't admin-only (only
    create/edit/delete are)."""
    templates = db.scalars(select(ReportTemplate).where(ReportTemplate.organization_id == organization_id)).all()
    return [template_out(t) for t in templates]


@router.put("/{organization_id}/report-templates/{template_id}", response_model=ReportTemplateOut)
def update_report_template(
    organization_id: UUID, template_id: UUID, payload: ReportTemplateCreate,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)), db: Session = Depends(get_db),
):
    """Updates a template's branding."""
    template = db.get(ReportTemplate, template_id)
    if template is None or template.organization_id != organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Report template not found.")
    template.name = payload.name
    template.accent_color_hex = payload.accent_color_hex
    template.include_cover_page = payload.include_cover_page
    template.include_logo = payload.include_logo
    template.footer_text = payload.footer_text
    template.chapters_per_component = payload.chapters_per_component
    log_event(db, entity_type="report_template", entity_id=template.id, action="updated",
              actor_id=current_user.id, organization_id=organization_id, detail={"name": template.name})
    db.commit()
    db.refresh(template)
    return template_out(template)


@router.delete("/{organization_id}/report-templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_report_template(
    organization_id: UUID, template_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)), db: Session = Depends(get_db),
):
    template = db.get(ReportTemplate, template_id)
    if template is None or template.organization_id != organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Report template not found.")
    log_event(db, entity_type="report_template", entity_id=template.id, action="deleted",
              actor_id=current_user.id, organization_id=organization_id, detail={"name": template.name})
    db.delete(template)
    db.commit()
