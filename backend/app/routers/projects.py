"""
Module: routers.projects

Project CRUD, stages (with approval -> baseline), components/categories
(with ordering, C-E-01/C-E-02), project groups and role assignment
(C-U-10, C-U-11), and the project overview metrics endpoint (U-P-05).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models.change_request import ChangeRequest
from app.models.enums import ChangeRequestStatus, OrgRole, ProjectRole, RequirementStatus, StageStatus
from app.models.notification import NotificationType
from app.models.organization import OrgGroup, UserOrgRole
from app.models.project import (
    FavoriteProject,
    Project,
    ProjectCategory,
    ProjectComponent,
    ProjectGroup,
    ProjectGroupMember,
    ProjectStage,
    UserProjectRole,
)
from app.models.requirement import Requirement, RequirementVersion
from app.models.user import User
from app.schemas.changes import ChangeEntryOut
from app.schemas.project import (
    CategoryCreate,
    CategoryOut,
    ComponentCreate,
    ComponentOut,
    MoveDirection,
    ProjectCreate,
    ProjectGroupCreate,
    ProjectGroupMemberAdd,
    ProjectGroupOut,
    ProjectListItemOut,
    ProjectMetricsOut,
    ProjectOut,
    ProjectStageCreate,
    ProjectStageOut,
    ProjectUpdate,
    TerminologyUpdate,
    UserProjectRoleAssign,
)
from app.services.audit import log_event
from app.services.baseline import create_baseline_for_stage, project_is_locked
from app.services.changes import get_project_changes
from app.services.notifications import notify
from app.services.rbac import (
    can_manage_project_settings,
    get_effective_org_roles,
    get_effective_project_roles,
    get_project_managers,
    get_project_member_user_ids,
    require_project_manage,
    require_project_view,
)
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
    """
    org_roles = get_effective_org_roles(db, current_user.id, payload.organization_id)
    if not current_user.is_server_admin and not org_roles & {OrgRole.ORG_ADMIN, OrgRole.PROJECT_CREATOR}:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only org admins or project creators may create projects.")

    if payload.template_project_id is not None:
        template = db.get(Project, payload.template_project_id)
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

    log_event(
        db, entity_type="project", entity_id=project.id, action="created", actor_id=current_user.id,
        organization_id=payload.organization_id, project_id=project.id,
        detail={"template_project_id": str(payload.template_project_id)} if payload.template_project_id else None,
    )
    db.commit()
    db.refresh(project)
    return project


@router.get("", response_model=list[ProjectListItemOut])
def list_projects(
    archived: bool = False,
    search: str | None = None,
    role: ProjectRole | None = None,
    stage_status: StageStatus | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Project list view (U-E-03, U-E-04): active/archived projects the user can access.

    Supports an optional `role` filter (only projects where the caller holds
    the given effective project role) and `stage_status` filter (only
    projects whose current stage is in the given status) for U-E-05.
    Results are sorted with the caller's favourited projects (U-U-03) first,
    then by name.
    """
    if current_user.is_server_admin:
        projects = db.scalars(select(Project).where(Project.is_archived == archived)).all()
    else:
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
            projects = db.scalars(
                select(Project).where(Project.id.in_(accessible_ids), Project.is_archived == archived)
            ).all()

    if search:
        needle = search.lower()
        projects = [p for p in projects if needle in p.name.lower() or needle in p.summary.lower()]

    favorite_ids = set(
        db.scalars(select(FavoriteProject.project_id).where(FavoriteProject.user_id == current_user.id)).all()
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
            )
        )
    out.sort(key=lambda item: (not item.is_favorite, item.name.lower()))
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


@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: UUID, payload: ProjectUpdate,
    project: Project = Depends(require_project_manage), db: Session = Depends(get_db),
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
    db.commit()
    db.refresh(project)
    return project


@router.put("/{project_id}/terminology", response_model=ProjectOut)
def update_terminology(
    project_id: UUID, payload: TerminologyUpdate,
    project: Project = Depends(require_project_manage), db: Session = Depends(get_db),
):
    """Sets per-project terminology overrides (C-C-03), e.g. {"stage": "Horizon"}."""
    project.terminology = payload.terminology
    db.commit()
    db.refresh(project)
    return project


@router.post("/{project_id}/archive", response_model=ProjectOut)
def archive_project(
    project_id: UUID, project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Archives a project: hidden from the active project list, data preserved (C-P-01)."""
    from datetime import datetime, timezone

    project.is_archived = True
    project.archived_at = datetime.now(timezone.utc)
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
    current_user: User = Depends(require_project_view),
    db: Session = Depends(get_db),
):
    """Project changes-over-time view (C-A-10): a unified timeline of
    requirement/change-request/audit events, with an optional time range
    filter. Discussion comments are excluded unless `include_comments=true`."""
    return get_project_changes(db, project_id, since=since, until=until, include_comments=include_comments)


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
    return ProjectMetricsOut(
        requirement_count=requirement_count,
        requirement_completed_percent=round(percent, 1),
        change_requests_proposed=proposed,
        change_requests_approved=approved,
        change_requests_rejected=rejected,
    )


