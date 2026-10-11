"""
Module: routers.orgs.reports

Organisation report templates (R-G-05): create/list/update/delete a named
PDF report branding preset (with its per-report-type intro/chapters/appendices),
plus the organisation-level default content per report type a project falls
back to, and the list of report types content can be written for.

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
from app.models.organization import Organization, ReportTemplate
from app.models.report_content import SCOPE_ORGANIZATION, SCOPE_TEMPLATE
from app.models.user import User
from app.schemas.org import ReportTemplateCreate, ReportTemplateOut
from app.schemas.report import OrgReportDefaults
from app.services.audit import log_event
from app.services.rbac import require_org_role
from app.services.report_content import (
    ReportTypeOption,
    content_entries,
    delete_content_for_scopes,
    replace_scope_content,
    report_type_options,
)

router = APIRouter(tags=["organizations-reports"])


def template_out(db: Session, template: ReportTemplate) -> ReportTemplateOut:
    """A template with the content it owns."""
    return ReportTemplateOut(
        id=template.id, organization_id=template.organization_id, name=template.name,
        accent_color_hex=template.accent_color_hex, include_cover_page=template.include_cover_page,
        include_logo=template.include_logo, footer_text=template.footer_text,
        chapters_per_component=template.chapters_per_component,
        content=content_entries(db, SCOPE_TEMPLATE, template.id),
    )


@router.get("/{organization_id}/report-types", response_model=list[ReportTypeOption])
def list_report_types(
    organization_id: UUID,
    current_user: User = Depends(require_org_role(*OrgRole)), db: Session = Depends(get_db),
):
    """The report types content can be written for in this organisation: the
    requirements report and every report of a module enabled for it. Any org
    member may list them (the editors that use them are gated separately)."""
    return report_type_options(db, organization_id)


@router.post("/{organization_id}/report-templates", response_model=ReportTemplateOut, status_code=status.HTTP_201_CREATED)
def create_report_template(
    organization_id: UUID, payload: ReportTemplateCreate,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)), db: Session = Depends(get_db),
):
    """Creates a named PDF report branding preset for this organisation
    (R-G-05), with any per-report-type content it carries."""
    template = ReportTemplate(
        organization_id=organization_id, name=payload.name, accent_color_hex=payload.accent_color_hex,
        include_cover_page=payload.include_cover_page, include_logo=payload.include_logo,
        footer_text=payload.footer_text, created_by=current_user.id,
        chapters_per_component=payload.chapters_per_component,
    )
    db.add(template)
    db.flush()
    replace_scope_content(db, SCOPE_TEMPLATE, template.id, payload.content)
    log_event(db, entity_type="report_template", entity_id=template.id, action="created",
              actor_id=current_user.id, organization_id=organization_id, detail={"name": template.name})
    db.commit()
    db.refresh(template)
    return template_out(db, template)


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
    return [template_out(db, t) for t in templates]


@router.put("/{organization_id}/report-templates/{template_id}", response_model=ReportTemplateOut)
def update_report_template(
    organization_id: UUID, template_id: UUID, payload: ReportTemplateCreate,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)), db: Session = Depends(get_db),
):
    """Updates a template's branding and replaces the content it owns with
    `payload.content` (a report type absent from it loses its content)."""
    template = db.get(ReportTemplate, template_id)
    if template is None or template.organization_id != organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Report template not found.")
    template.name = payload.name
    template.accent_color_hex = payload.accent_color_hex
    template.include_cover_page = payload.include_cover_page
    template.include_logo = payload.include_logo
    template.footer_text = payload.footer_text
    template.chapters_per_component = payload.chapters_per_component
    replace_scope_content(db, SCOPE_TEMPLATE, template.id, payload.content)
    log_event(db, entity_type="report_template", entity_id=template.id, action="updated",
              actor_id=current_user.id, organization_id=organization_id, detail={"name": template.name})
    db.commit()
    db.refresh(template)
    return template_out(db, template)


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
    delete_content_for_scopes(db, SCOPE_TEMPLATE, [template.id])
    db.delete(template)
    db.commit()


@router.get("/{organization_id}/report-defaults", response_model=OrgReportDefaults)
def get_org_report_defaults(
    organization_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """Returns the content this organisation holds per report type — what a
    project falls back to when neither it nor its ancestors set their own
    (`services.report_content.resolve_report_content`)."""
    if db.get(Organization, organization_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    return OrgReportDefaults(content=content_entries(db, SCOPE_ORGANIZATION, organization_id))


@router.put("/{organization_id}/report-defaults", response_model=OrgReportDefaults)
def update_org_report_defaults(
    organization_id: UUID, payload: OrgReportDefaults,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """Replaces the organisation's default content with `payload.content`.
    A blank entry (or a report type left out) removes that type's default, so
    "no default" is the absence of a row rather than a stored empty value."""
    if db.get(Organization, organization_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    replace_scope_content(db, SCOPE_ORGANIZATION, organization_id, payload.content)
    log_event(db, entity_type="organization", entity_id=organization_id, action="report_defaults_updated",
              actor_id=current_user.id, organization_id=organization_id)
    db.commit()
    return OrgReportDefaults(content=content_entries(db, SCOPE_ORGANIZATION, organization_id))
