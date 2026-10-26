"""
Module: routers.projects.report_config

A project's own report setup (the "Report Setup" tab): its default report
template and the introduction/chapters/appendices it owns per report type, plus
the read-only views the editors and the generation page need — the report types
available, and the *effective* content a given report type would use with where
each field came from (own, an ancestor project, the organisation, a template).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models.organization import Organization, ReportTemplate
from app.models.project import Project
from app.models.report_content import SCOPE_PROJECT
from app.models.user import User
from app.schemas.report import (
    EffectiveReportContentOut,
    ProjectReportConfig,
    ReportChapter,
    ReportContentSourceOut,
)
from app.services.audit import log_event
from app.services.rbac import require_project_manage, require_project_view
from app.services.report_content import (
    ReportTypeOption,
    content_entries,
    is_valid_report_key,
    replace_scope_content,
    report_type_options,
    resolve_report_content,
)

router = APIRouter(tags=["projects-report-config"])


def _config(db: Session, project: Project) -> ProjectReportConfig:
    return ProjectReportConfig(
        default_report_template_id=project.default_report_template_id,
        content=content_entries(db, SCOPE_PROJECT, project.id),
    )


def _source_out(source) -> ReportContentSourceOut | None:
    if source is None:
        return None
    return ReportContentSourceOut(
        scope_type=source.scope_type, scope_id=source.scope_id, scope_name=source.scope_name, report_key=source.report_key,
    )


@router.get("/{project_id}/report-config", response_model=ProjectReportConfig)
def get_report_config(
    project_id: UUID, current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Returns what the project itself holds: its default template and its own
    content per report type (not what it inherits; see
    `get_effective_report_content`).

    Read-only, so gated to plain project view rather than manage access:
    stakeholders and members can generate reports (C-U-03) and the generation
    page fetches the default template from here. `update_report_config` below
    stays manage-only.
    """
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    return _config(db, project)


@router.put("/{project_id}/report-config", response_model=ProjectReportConfig)
def update_report_config(
    project_id: UUID, payload: ProjectReportConfig,
    project: Project = Depends(require_project_manage), current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Replaces the project's own report setup: its default template and the
    content it owns. A blank entry, or a report type left out, removes that
    type's own content so the project inherits again.

    `default_report_template_id`, if set, must be a template belonging to this
    project's own organisation (400 otherwise); an unknown or repeated report
    type is a 400."""
    if payload.default_report_template_id is not None:
        template = db.get(ReportTemplate, payload.default_report_template_id)
        if template is None or template.organization_id != project.organization_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid default_report_template_id for this project's organisation.")
    replace_scope_content(db, SCOPE_PROJECT, project.id, payload.content)
    project.default_report_template_id = payload.default_report_template_id
    log_event(db, entity_type="project", entity_id=project_id, action="report_config_updated",
              actor_id=current_user.id, project_id=project_id, organization_id=project.organization_id)
    db.commit()
    db.refresh(project)
    return _config(db, project)


@router.get("/{project_id}/report-types", response_model=list[ReportTypeOption])
def list_project_report_types(
    project_id: UUID, current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """The report types content can be written for in this project's
    organisation (the requirements report and each enabled module's reports)."""
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    return report_type_options(db, project.organization_id, project)


@router.get("/{project_id}/report-content/effective", response_model=EffectiveReportContentOut)
def get_effective_report_content(
    project_id: UUID,
    report_key: str = Query("requirements", min_length=1, max_length=100),
    template_id: UUID | None = Query(None),
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """The introduction, chapters and appendices a report of `report_key` run on
    this project would use, resolved through the selected template (if any), the
    project, its ancestors and the organisation, each field with its source.
    Shown on the generation page and as the "inherited" hint in the Report Setup
    editor; the same resolution generation itself uses.

    Raises:
        HTTPException: 400 for an unknown report type or a template of another organisation.
    """
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    if not is_valid_report_key(db, report_key, SCOPE_PROJECT, project.id) or report_key == "*":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown report type '{report_key}'.")
    template = None
    if template_id is not None:
        template = db.get(ReportTemplate, template_id)
        if template is None or template.organization_id != project.organization_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid template_id for this project's organisation.")
    org = db.get(Organization, project.organization_id)
    resolved = resolve_report_content(db, report_key, org, project, template)
    return EffectiveReportContentOut(
        report_key=report_key, intro=resolved.intro.value,
        chapters=[ReportChapter(**c) for c in resolved.chapters.value],
        appendices=[ReportChapter(**c) for c in resolved.appendices.value],
        intro_source=_source_out(resolved.intro.source), chapters_source=_source_out(resolved.chapters.source),
        appendices_source=_source_out(resolved.appendices.source),
    )