# --- Stages -----------------------------------------------------------------


@router.post("/{project_id}/stages", response_model=ProjectStageOut, status_code=status.HTTP_201_CREATED)
def create_stage(
    payload: ProjectStageCreate, project: Project = Depends(require_project_manage), db: Session = Depends(get_db)
):
    """Adds a new project stage (C-G-08)."""
    count = len(db.scalars(select(ProjectStage.id).where(ProjectStage.project_id == project.id)).all())
    stage = ProjectStage(project_id=project.id, name=payload.name, status=StageStatus.SCOPING, sort_order=count)
    db.add(stage)
    db.flush()
    log_event(db, entity_type="project_stage", entity_id=stage.id, action="created",
              actor_id=None, project_id=project.id)
    db.commit()
    db.refresh(stage)
    return stage


@router.get("/{project_id}/stages", response_model=list[ProjectStageOut])
def list_stages(project_id: UUID, current_user: User = Depends(require_project_view), db: Session = Depends(get_db)):
    return db.scalars(
        select(ProjectStage).where(ProjectStage.project_id == project_id).order_by(ProjectStage.sort_order)
    ).all()


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
    """
    stage = db.get(ProjectStage, stage_id)
    if stage is None or stage.project_id != project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Stage not found.")

    if new_status == StageStatus.APPROVED:
        if not current_user.is_server_admin and ProjectRole.PROJECT_MANAGER not in get_effective_project_roles(
            db, current_user.id, project.id
        ):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a project manager can approve a stage.")
        from datetime import datetime, timezone

        stage.status = StageStatus.APPROVED
        stage.approved_at = datetime.now(timezone.utc)
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


_STAGE_NOTIFICATION_TYPES = {
    StageStatus.REVIEW: NotificationType.STAGE_REVIEW,
    StageStatus.APPROVED: NotificationType.STAGE_APPROVED,
    StageStatus.COMPLETED: NotificationType.STAGE_COMPLETED,
}


def _notify_stage_transition(db: Session, project: Project, stage: ProjectStage) -> None:
    """Notifies all project members of stage transitions (C-N-01).

    Scoping transitions are intentionally excluded per the requirement's
    "unless brand new project" clarification — every project's initial
    stage starts in scoping, so notifying on that specific transition would
    just be noise on every project creation.
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
    payload: ComponentCreate, project: Project = Depends(require_project_manage), db: Session = Depends(get_db)
):
    count = len(db.scalars(select(ProjectComponent.id).where(ProjectComponent.project_id == project.id)).all())
    component = ProjectComponent(project_id=project.id, name=payload.name, prefix=payload.prefix, sort_order=count)
    db.add(component)
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
    project: Project = Depends(require_project_manage), db: Session = Depends(get_db)
):
    """Moves a component up/down in display order (C-E-01)."""
    return _move_ordered(db, ProjectComponent, project.id, component_id, payload.direction)


@router.post("/{project_id}/categories", response_model=CategoryOut, status_code=status.HTTP_201_CREATED)
def create_category(
    payload: CategoryCreate, project: Project = Depends(require_project_manage), db: Session = Depends(get_db)
):
    count = len(db.scalars(select(ProjectCategory.id).where(ProjectCategory.project_id == project.id)).all())
    category = ProjectCategory(project_id=project.id, name=payload.name, prefix=payload.prefix, sort_order=count)
    db.add(category)
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
    project: Project = Depends(require_project_manage), db: Session = Depends(get_db)
):
    """Moves a category up/down in display order (C-E-02)."""
    return _move_ordered(db, ProjectCategory, project.id, category_id, payload.direction)


