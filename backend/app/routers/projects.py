"""
Module: routers.projects

Project CRUD, stages (with approval -> baseline), components/categories
(with ordering, C-E-01/C-E-02), project groups and role assignment
(C-U-10, C-U-11) — including by-email assignment for a user outside the
project's organisation, gated by `Organization.external_user_policy` (see
`assign_project_role_by_email`/`services/invites.py`) — and the project
overview metrics endpoint (U-P-05).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models.change_request import ChangeRequest, ChangeRequestVersion
from app.models.enums import ChangeRequestStatus, ExternalUserPolicy, OrgRole, ProjectRole, RequirementStatus, StageStatus
from app.models.file import RequirementFile
from app.models.notification import NotificationType
from app.models.organization import Organization, OrgGroup, ReportTemplate, UserOrgRole
from app.models.project import (
    FavoriteProject,
    Project,
    ProjectCategory,
    ProjectComponent,
    ProjectGroup,
    ProjectGroupMember,
    ProjectStage,
    StageReviewResponse,
    UserProjectRole,
)
from app.models.requirement import Baseline, BaselineItem, Requirement, RequirementVersion
from app.models.user import User
from app.schemas.changes import ChangeEntryOut
from app.schemas.project import (
    AssignByEmailOut,
    CategoryCreate,
    CategoryOut,
    CategoryUpdate,
    ComponentCreate,
    ComponentOut,
    ComponentUpdate,
    MoveDirection,
    ProjectCreate,
    ProjectGroupCreate,
    ProjectGroupMemberAdd,
    ProjectGroupOut,
    ProjectImportResult,
    ProjectListItemOut,
    ProjectMetricsOut,
    ProjectOut,
    ProjectStageCreate,
    ProjectStageOut,
    ProjectStageUpdate,
    ProjectUpdate,
    StageCompleteRequest,
    StageProgressOut,
    StageReviewDeadlineSet,
    StageReviewResponseCreate,
    StageReviewResponseOut,
    TerminologyUpdate,
    UserProjectRoleAssign,
    UserProjectRoleAssignByEmail,
)
from app.schemas.report import ProjectReportConfig
from app.services import engagement, invites
from app.services.audit import log_event
from app.services.baseline import create_baseline_for_stage
from app.services.changes import get_project_changes
from app.services.downloads import filename_safe
from app.services.notifications import notify
from app.services.project_export import build_project_bundle, import_project_bundle
from app.services.rbac import (
    check_pat_scope,
    get_effective_org_roles,
    get_effective_project_roles,
    get_project_managers,
    get_project_member_user_ids,
    lock_project_for_update,
    require_project_manage,
    require_project_view,
    require_project_view_or_manage,
)
from app.services.reports import resolve_report_config
from app.services.stages import complete_stage
from app.services.templates import clone_project

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])

DEFAULT_GROUPS = [
    ("Project Managers", ProjectRole.PROJECT_MANAGER),
    ("Project Administrators", ProjectRole.PROJECT_ADMINISTRATOR),
    ("Stakeholders", ProjectRole.STAKEHOLDER),
    ("Members", ProjectRole.MEMBER),
]


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
def create_project(
    payload: ProjectCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Creates a project within an organisation (C-U-01: project_creator/org_admin).

    On creation, the four standard project groups are created and the
    creator is added to the Project Managers group (C-U-10) — unless a
    template project is used (C-E-05), per C-U-10's explicit "unless using
    a template project" clause: groups/members are copied from the template
    instead. If that leaves the new project with no manager at all, the
    creator is still added as a fallback so C-U-08 (every project must have
    a manager) can never be violated.

    `organization_id` lives in the request body here (the project doesn't
    exist yet to have a path segment of its own), so — unlike every other
    org/project-scoped endpoint — it isn't covered by `require_org_role`'s
    or `require_project_*`'s built-in PAT-scope check; enforced explicitly
    here instead.
    """
    check_pat_scope(request, payload.organization_id)
    org_roles = get_effective_org_roles(db, current_user.id, payload.organization_id)
    if not org_roles & {OrgRole.ORG_ADMIN, OrgRole.PROJECT_CREATOR}:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only org admins or project creators may create projects.")

    template_project_id = payload.template_project_id
    if template_project_id is None:
        # C-E-04: fall back to the organisation's configured default template
        # when the caller didn't specify one. The frontend's "New project"
        # form pre-selects this same default in its template dropdown so a
        # user can still explicitly override it before submitting.
        org = db.get(Organization, payload.organization_id)
        if org is not None:
            template_project_id = org.default_template_project_id

    if template_project_id is not None:
        template = db.get(Project, template_project_id)
        if (
            template is None
            or template.organization_id != payload.organization_id
            or not template.is_template
        ):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "template_project_id must be a template project in this organisation.")
        project = clone_project(db, template, name=payload.name, summary=payload.summary, creator=current_user)
        db.flush()
        if not get_project_managers(db, project.id):
            fallback_group = db.scalar(
                select(ProjectGroup).where(ProjectGroup.project_id == project.id, ProjectGroup.role == ProjectRole.PROJECT_MANAGER)
            )
            if fallback_group is not None:
                db.add(ProjectGroupMember(project_group_id=fallback_group.id, user_id=current_user.id))
            else:
                db.add(UserProjectRole(user_id=current_user.id, project_id=project.id, role=ProjectRole.PROJECT_MANAGER))
    else:
        project = Project(organization_id=payload.organization_id, name=payload.name, summary=payload.summary)
        db.add(project)
        db.flush()

        db.add(ProjectStage(project_id=project.id, name="Scoping", status=StageStatus.SCOPING, sort_order=0, is_current=True))

        manager_group = None
        for name, role in DEFAULT_GROUPS:
            group = ProjectGroup(project_id=project.id, name=name, role=role, is_default=True)
            db.add(group)
            db.flush()
            if role == ProjectRole.PROJECT_MANAGER:
                manager_group = group
        if manager_group is not None:
            db.add(ProjectGroupMember(project_group_id=manager_group.id, user_id=current_user.id))

    if payload.terminology:
        project.terminology = payload.terminology
    if payload.is_template:
        project.is_template = True

    log_event(
        db, entity_type="project", entity_id=project.id, action="created", actor_id=current_user.id,
        organization_id=payload.organization_id, project_id=project.id,
        detail={"template_project_id": str(template_project_id)} if template_project_id else None,
    )
    db.commit()
    db.refresh(project)
    return project


