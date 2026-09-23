"""
Module: routers.projects.report_config

A project's own report structure (mock's "Report Setup"): the effective
(with organisation-default fallback) view, and the persisted override.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models.organization import Organization, ReportTemplate
from app.models.project import Project
from app.models.user import User
from app.schemas.report import ProjectReportConfig
from app.services.audit import log_event
from app.services.rbac import require_project_manage, require_project_view
from app.services.reports import resolve_report_config

router = APIRouter(tags=["projects-report-config"])


@router.get("/{project_id}/report-config", response_model=ProjectReportConfig)
def get_report_config(
    project_id: UUID, current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Returns the project's *effective* report structure (mock's "Report
    Setup") — its own content where set, falling back per-field to the
    owning organisation's default otherwise (`resolve_report_config`).

    Read-only, so gated to plain project view rather than manage access:
    stakeholders and members can generate reports (C-U-03) and
    `ReportsPage.tsx` fetches this same endpoint to pre-populate the
    generation page, which was silently 403ing (and, bundled into
    `ProjectAdminPage.tsx`'s single `Promise.all` reload, hanging that
    whole page on its loading spinner — the same failure class as the
    previously-fixed OrgAdminPage hang) for any caller below manager/
    administrator. `update_report_config` below stays manage-only, since
    only admins/PMs may persist changes to it.
    """
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    org = db.get(Organization, project.organization_id)
    return resolve_report_config(project, org)


@router.put("/{project_id}/report-config", response_model=ProjectReportConfig)
def update_report_config(
    project_id: UUID, payload: ProjectReportConfig,
    project: Project = Depends(require_project_manage), current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Saves the project's own persisted report structure, used as the
    default report content on generation unless overridden ad hoc. Saving
    a blank field here reverts that field to the organisation's default
    (if one is set), rather than forcing genuinely empty content — see
    `resolve_report_config`.

    `default_report_template_id`, if set, must be a template belonging to
    this project's own organisation (400 otherwise) — the same cross-org
    check `generate_pdf` already applies to an ad-hoc `report_template_id`."""
    if payload.default_report_template_id is not None:
        template = db.get(ReportTemplate, payload.default_report_template_id)
        if template is None or template.organization_id != project.organization_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid default_report_template_id for this project's organisation.")
    project.report_intro = payload.intro
    project.report_chapters = [c.model_dump() for c in payload.chapters]
    project.report_appendices = [c.model_dump() for c in payload.appendices]
    project.default_report_template_id = payload.default_report_template_id
    log_event(db, entity_type="project", entity_id=project_id, action="report_config_updated",
              actor_id=current_user.id, project_id=project_id, organization_id=project.organization_id)
    db.commit()
    db.refresh(project)
    org = db.get(Organization, project.organization_id)
    return resolve_report_config(project, org)