def _move_ordered(db: Session, model, project_id: UUID, item_id: UUID, direction: str):
    items = db.scalars(select(model).where(model.project_id == project_id).order_by(model.sort_order)).all()
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


@router.post("/{project_id}/groups", response_model=ProjectGroupOut, status_code=status.HTTP_201_CREATED)
def create_project_group(
    payload: ProjectGroupCreate, project: Project = Depends(require_project_manage), db: Session = Depends(get_db)
):
    group = ProjectGroup(project_id=project.id, name=payload.name, role=payload.role)
    db.add(group)
    db.commit()
    db.refresh(group)
    return ProjectGroupOut(id=group.id, name=group.name, role=group.role, is_default=group.is_default,
                            member_user_ids=[], member_org_group_ids=[])


@router.get("/{project_id}/groups", response_model=list[ProjectGroupOut])
def list_project_groups(project_id: UUID, current_user: User = Depends(require_project_view), db: Session = Depends(get_db)):
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
    project: Project = Depends(require_project_manage), db: Session = Depends(get_db)
):
    if not payload.user_id and not payload.org_group_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Provide user_id or org_group_id.")
    _get_group_in_project(db, project.id, group_id)
    if payload.org_group_id is not None:
        # Nesting an org group from a *different* organisation would let its
        # members inherit this project's role, crossing the tenant boundary
        # (organisations are the tenant boundary per C-U-02).
        org_group = db.get(OrgGroup, payload.org_group_id)
        if org_group is None or org_group.organization_id != project.organization_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "org_group_id must belong to the project's organisation.")
    db.add(ProjectGroupMember(project_group_id=group_id, user_id=payload.user_id, org_group_id=payload.org_group_id))
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
    project: Project = Depends(require_project_manage), db: Session = Depends(get_db)
):
    _get_group_in_project(db, project.id, group_id)
    db.execute(
        ProjectGroupMember.__table__.delete().where(
            ProjectGroupMember.project_group_id == group_id,
            (ProjectGroupMember.user_id == member_id) | (ProjectGroupMember.org_group_id == member_id),
        )
    )
    db.commit()


@router.post("/{project_id}/roles", status_code=status.HTTP_204_NO_CONTENT)
def assign_project_role(
    project_id: UUID, payload: UserProjectRoleAssign,
    project: Project = Depends(require_project_manage), db: Session = Depends(get_db)
):
    """Assigns a direct (non-group) project role to a user."""
    existing = db.scalar(
        select(UserProjectRole).where(
            UserProjectRole.user_id == payload.user_id, UserProjectRole.project_id == project.id,
            UserProjectRole.role == payload.role,
        )
    )
    if existing is None:
        db.add(UserProjectRole(user_id=payload.user_id, project_id=project.id, role=payload.role))
        granted_user = db.get(User, payload.user_id)
        if granted_user is not None:
            notify(
                db, granted_user, notification_type=NotificationType.PROJECT_JOINED,
                title=f"You were added to {project.name}",
                body=f"You were granted the '{payload.role.value}' role.",
                project_id=project.id,
            )
        db.commit()


@router.delete("/{project_id}/roles/{user_id}/{role}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_project_role(
    project_id: UUID, user_id: UUID, role: ProjectRole,
    project: Project = Depends(require_project_manage), db: Session = Depends(get_db)
):
    """Revokes a direct project role, blocking removal of the last manager (C-U-08)."""
    if role == ProjectRole.PROJECT_MANAGER:
        from app.services.rbac import get_project_managers

        managers = get_project_managers(db, project.id)
        if managers == {user_id}:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "A project must have at least one project manager.")
    db.execute(
        UserProjectRole.__table__.delete().where(
            UserProjectRole.user_id == user_id, UserProjectRole.project_id == project.id,
            UserProjectRole.role == role,
        )
    )
    revoked_user = db.get(User, user_id)
    if revoked_user is not None:
        notify(
            db, revoked_user, notification_type=NotificationType.PERMISSION_REVOKED,
            title=f"Your '{role.value}' role on {project.name} was revoked", project_id=project.id,
        )
    db.commit()