@router.post("/import", response_model=ProjectImportResult, status_code=status.HTTP_201_CREATED)
async def import_project(
    request: Request,
    organization_id: UUID = Form(...), name: str = Form(...), summary: str | None = Form(None),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Creates a brand-new project in `organization_id` from an uploaded
    project export bundle (`GET /{project_id}/export` — see
    `services.project_export`'s module docstring for the full bundle
    contents: structure, custom field definitions, and full history).

    Authorization mirrors plain project creation (`POST /projects`) exactly
    — org admins or project creators of the *target* organisation — which
    is what makes cross-organisation import safe: the bundle itself carries
    no ids or org references, only names/prefixes/emails resolved fresh
    against whatever org the caller is authorized to create in.

    Registered before `GET /{project_id}` so the static "/import" path
    isn't swallowed by that dynamic route.
    """
    check_pat_scope(request, organization_id)
    org_roles = get_effective_org_roles(db, current_user.id, organization_id)
    if not org_roles & {OrgRole.ORG_ADMIN, OrgRole.PROJECT_CREATOR}:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only org admins or project creators may create projects.")

    zip_bytes = await file.read()
    project, warnings = import_project_bundle(
        db, organization_id=organization_id, name=name, summary=summary, zip_bytes=zip_bytes, current_user=current_user
    )
    return ProjectImportResult(project=ProjectOut.model_validate(project), warnings=warnings)


@router.get("", response_model=list[ProjectListItemOut])
def list_projects(
    response: Response,
    archived: bool = False,
    search: str | None = None,
    role: ProjectRole | None = None,
    stage_status: StageStatus | None = None,
    organization_id: UUID | None = None,
    limit: int | None = Query(None, ge=1),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Project list view (U-E-03, U-E-04): active/archived projects the user can access.

    Supports an optional `role` filter (only projects where the caller holds
    the given effective project role), `stage_status` filter (only projects
    whose current stage is in the given status) for U-E-05, and
    `organization_id` (only projects in that organisation — for a user
    belonging to more than one, this replaces having to visit each
    organisation separately to see just its projects). Results are sorted
    with the caller's favourited projects (U-U-03) first, then by name.
    `limit`/`offset` (U-P-06) are optional pagination — see
    `list_requirements` for the same pattern and its rationale.
    """
    # No server-admin bypass here (I-M-05): project listings are "data within
    # organisations", so even server admins only see projects they hold a
    # genuine role in, same as anyone else.
    project_ids_via_role = set(
        db.scalars(select(UserProjectRole.project_id).where(UserProjectRole.user_id == current_user.id)).all()
    )
    project_ids_via_group = set(
        db.scalars(
            select(ProjectGroup.project_id)
            .join(ProjectGroupMember, ProjectGroupMember.project_group_id == ProjectGroup.id)
            .where(ProjectGroupMember.user_id == current_user.id)
        ).all()
    )
    accessible_ids = project_ids_via_role | project_ids_via_group
    if not accessible_ids:
        projects = []
    else:
        # Joins to Organization to exclude projects belonging to a disabled
        # org (`Organization.is_active`) — a disabled org locks out its own
        # content everywhere else (`rbac._require_org_active`), and this
        # aggregate cross-org listing had been the one place that check
        # didn't reach, since it filters by project accessible-ids rather
        # than going through a per-org `require_org_role` dependency.
        conditions = [
            Project.id.in_(accessible_ids),
            Project.is_archived == archived,
            Organization.is_active.is_(True),
        ]
        if organization_id is not None:
            conditions.append(Project.organization_id == organization_id)
        projects = db.scalars(
            select(Project).join(Organization, Organization.id == Project.organization_id).where(*conditions)
        ).all()

    if search:
        needle = search.lower()
        projects = [p for p in projects if needle in p.name.lower() or needle in p.summary.lower()]

    favorite_ids = set(
        db.scalars(select(FavoriteProject.project_id).where(FavoriteProject.user_id == current_user.id)).all()
    )
    org_names = dict(
        db.execute(
            select(Organization.id, Organization.name).where(
                Organization.id.in_({p.organization_id for p in projects})
            )
        ).all()
    )
    requirement_counts = dict(
        db.execute(
            select(Requirement.project_id, func.count(Requirement.id))
            .where(Requirement.project_id.in_({p.id for p in projects}), Requirement.is_archived.is_(False))
            .group_by(Requirement.project_id)
        ).all()
    )

    out = []
    for p in projects:
        stage = db.scalar(
            select(ProjectStage).where(ProjectStage.project_id == p.id, ProjectStage.is_current.is_(True))
        )
        if stage_status is not None and (stage is None or stage.status != stage_status):
            continue
        roles = sorted(get_effective_project_roles(db, current_user.id, p.id), key=lambda r: r.value)
        if role is not None and role not in roles:
            continue
        out.append(
            ProjectListItemOut(
                id=p.id, organization_id=p.organization_id, name=p.name, summary=p.summary,
                created_at=p.created_at, updated_at=p.updated_at,
                is_archived=p.is_archived, is_template=p.is_template,
                allow_member_change_requests=p.allow_member_change_requests, terminology=p.terminology,
                current_stage_name=stage.name if stage else None,
                current_stage_status=stage.status if stage else None,
                my_roles=list(roles),
                is_favorite=p.id in favorite_ids,
                organization_name=org_names.get(p.organization_id, ""),
                requirement_count=requirement_counts.get(p.id, 0),
            )
        )
    out.sort(key=lambda item: (not item.is_favorite, item.name.lower()))

    response.headers["X-Total-Count"] = str(len(out))
    if limit is not None:
        out = out[offset:offset + limit]
    return out


@router.put("/{project_id}/favorite", status_code=status.HTTP_204_NO_CONTENT)
def set_favorite_project(
    project_id: UUID,
    current_user: User = Depends(require_project_view),
    db: Session = Depends(get_db),
):
    """Marks a project as a favourite for the current user (U-U-03)."""
    existing = db.scalar(
        select(FavoriteProject).where(FavoriteProject.user_id == current_user.id, FavoriteProject.project_id == project_id)
    )
    if existing is None:
        db.add(FavoriteProject(user_id=current_user.id, project_id=project_id))
        db.commit()


@router.delete("/{project_id}/favorite", status_code=status.HTTP_204_NO_CONTENT)
def unset_favorite_project(
    project_id: UUID,
    current_user: User = Depends(require_project_view),
    db: Session = Depends(get_db),
):
    """Removes a project from the current user's favourites (U-U-03)."""
    existing = db.scalar(
        select(FavoriteProject).where(FavoriteProject.user_id == current_user.id, FavoriteProject.project_id == project_id)
    )
    if existing is not None:
        db.delete(existing)
        db.commit()


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: UUID, current_user: User = Depends(require_project_view), db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    return project


@router.get("/{project_id}/export")
def export_project(project: Project = Depends(require_project_manage), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Exports this project's full structure and history as a self-
    describing zip bundle (see `services.project_export`'s module
    docstring) — directly re-importable via `POST /projects/import`, into
    this organisation or a different one, to create a brand-new project.

    Same authorization as the other structural-admin endpoints
    (`require_project_manage`): project managers, project administrators,
    or organisation admins of this project's organisation.
    """
    zip_bytes = build_project_bundle(db, project, current_user)
    return Response(
        content=zip_bytes, media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename_safe(project.name, fallback="project")}-export.zip"'},
    )


@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: UUID, payload: ProjectUpdate,
    project: Project = Depends(require_project_manage), current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Updates project settings: name/summary, the member change-request
    toggle (C-U-13), and the template flag (C-E-05)."""
    if payload.name is not None:
        project.name = payload.name
    if payload.summary is not None:
        project.summary = payload.summary
    if payload.allow_member_change_requests is not None:
        project.allow_member_change_requests = payload.allow_member_change_requests
    if payload.is_template is not None:
        project.is_template = payload.is_template
    log_event(db, entity_type="project", entity_id=project_id, action="settings_updated",
              actor_id=current_user.id, project_id=project_id, organization_id=project.organization_id)
    db.commit()
    db.refresh(project)
    return project


@router.put("/{project_id}/terminology", response_model=ProjectOut)
def update_terminology(
    project_id: UUID, payload: TerminologyUpdate,
    project: Project = Depends(require_project_manage), current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Sets per-project terminology overrides (C-C-03), e.g. {"stage": "Horizon"}."""
    project.terminology = payload.terminology
    log_event(db, entity_type="project", entity_id=project_id, action="terminology_updated",
              actor_id=current_user.id, project_id=project_id, organization_id=project.organization_id)
    db.commit()
    db.refresh(project)
    return project


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


@router.post("/{project_id}/archive", response_model=ProjectOut)
def archive_project(
    project_id: UUID, project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Archives a project: hidden from the active project list, data preserved (C-P-01)."""
    from datetime import datetime

    project.is_archived = True
    project.archived_at = datetime.now(UTC)
    project.archived_by = current_user.id
    log_event(db, entity_type="project", entity_id=project.id, action="archived",
              actor_id=current_user.id, project_id=project.id)
    db.commit()
    db.refresh(project)
    return project


@router.post("/{project_id}/unarchive", response_model=ProjectOut)
def unarchive_project(
    project_id: UUID, project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Restores an archived project to the active project list (C-P-01)."""
    project.is_archived = False
    project.archived_at = None
    project.archived_by = None
    log_event(db, entity_type="project", entity_id=project.id, action="unarchived",
              actor_id=current_user.id, project_id=project.id)
    db.commit()
    db.refresh(project)
    return project


@router.get("/{project_id}/changes", response_model=list[ChangeEntryOut])
def get_project_changes_endpoint(
    project_id: UUID,
    since: datetime | None = None,
    until: datetime | None = None,
    include_comments: bool = False,
    entity_type: str | None = None,
    current_user: User = Depends(require_project_view),
    db: Session = Depends(get_db),
):
    """Project changes-over-time view (C-A-10): a unified timeline of
    requirement/change-request/audit events, with an optional time range
    and entity-type filter. Discussion comments are excluded unless
    `include_comments=true`."""
    return get_project_changes(
        db, project_id, since=since, until=until, include_comments=include_comments, entity_type=entity_type,
    )


@router.get("/{project_id}/metrics", response_model=ProjectMetricsOut)
def get_project_metrics(
    project_id: UUID, current_user: User = Depends(require_project_view), db: Session = Depends(get_db)
):
    """Project overview dashboard metrics (U-P-05)."""
    requirement_ids = db.scalars(
        select(Requirement.id).where(Requirement.project_id == project_id, Requirement.is_archived.is_(False))
    ).all()
    requirement_count = len(requirement_ids)
    completed = 0
    if requirement_ids:
        completed = len(
            db.scalars(
                select(RequirementVersion.requirement_id).where(
                    RequirementVersion.requirement_id.in_(requirement_ids),
                    RequirementVersion.valid_to.is_(None),
                    RequirementVersion.status == RequirementStatus.COMPLETED,
                )
            ).all()
        )
    percent = (completed / requirement_count * 100.0) if requirement_count else 0.0

    proposed = len(
        db.scalars(
            select(ChangeRequest.id).where(
                ChangeRequest.project_id == project_id,
                ChangeRequest.status.in_([ChangeRequestStatus.SUBMITTED, ChangeRequestStatus.IN_REVIEW]),
            )
        ).all()
    )
    approved = len(
        db.scalars(
            select(ChangeRequest.id).where(
                ChangeRequest.project_id == project_id, ChangeRequest.status == ChangeRequestStatus.APPROVED
            )
        ).all()
    )
    rejected = len(
        db.scalars(
            select(ChangeRequest.id).where(
                ChangeRequest.project_id == project_id, ChangeRequest.status == ChangeRequestStatus.REJECTED
            )
        ).all()
    )

    requirements_by_status: dict[str, int] = {}
    if requirement_ids:
        for status_value in db.scalars(
            select(RequirementVersion.status).where(
                RequirementVersion.requirement_id.in_(requirement_ids), RequirementVersion.valid_to.is_(None)
            )
        ).all():
            requirements_by_status[status_value.value] = requirements_by_status.get(status_value.value, 0) + 1

    # Per-stage progress (dashboard "Stage Progress" chart): a stage that has
    # been baselined (C-G-10) shows completion across the requirements
    # captured in that baseline; a stage not yet approved has no baseline
    # yet, so it shows the project's current requirement count at 0%
    # complete rather than a stage-specific count that doesn't exist yet.
    stages = db.scalars(
        select(ProjectStage).where(ProjectStage.project_id == project_id).order_by(ProjectStage.sort_order)
    ).all()
    stage_progress: list[StageProgressOut] = []
    for stage in stages:
        baseline = db.scalar(
            select(Baseline).where(Baseline.project_id == project_id, Baseline.stage_id == stage.id)
        )
        if baseline is not None:
            item_requirement_ids = db.scalars(
                select(BaselineItem.requirement_id).where(BaselineItem.baseline_id == baseline.id)
            ).all()
            stage_requirement_count = len(item_requirement_ids)
            stage_completed = 0
            if item_requirement_ids:
                stage_completed = len(
                    db.scalars(
                        select(RequirementVersion.requirement_id).where(
                            RequirementVersion.requirement_id.in_(item_requirement_ids),
                            RequirementVersion.valid_to.is_(None),
                            RequirementVersion.status == RequirementStatus.COMPLETED,
                        )
                    ).all()
                )
            stage_percent = (stage_completed / stage_requirement_count * 100.0) if stage_requirement_count else 0.0
        else:
            stage_requirement_count = requirement_count
            stage_percent = 0.0
        stage_progress.append(
            StageProgressOut(
                stage_id=stage.id, name=stage.name, status=stage.status,
                requirement_count=stage_requirement_count, completed_percent=round(stage_percent, 1),
            )
        )

    file_count = 0
    if requirement_ids:
        file_count = len(
            set(
                db.scalars(
                    select(RequirementFile.file_id).where(RequirementFile.requirement_id.in_(requirement_ids))
                ).all()
            )
        )

    return ProjectMetricsOut(
        requirement_count=requirement_count,
        requirement_completed_percent=round(percent, 1),
        change_requests_proposed=proposed,
        change_requests_approved=approved,
        change_requests_rejected=rejected,
        file_count=file_count,
        requirements_by_status=requirements_by_status,
        stage_progress=stage_progress,
    )


# --- Stages -----------------------------------------------------------------


@router.post("/{project_id}/stages", response_model=ProjectStageOut, status_code=status.HTTP_201_CREATED)
def create_stage(
    payload: ProjectStageCreate,
    project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Adds a new project stage (C-G-08), starting in scoping status.

    Notifies project members that a new stage has entered scoping (C-N-01)
    — this is never the "brand new project" case the requirement excludes,
    since a project's very first stage is created directly in
    `create_project`, not through this endpoint.
    """
    count = len(db.scalars(select(ProjectStage.id).where(ProjectStage.project_id == project.id)).all())
    stage = ProjectStage(project_id=project.id, name=payload.name, status=StageStatus.SCOPING, sort_order=count)
    db.add(stage)
    db.flush()
    log_event(db, entity_type="project_stage", entity_id=stage.id, action="created",
              actor_id=current_user.id, project_id=project.id)
    _notify_stage_transition(db, project, stage)
    db.commit()
    db.refresh(stage)
    return stage


@router.get("/{project_id}/stages", response_model=list[ProjectStageOut])
def list_stages(project_id: UUID, current_user: User = Depends(require_project_view), db: Session = Depends(get_db)):
    return db.scalars(
        select(ProjectStage).where(ProjectStage.project_id == project_id).order_by(ProjectStage.sort_order)
    ).all()


@router.patch("/{project_id}/stages/{stage_id}", response_model=ProjectStageOut)
def rename_stage(
    project_id: UUID, stage_id: UUID, payload: ProjectStageUpdate,
    project: Project = Depends(require_project_manage), current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stage = db.get(ProjectStage, stage_id)
    if stage is None or stage.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Stage not found.")
    existing = db.scalar(
        select(ProjectStage.id).where(
            ProjectStage.project_id == project.id, ProjectStage.name == payload.name, ProjectStage.id != stage_id
        )
    )
    if existing is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A stage with this name already exists.")
    stage.name = payload.name
    log_event(db, entity_type="project_stage", entity_id=stage.id, action="renamed",
              actor_id=current_user.id, project_id=project.id)
    db.commit()
    db.refresh(stage)
    return stage


@router.delete("/{project_id}/stages/{stage_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_stage(
    project_id: UUID, stage_id: UUID, reassign_to: UUID,
    project: Project = Depends(require_project_manage), current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Deletes a stage, reassigning every requirement version and
    change-request proposal that ever targeted it to `reassign_to` first —
    `RequirementVersion.target_stage_id` is mandatory (never null), so this
    isn't optional the way unlinking a file is.

    Refuses to delete a stage any approved baseline snapshots (C-G-10):
    a `Baseline` is documented as an *immutable* record of what a specific
    stage's approved requirements looked like, and silently repointing it
    at a different stage would quietly rewrite what that snapshot means.
    Archiving/renaming is always available instead; only a stage with no
    baseline history can be removed outright. `reassign_to` must be a
    different, existing stage in the same project — if this is the
    project's only stage, no valid target exists and deletion is refused
    (a project must always have at least one stage).
    """
    stage = db.get(ProjectStage, stage_id)
    if stage is None or stage.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Stage not found.")
    if reassign_to == stage_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "reassign_to must be a different stage.")
    target = db.get(ProjectStage, reassign_to)
    if target is None or target.project_id != project.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "reassign_to must be an existing stage in this project.")
    has_baseline = db.scalar(select(Baseline.id).where(Baseline.stage_id == stage_id)) is not None
    if has_baseline:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This stage has an approved baseline and can't be deleted — baselines are immutable history.",
        )
    db.execute(
        RequirementVersion.__table__.update()
        .where(RequirementVersion.target_stage_id == stage_id)
        .values(target_stage_id=reassign_to)
    )
    db.execute(
        ChangeRequestVersion.__table__.update()
        .where(ChangeRequestVersion.proposed_target_stage_id == stage_id)
        .values(proposed_target_stage_id=reassign_to)
    )
    if stage.is_current:
        target.is_current = True
    log_event(db, entity_type="project_stage", entity_id=stage_id, action="deleted",
              actor_id=current_user.id, project_id=project.id, detail={"reassigned_to": str(reassign_to)})
    db.delete(stage)
    db.commit()


#: Explicit forward-only lifecycle transitions this endpoint permits, keyed
#: by the stage's *current* status. COMPLETED is deliberately absent as a
#: value here — it's only reachable via the dedicated `/stages/{id}/complete`
#: endpoint (C-P-02), which also handles the `cascade_to_requirements` flag
#: and doesn't belong in a generic status-setter. ARCHIVED is reachable from
#: any non-terminal status, matching its own documented purpose as a manual,
#: no-special-gating display/filtering state (see `StageStatus`'s docstring).
_ALLOWED_STAGE_TRANSITIONS: dict[StageStatus, set[StageStatus]] = {
    StageStatus.SCOPING: {StageStatus.REVIEW, StageStatus.ARCHIVED},
    StageStatus.REVIEW: {StageStatus.APPROVED, StageStatus.ARCHIVED},
    StageStatus.APPROVED: {StageStatus.ARCHIVED},
}


@router.post("/{project_id}/stages/{stage_id}/transition", response_model=ProjectStageOut)
def transition_stage(
    project_id: UUID,
    stage_id: UUID,
    new_status: StageStatus,
    project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Transitions a stage's lifecycle status.

    Approving a stage (-> APPROVED) writes an immutable baseline (C-G-10)
    and, from that point on, locks direct requirement edits project-wide
    until further change requests are approved (C-G-12). This transition
    requires the project manager role specifically (C-U-03 clarification),
    not just general settings-management access.

    Only the forward transitions in `_ALLOWED_STAGE_TRANSITIONS` are
    accepted (plus the always-available move to ARCHIVED) — a stage can't
    skip a step (e.g. straight from SCOPING to APPROVED, bypassing the
    review-deadline/stakeholder-response workflow, C-R-05) or move
    backwards (e.g. APPROVED back to SCOPING, which would silently unlock
    already-locked requirements outside the change-request process,
    C-G-12). COMPLETED is intentionally not settable here at all; see
    `/stages/{stage_id}/complete`.
    """
    stage = db.get(ProjectStage, stage_id)
    if stage is None or stage.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Stage not found.")

    # Role check before state-machine check for APPROVED specifically, so an
    # unauthorized caller always gets a uniform 403 rather than a 409 that
    # would leak the stage's current status to someone who can't act on it
    # anyway (matches C-U-03's PM-only approval gate being checked first
    # everywhere else in this file).
    if new_status == StageStatus.APPROVED:
        if ProjectRole.PROJECT_MANAGER not in get_effective_project_roles(db, current_user.id, project.id):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a project manager can approve a stage.")

    allowed = _ALLOWED_STAGE_TRANSITIONS.get(stage.status, set())
    if new_status not in allowed:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Cannot transition a stage from '{stage.status.value}' to '{new_status.value}'.",
        )

    if new_status == StageStatus.APPROVED:
        from datetime import datetime

        stage.status = StageStatus.APPROVED
        stage.approved_at = datetime.now(UTC)
        stage.approved_by = current_user.id
        create_baseline_for_stage(db, project, stage, current_user)
        log_event(db, entity_type="project_stage", entity_id=stage.id, action="approved",
                   actor_id=current_user.id, project_id=project.id)
    else:
        stage.status = new_status
        log_event(db, entity_type="project_stage", entity_id=stage.id, action="status_changed",
                   actor_id=current_user.id, project_id=project.id, detail={"status": new_status.value})

    _notify_stage_transition(db, project, stage)
    db.commit()
    db.refresh(stage)
    return stage


@router.post("/{project_id}/stages/{stage_id}/review-deadline", response_model=ProjectStageOut)
def set_stage_review_deadline(
    project_id: UUID, stage_id: UUID, payload: StageReviewDeadlineSet,
    project: Project = Depends(require_project_manage), current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Sets (or clears) a stage's review-response deadline (C-R-05).

    Only meaningful while the stage is in REVIEW; the daily scheduler sweep
    (services/stages.py) auto-approves the stage once the deadline passes
    with no stakeholder rejection. Setting a new deadline clears any
    responses from a prior review cycle so they don't leak into this one.
    """
    stage = db.get(ProjectStage, stage_id)
    if stage is None or stage.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Stage not found.")
    if stage.status != StageStatus.REVIEW:
        raise HTTPException(status.HTTP_409_CONFLICT, "A review deadline can only be set while the stage is in review.")
    db.execute(StageReviewResponse.__table__.delete().where(StageReviewResponse.stage_id == stage.id))
    stage.review_deadline = payload.review_deadline
    log_event(db, entity_type="project_stage", entity_id=stage.id, action="review_deadline_set",
              actor_id=current_user.id, project_id=project.id,
              detail={"review_deadline": payload.review_deadline.isoformat() if payload.review_deadline else None})
    db.commit()
    db.refresh(stage)
    return stage


@router.post("/{project_id}/stages/{stage_id}/review-response", response_model=StageReviewResponseOut)
def submit_stage_review_response(
    project_id: UUID, stage_id: UUID, payload: StageReviewResponseCreate,
    current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """A stakeholder's response to a stage's review deadline (C-R-05)."""
    stage = db.get(ProjectStage, stage_id)
    if stage is None or stage.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Stage not found.")
    if stage.status != StageStatus.REVIEW or stage.review_deadline is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This stage has no open review deadline.")
    if ProjectRole.STAKEHOLDER not in get_effective_project_roles(db, current_user.id, project_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only stakeholders or managers may respond to a stage review.")

    existing = db.scalar(
        select(StageReviewResponse).where(StageReviewResponse.stage_id == stage.id, StageReviewResponse.user_id == current_user.id)
    )
    if existing is not None:
        existing.response = payload.response
        existing.comment = payload.comment
        existing.responded_at = datetime.now(UTC)
        response = existing
    else:
        response = StageReviewResponse(
            stage_id=stage.id, user_id=current_user.id, response=payload.response,
            comment=payload.comment, responded_at=datetime.now(UTC),
        )
        db.add(response)
    db.commit()
    db.refresh(response)
    return response


@router.post("/{project_id}/stages/{stage_id}/complete", response_model=ProjectStageOut)
def complete_stage_endpoint(
    project_id: UUID, stage_id: UUID, payload: StageCompleteRequest,
    project: Project = Depends(require_project_manage), current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Marks a stage completed (C-P-02), optionally cascading to its
    approved requirements (C-P-03, defaults to off per the requirement's
    clarification)."""
    stage = db.get(ProjectStage, stage_id)
    if stage is None or stage.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Stage not found.")
    complete_stage(db, project, stage, current_user, cascade_to_requirements=payload.cascade_to_requirements)
    db.commit()
    db.refresh(stage)
    return stage


_STAGE_NOTIFICATION_TYPES = {
    StageStatus.SCOPING: NotificationType.STAGE_SCOPING,
    StageStatus.REVIEW: NotificationType.STAGE_REVIEW,
    StageStatus.APPROVED: NotificationType.STAGE_APPROVED,
    StageStatus.COMPLETED: NotificationType.STAGE_COMPLETED,
}


def _notify_stage_transition(db: Session, project: Project, stage: ProjectStage) -> None:
    """Notifies all project members of stage transitions (C-N-01), including
    a newly created stage entering scoping.

    Per the requirement's "unless brand new project" clarification, a brand
    new *project's* very first stage must not notify — but that stage is
    created directly in `create_project` (never through this function), so
    every actual caller of `_notify_stage_transition` (a subsequent stage
    being created via `create_stage`, or an existing stage transitioning via
    `transition_stage`) is, by construction, never that excluded case.
    """
    notification_type = _STAGE_NOTIFICATION_TYPES.get(stage.status)
    if notification_type is None:
        return
    member_ids = get_project_member_user_ids(db, project.id)
    for user_id in member_ids:
        user = db.get(User, user_id)
        if user is not None:
            notify(
                db, user, notification_type=notification_type,
                title=f"{project.name}: {stage.name} is now {stage.status.value}",
                project_id=project.id, entity_type="project_stage", entity_id=str(stage.id),
            )


# --- Components & Categories (ordering: C-E-01, C-E-02) ---------------------


@router.post("/{project_id}/components", response_model=ComponentOut, status_code=status.HTTP_201_CREATED)
def create_component(
    payload: ComponentCreate, project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    count = len(db.scalars(select(ProjectComponent.id).where(ProjectComponent.project_id == project.id)).all())
    component = ProjectComponent(project_id=project.id, name=payload.name, prefix=payload.prefix, sort_order=count)
    db.add(component)
    db.flush()
    log_event(db, entity_type="project_component", entity_id=component.id, action="created",
              actor_id=current_user.id, project_id=project.id, organization_id=project.organization_id,
              detail={"name": component.name})
    db.commit()
    db.refresh(component)
    return component


@router.get("/{project_id}/components", response_model=list[ComponentOut])
def list_components(project_id: UUID, current_user: User = Depends(require_project_view), db: Session = Depends(get_db)):
    return db.scalars(
        select(ProjectComponent).where(ProjectComponent.project_id == project_id).order_by(ProjectComponent.sort_order)
    ).all()


@router.post("/{project_id}/components/{component_id}/move", response_model=ComponentOut)
def move_component(
    project_id: UUID, component_id: UUID, payload: MoveDirection,
    project: Project = Depends(require_project_manage), current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Moves a component up/down in display order (C-E-01)."""
    result = _move_ordered(db, ProjectComponent, [ProjectComponent.project_id == project.id], component_id, payload.direction)
    log_event(db, entity_type="project_component", entity_id=component_id, action="reordered",
              actor_id=current_user.id, project_id=project.id, organization_id=project.organization_id,
              detail={"direction": payload.direction})
    db.commit()
    return result


@router.patch("/{project_id}/components/{component_id}", response_model=ComponentOut)
def rename_component(
    project_id: UUID, component_id: UUID, payload: ComponentUpdate,
    project: Project = Depends(require_project_manage), current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Renames a component and/or changes its prefix. Existing requirements'
    `unique_code` values (e.g. `SW-PERF-014`) are generated once at creation
    and never retroactively rewritten (see `Requirement.unique_code`'s
    docstring) — a prefix change only affects codes assigned to requirements
    created after the change."""
    component = db.get(ProjectComponent, component_id)
    if component is None or component.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Component not found.")
    existing = db.scalar(
        select(ProjectComponent.id).where(
            ProjectComponent.project_id == project.id, ProjectComponent.prefix == payload.prefix,
            ProjectComponent.id != component_id,
        )
    )
    if existing is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A component with this prefix already exists.")
    component.name = payload.name
    component.prefix = payload.prefix
    log_event(db, entity_type="project_component", entity_id=component.id, action="renamed",
              actor_id=current_user.id, project_id=project.id, organization_id=project.organization_id)
    db.commit()
    db.refresh(component)
    return component


@router.delete("/{project_id}/components/{component_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_component(
    project_id: UUID, component_id: UUID,
    project: Project = Depends(require_project_manage), current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Deletes a component. Only possible once it has no categories left —
    a category is where requirements actually attach (every
    `Requirement.category_id` implies a matching `component_id`, enforced
    at creation), so emptying a component of its categories first (deleting
    or reassigning each one via `delete_category`, which can target a
    category under a *different* component) always empties it of
    requirements too, making this a simple, unconditional delete rather
    than needing its own reassignment step."""
    component = db.get(ProjectComponent, component_id)
    if component is None or component.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Component not found.")
    has_categories = db.scalar(select(ProjectCategory.id).where(ProjectCategory.component_id == component_id)) is not None
    if has_categories:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This component still has categories — delete or reassign them first."
        )
    log_event(db, entity_type="project_component", entity_id=component_id, action="deleted",
              actor_id=current_user.id, project_id=project.id, organization_id=project.organization_id)
    db.delete(component)
    db.commit()


@router.post("/{project_id}/categories", response_model=CategoryOut, status_code=status.HTTP_201_CREATED)
def create_category(
    payload: CategoryCreate, project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """Creates a category nested under `payload.component_id` (the
    component/category tree — C-G-07)."""
    component = db.get(ProjectComponent, payload.component_id)
    if component is None or component.project_id != project.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "component_id must belong to this project.")
    existing = db.scalar(
        select(ProjectCategory.id).where(
            ProjectCategory.component_id == payload.component_id, ProjectCategory.prefix == payload.prefix
        )
    )
    if existing is not None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "A category with this prefix already exists under this component."
        )
    count = len(db.scalars(select(ProjectCategory.id).where(ProjectCategory.component_id == payload.component_id)).all())
    category = ProjectCategory(
        project_id=project.id, component_id=payload.component_id, name=payload.name, prefix=payload.prefix,
        sort_order=count,
    )
    db.add(category)
    db.flush()
    log_event(db, entity_type="project_category", entity_id=category.id, action="created",
              actor_id=current_user.id, project_id=project.id, organization_id=project.organization_id,
              detail={"name": category.name})
    db.commit()
    db.refresh(category)
    return category


@router.get("/{project_id}/categories", response_model=list[CategoryOut])
def list_categories(project_id: UUID, current_user: User = Depends(require_project_view), db: Session = Depends(get_db)):
    return db.scalars(
        select(ProjectCategory).where(ProjectCategory.project_id == project_id).order_by(ProjectCategory.sort_order)
    ).all()


@router.post("/{project_id}/categories/{category_id}/move", response_model=CategoryOut)
def move_category(
    project_id: UUID, category_id: UUID, payload: MoveDirection,
    project: Project = Depends(require_project_manage), current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Moves a category up/down in display order among its siblings under
    the same parent component (C-E-02) — never reorders across components."""
    category = db.get(ProjectCategory, category_id)
    if category is None or category.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Category not found.")
    result = _move_ordered(db, ProjectCategory, [ProjectCategory.component_id == category.component_id], category_id, payload.direction)
    log_event(db, entity_type="project_category", entity_id=category_id, action="reordered",
              actor_id=current_user.id, project_id=project.id, organization_id=project.organization_id,
              detail={"direction": payload.direction})
    db.commit()
    return result


@router.patch("/{project_id}/categories/{category_id}", response_model=CategoryOut)
def rename_category(
    project_id: UUID, category_id: UUID, payload: CategoryUpdate,
    project: Project = Depends(require_project_manage), current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Renames a category and/or changes its prefix (see `rename_component`'s
    docstring on why existing `unique_code`s are unaffected)."""
    category = db.get(ProjectCategory, category_id)
    if category is None or category.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Category not found.")
    existing = db.scalar(
        select(ProjectCategory.id).where(
            ProjectCategory.component_id == category.component_id, ProjectCategory.prefix == payload.prefix,
            ProjectCategory.id != category_id,
        )
    )
    if existing is not None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "A category with this prefix already exists under this component."
        )
    category.name = payload.name
    category.prefix = payload.prefix
    log_event(db, entity_type="project_category", entity_id=category.id, action="renamed",
              actor_id=current_user.id, project_id=project.id, organization_id=project.organization_id)
    db.commit()
    db.refresh(category)
    return category


@router.delete("/{project_id}/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category(
    project_id: UUID, category_id: UUID, reassign_to: UUID,
    project: Project = Depends(require_project_manage), current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Deletes a category, reassigning every requirement that belonged to it
    to `reassign_to` — which may be a category under a *different*
    component (unlike moving a category's display position, which stays
    within one component). Crossing components on reassignment also moves
    the affected requirements' `component_id` to match, preserving the
    invariant that a requirement's component always matches its category's
    component. `reassign_to` must be a different, existing category in the
    same project — if this is the project's only remaining category, no
    valid target exists and deletion is refused.
    """
    category = db.get(ProjectCategory, category_id)
    if category is None or category.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Category not found.")
    if reassign_to == category_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "reassign_to must be a different category.")
    target = db.get(ProjectCategory, reassign_to)
    if target is None or target.project_id != project.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "reassign_to must be an existing category in this project.")
    db.execute(
        Requirement.__table__.update()
        .where(Requirement.category_id == category_id)
        .values(category_id=reassign_to, component_id=target.component_id)
    )
    log_event(db, entity_type="project_category", entity_id=category_id, action="deleted",
              actor_id=current_user.id, project_id=project.id, organization_id=project.organization_id,
              detail={"reassigned_to": str(reassign_to)})
    db.delete(category)
    db.commit()


def _move_ordered(db: Session, model, scope_conditions: list, item_id: UUID, direction: str):
    """Swaps `sort_order` between `item_id` and its neighbour (C-E-01/C-E-02).

    Shared by component and category reordering, since both are plain
    sort_order-ordered rows, just scoped differently: components are
    ordered within their project; categories are ordered within their
    parent component (siblings in the tree), not the whole project. A
    no-op (not an error) if the item is already at the boundary in the
    requested direction.

    Args:
        db: Active database session.
        model: The SQLAlchemy model class (`ProjectComponent` or
            `ProjectCategory`).
        scope_conditions: SQLAlchemy filter expressions identifying the
            sibling group `item_id` is ordered within (e.g. same
            `project_id` for components, same `component_id` for
            categories).
        item_id: The row being moved.
        direction: "up" or "down".

    Returns:
        The moved row, refreshed with its (possibly unchanged) sort_order.

    Raises:
        HTTPException: 404 if `item_id` isn't found among the scoped siblings.
    """
    items = db.scalars(select(model).where(*scope_conditions).order_by(model.sort_order)).all()
    idx = next((i for i, it in enumerate(items) if it.id == item_id), None)
    if idx is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found.")
    swap_idx = idx - 1 if direction == "up" else idx + 1
    if 0 <= swap_idx < len(items):
        items[idx].sort_order, items[swap_idx].sort_order = items[swap_idx].sort_order, items[idx].sort_order
        db.commit()
    db.refresh(items[idx])
    return items[idx]


# --- Project groups & roles (C-U-10, C-U-11) --------------------------------


def _require_user_in_org(db: Session, user_id: UUID, organization_id: UUID) -> None:
    """C-U-02: "All Project users, must be an organisation user." Raises 400
    if `user_id` holds no role at all in `organization_id`, so a project
    manager can't grant project-level access to someone outside the
    organisation.
    """
    if not get_effective_org_roles(db, user_id, organization_id):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "The user must be a member of this project's organisation first."
        )


@router.post("/{project_id}/groups", response_model=ProjectGroupOut, status_code=status.HTTP_201_CREATED)
def create_project_group(
    payload: ProjectGroupCreate,
    project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    group = ProjectGroup(project_id=project.id, name=payload.name, role=payload.role)
    db.add(group)
    db.flush()
    log_event(
        db, entity_type="project_group", entity_id=group.id, action="created", actor_id=current_user.id,
        project_id=project.id, detail={"name": group.name, "role": group.role.value},
    )
    db.commit()
    db.refresh(group)
    return ProjectGroupOut(id=group.id, name=group.name, role=group.role, is_default=group.is_default,
                            member_user_ids=[], member_org_group_ids=[])


@router.get("/{project_id}/groups", response_model=list[ProjectGroupOut])
def list_project_groups(project_id: UUID, current_user: User = Depends(require_project_view_or_manage), db: Session = Depends(get_db)):
    groups = db.scalars(select(ProjectGroup).where(ProjectGroup.project_id == project_id)).all()
    out = []
    for g in groups:
        members = db.scalars(select(ProjectGroupMember).where(ProjectGroupMember.project_group_id == g.id)).all()
        out.append(ProjectGroupOut(
            id=g.id, name=g.name, role=g.role, is_default=g.is_default,
            member_user_ids=[m.user_id for m in members if m.user_id],
            member_org_group_ids=[m.org_group_id for m in members if m.org_group_id],
        ))
    return out


def _get_group_in_project(db: Session, project_id: UUID, group_id: UUID) -> ProjectGroup:
    """Loads a project group and 404s unless it belongs to `project_id`.

    Without this check, a manager of *some* project (any project — that's
    all `require_project_manage` validates) could pass the `group_id` of a
    *different* project's "Project Managers" group and add themselves as a
    member, inheriting that project's manager role — a privilege escalation
    across the project boundary.
    """
    group = db.get(ProjectGroup, group_id)
    if group is None or group.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project group not found.")
    return group


@router.post("/{project_id}/groups/{group_id}/members", status_code=status.HTTP_204_NO_CONTENT)
def add_project_group_member(
    project_id: UUID, group_id: UUID, payload: ProjectGroupMemberAdd,
    project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not payload.user_id and not payload.org_group_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Provide user_id or org_group_id.")
    _get_group_in_project(db, project.id, group_id)
    if payload.user_id is not None:
        # C-U-02: "All Project users, must be an organisation user."
        _require_user_in_org(db, payload.user_id, project.organization_id)
    if payload.org_group_id is not None:
        # Nesting an org group from a *different* organisation would let its
        # members inherit this project's role, crossing the tenant boundary
        # (organisations are the tenant boundary per C-U-02).
        org_group = db.get(OrgGroup, payload.org_group_id)
        if org_group is None or org_group.organization_id != project.organization_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "org_group_id must belong to the project's organisation.")
    db.add(ProjectGroupMember(project_group_id=group_id, user_id=payload.user_id, org_group_id=payload.org_group_id))
    log_event(
        db, entity_type="project_group", entity_id=group_id, action="member_added", actor_id=current_user.id,
        project_id=project.id,
        detail={"user_id": str(payload.user_id) if payload.user_id else None,
                "org_group_id": str(payload.org_group_id) if payload.org_group_id else None},
    )
    if payload.user_id is not None:
        added_user = db.get(User, payload.user_id)
        if added_user is not None:
            group = db.get(ProjectGroup, group_id)
            notify(
                db, added_user, notification_type=NotificationType.PROJECT_JOINED,
                title=f"You were added to {project.name}",
                body=f"You were added to the '{group.name}' group." if group else "",
                project_id=project.id,
            )
    db.commit()


@router.delete("/{project_id}/groups/{group_id}/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_project_group_member(
    project_id: UUID, group_id: UUID, member_id: UUID,
    project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Removes a member (user or nested org group) from a project group.

    Blocks the removal if `group` is the project-manager-role group and
    `member_id` is currently the project's only manager (C-U-08), mirroring
    the same guard `revoke_project_role` applies to direct role revocation —
    a project must always retain at least one manager.
    """
    group = _get_group_in_project(db, project.id, group_id)
    if group.role == ProjectRole.PROJECT_MANAGER:
        lock_project_for_update(db, project.id)
        managers = get_project_managers(db, project.id)
        if managers == {member_id}:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "A project must have at least one project manager.")
    db.execute(
        ProjectGroupMember.__table__.delete().where(
            ProjectGroupMember.project_group_id == group_id,
            (ProjectGroupMember.user_id == member_id) | (ProjectGroupMember.org_group_id == member_id),
        )
    )
    log_event(
        db, entity_type="project_group", entity_id=group_id, action="member_removed", actor_id=current_user.id,
        project_id=project.id, detail={"member_id": str(member_id)},
    )
    # A group can grant a role alongside other direct/group roles a user
    # holds on the same project, so only clean up subscriptions/favourites
    # if this removal actually left them with no remaining access — not on
    # every membership change.
    if member_id and not get_effective_project_roles(db, member_id, project.id):
        engagement.remove_subscriptions_and_favorites_for_projects(db, member_id, [project.id])
    db.commit()


@router.post("/{project_id}/roles", status_code=status.HTTP_204_NO_CONTENT)
def assign_project_role(
    project_id: UUID, payload: UserProjectRoleAssign,
    project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Assigns a direct (non-group) project role to a user."""
    _require_user_in_org(db, payload.user_id, project.organization_id)  # C-U-02
    existing = db.scalar(
        select(UserProjectRole).where(
            UserProjectRole.user_id == payload.user_id, UserProjectRole.project_id == project.id,
            UserProjectRole.role == payload.role,
        )
    )
    if existing is None:
        db.add(UserProjectRole(user_id=payload.user_id, project_id=project.id, role=payload.role))
        log_event(
            db, entity_type="user_project_role", entity_id=payload.user_id, action="granted",
            actor_id=current_user.id, project_id=project.id, detail={"role": payload.role.value},
        )
        granted_user = db.get(User, payload.user_id)
        if granted_user is not None:
            notify(
                db, granted_user, notification_type=NotificationType.PROJECT_JOINED,
                title=f"You were added to {project.name}",
                body=f"You were granted the '{payload.role.value}' role.",
                project_id=project.id,
            )
        db.commit()


@router.post("/{project_id}/roles/by-email", response_model=AssignByEmailOut)
def assign_project_role_by_email(
    project_id: UUID, payload: UserProjectRoleAssignByEmail,
    project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The by-email counterpart to `assign_project_role`, for a user who
    isn't (yet) a member of this project's organisation — the project-user
    picker's "add external user" action (`orgs.py::search_org_users`
    surfaces the candidate; this endpoint re-validates and acts on it,
    never trusting the frontend's search-result flags).

    Gated by `Organization.external_user_policy`:
      - DISABLED: always 403, whether or not an account already exists.
      - ORG_DOMAIN_ONLY: an *existing* account can always be added; a
        *new* account can only be invited if the email's domain matches
        `auto_accept_email_domain`.
      - ANYONE: both existing and brand-new accounts are allowed.

    For a brand-new account, branches on `Organization.sso_only` (see
    `services/invites.py`): an SSO-only org gets the account and roles
    provisioned immediately (`outcome="sso_provisioned"`); otherwise an
    email invite with a signup link is sent (`outcome="invited"`) and the
    role is granted once they complete signup.
    """
    email = payload.email.lower()
    org = db.get(Organization, project.organization_id)
    existing_user = db.scalar(select(User).where(User.email == email))

    if existing_user is not None:
        already_in_org = bool(get_effective_org_roles(db, existing_user.id, org.id))
        if not already_in_org:
            if org.external_user_policy == ExternalUserPolicy.DISABLED:
                raise HTTPException(status.HTTP_403_FORBIDDEN, "This organisation does not allow external users.")
            if existing_user.is_banned:
                # Same check assign_org_role already enforces for the
                # ordinary org-role-grant path (routers/orgs.py) — this
                # endpoint grants org membership too (as a side effect of
                # adding a project member by email) and must not become a
                # second, unguarded way back in for a banned account.
                raise HTTPException(
                    status.HTTP_403_FORBIDDEN,
                    "This user has been banned by a server admin and cannot be granted a role.",
                )
            db.add(UserOrgRole(user_id=existing_user.id, organization_id=org.id, role=OrgRole.MEMBER))
            log_event(
                db, entity_type="user", entity_id=existing_user.id, action="external_user_added_to_org",
                actor_id=current_user.id, organization_id=org.id,
            )
        existing_role = db.scalar(
            select(UserProjectRole).where(
                UserProjectRole.user_id == existing_user.id, UserProjectRole.project_id == project.id,
                UserProjectRole.role == payload.role,
            )
        )
        if existing_role is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, "This user already has this role on the project.")
        db.add(UserProjectRole(user_id=existing_user.id, project_id=project.id, role=payload.role))
        log_event(
            db, entity_type="user_project_role", entity_id=existing_user.id, action="granted",
            actor_id=current_user.id, project_id=project.id, detail={"role": payload.role.value, "via": "email"},
        )
        notify(
            db, existing_user, notification_type=NotificationType.PROJECT_JOINED,
            title=f"You were added to {project.name}",
            body=f"You were granted the '{payload.role.value}' role.",
            project_id=project.id,
        )
        db.commit()
        return AssignByEmailOut(outcome="added")

    # No account exists anywhere yet.
    if org.external_user_policy == ExternalUserPolicy.DISABLED:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This organisation does not allow external users.")
    if org.external_user_policy == ExternalUserPolicy.ORG_DOMAIN_ONLY:
        domain = email.rsplit("@", 1)[-1]
        if not org.auto_accept_email_domain or org.auto_accept_email_domain.lower() != domain:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "This email's domain is not eligible for an invite in this organisation."
            )

    if org.sso_only:
        invites.provision_sso_invite(
            db, email=email, organization=org, project=project, project_role=payload.role,
            invited_by=current_user.id,
        )
        db.commit()
        return AssignByEmailOut(outcome="sso_provisioned")

    invites.create_pending_invite(
        db, email=email, organization=org, project=project, project_role=payload.role, invited_by=current_user.id,
    )
    db.commit()
    return AssignByEmailOut(outcome="invited")


@router.delete("/{project_id}/roles/{user_id}/{role}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_project_role(
    project_id: UUID, user_id: UUID, role: ProjectRole,
    project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Revokes a direct project role, blocking removal of the last manager (C-U-08)."""
    if role == ProjectRole.PROJECT_MANAGER:
        lock_project_for_update(db, project.id)
        managers = get_project_managers(db, project.id)
        if managers == {user_id}:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "A project must have at least one project manager.")
    db.execute(
        UserProjectRole.__table__.delete().where(
            UserProjectRole.user_id == user_id, UserProjectRole.project_id == project.id,
            UserProjectRole.role == role,
        )
    )
    log_event(
        db, entity_type="user_project_role", entity_id=user_id, action="revoked",
        actor_id=current_user.id, project_id=project.id, detail={"role": role.value},
    )
    revoked_user = db.get(User, user_id)
    if revoked_user is not None:
        notify(
            db, revoked_user, notification_type=NotificationType.PERMISSION_REVOKED,
            title=f"Your '{role.value}' role on {project.name} was revoked", project_id=project.id,
        )
    # Only clean up subscriptions/favourites if the user has no other role
    # (direct or group-derived) left granting them access to this project.
    if not get_effective_project_roles(db, user_id, project.id):
        engagement.remove_subscriptions_and_favorites_for_projects(db, user_id, [project.id])
    db.commit()
