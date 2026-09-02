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
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, aliased

from app.database import get_db
from app.deps import get_current_user
from app.models.change_request import ChangeRequest, ChangeRequestVersion, ReviewComment
from app.models.enums import (
    ChangeRequestStatus,
    ExternalUserPolicy,
    OrgRole,
    ProjectRole,
    ProjectRoleInheritanceMode,
    ProjectVisibility,
    ReviewTargetType,
    StageStatus,
)
from app.models.file import CommentFile, FileAsset, RequirementActionFile, RequirementFile
from app.models.notification import NotificationType
from app.models.organization import Organization, OrgGroup, OrgGroupMember, PendingInvite, ReportTemplate, UserOrgRole
from app.models.project import (
    FavoriteProject,
    OrgGroupProjectRole,
    Project,
    ProjectCategory,
    ProjectComponent,
    ProjectGroup,
    ProjectGroupMember,
    ProjectGroupRole,
    ProjectMemberSource,
    ProjectStage,
    StageReviewResponse,
    UserProjectRole,
)
from app.models.project_status import ProjectStatusDefinition
from app.models.requirement import Baseline, BaselineItem, Requirement, RequirementVersion
from app.models.requirement_action import RequirementAction
from app.models.user import User
from app.schemas.changes import ChangeEntryOut
from app.schemas.file import FileAssetOut, ProjectFileOut
from app.schemas.project import (
    AssignByEmailOut,
    CategoryCreate,
    CategoryOut,
    CategoryUpdate,
    ComponentCreate,
    ComponentOut,
    ComponentUpdate,
    EffectiveMemberOut,
    MaterializeResultOut,
    MoveDirection,
    OrgGroupProjectRoleAssign,
    PendingInviteOut,
    ProjectAncestorOut,
    ProjectCreate,
    ProjectGroupCreate,
    ProjectGroupMemberAdd,
    ProjectGroupOut,
    ProjectGroupRoleAssign,
    ProjectImportResult,
    ProjectListItemOut,
    ProjectMemberSourceAdd,
    ProjectMemberSourceOut,
    ProjectMetricsOut,
    ProjectOut,
    ProjectStageCreate,
    ProjectStageOut,
    ProjectStageUpdate,
    ProjectTreeNodeOut,
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
from app.services.definitions import get_default_project_status_id, seed_action_types
from app.services.downloads import filename_safe
from app.services.notifications import notify
from app.services.ordering import move_ordered
from app.services.project_export import build_project_bundle, import_project_bundle
from app.services.project_hierarchy import build_project_tree, get_ancestor_chain, would_create_project_cycle
from app.services.rbac import (
    _descendant_org_group_ids,
    _direct_project_member_ids_base,
    can_manage_project_settings,
    check_pat_scope,
    get_effective_org_roles,
    get_effective_project_managers,
    get_effective_project_members_with_provenance,
    get_effective_project_roles,
    get_group_inherited_project_roles,
    get_project_member_user_ids,
    get_user_org_group_ids,
    is_inherited_manager,
    is_org_admin,
    lock_project_for_update,
    require_project_manage,
    require_project_view,
    require_project_view_or_manage,
)
from app.services.reports import resolve_report_config
from app.services.stages import complete_stage
from app.services.templates import clone_project

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])

_ACCESSIBLE_EXPANSION_ITERATION_CAP = 50


def _accessible_project_ids(db: Session, user_id: UUID) -> set[UUID]:
    """Every project id the user has *some* effective role on — direct,
    group, org-wide visibility, plus (hierarchical projects) any project
    reachable *only* through forward or member-source inheritance from one
    of those.

    Without the inheritance expansion below, a user with access to a child
    purely via `role_inheritance_mode` (no direct/group/org-wide role of
    their own on the child) would never see it in `list_projects`/the tree/
    ancestors/children endpoints at all — the whole point of the feature
    would be invisible to exactly the users it's for. The expansion walks
    structural neighbours of already-accessible projects iteratively, since
    a multi-hop chain can make a project only reachable after an earlier
    hop's own expansion — three kinds of neighbour: children (source 5),
    projects whose member-source list names an accessible project as a
    source (source 6, same-organisation only since the mechanism was
    generalized beyond strict parent/child), and projects with a group
    whose members are defined as an accessible project's roster (source 7,
    same-organisation only) — but verifies each candidate's *actual*
    effective role (`get_effective_project_roles`) before including it,
    rather than trusting structural adjacency alone: a `MIRROR_ROLE`-
    filtered child, for instance, is only actually reachable by users
    holding the filtered role on the parent, not every accessible-parent
    user.
    """
    project_ids_via_role = set(
        db.scalars(select(UserProjectRole.project_id).where(UserProjectRole.user_id == user_id)).all()
    )
    # PR7 (members/groups directory rework plan, docs/decisions.md): a group
    # can now hold zero roles, so plain membership alone no longer implies
    # any access — the `join(ProjectGroupRole, ...)` below requires the
    # group to actually hold at least one role, matching `get_effective_
    # project_roles`'s own authoritative check (`rbac._direct_effective_
    # project_roles_by_kind`'s `direct_group` branch already requires this).
    # Found and fixed together with the identical pre-existing gap in
    # `rbac._direct_project_member_ids_base` — see that function's own
    # docstring for the regression this closes.
    project_ids_via_group = set(
        db.scalars(
            select(ProjectGroup.project_id)
            .join(ProjectGroupMember, ProjectGroupMember.project_group_id == ProjectGroup.id)
            .join(ProjectGroupRole, ProjectGroupRole.project_group_id == ProjectGroup.id)
            .where(ProjectGroupMember.user_id == user_id)
        ).all()
    )
    user_org_ids = set(db.scalars(select(UserOrgRole.organization_id).where(UserOrgRole.user_id == user_id)).all())
    project_ids_via_org_wide = (
        set(
            db.scalars(
                select(Project.id).where(
                    Project.visibility == ProjectVisibility.ORG_WIDE, Project.organization_id.in_(user_org_ids)
                )
            ).all()
        )
        if user_org_ids
        else set()
    )
    # Pre-existing gap fixed here, found while regression-testing PR4 (see
    # docs/decisions.md): the two sets above only ever covered a user's
    # *direct* membership (a UserProjectRole, or being a plain user_id
    # member of a ProjectGroup) — never a role reached only via an org group
    # the user belongs to, whether nested inside a ProjectGroup
    # (`ProjectGroupMember.org_group_id`, pre-existing) or granted a role
    # directly (`OrgGroupProjectRole`, PR4's new mechanism). Both are
    # already correctly resolved by `get_effective_project_roles`/`require_
    # project_view`, so `GET /{project_id}` has always worked for such a
    # user — but `_accessible_project_ids` is the separate function behind
    # `list_projects`/`/ancestors`/`/children`, so that same user's project
    # simply never appeared in their own project list or search. Uses the
    # same `get_user_org_group_ids` (direct + transitively-nested) already
    # used elsewhere for this exact resolution, once per organisation the
    # user belongs to.
    all_user_org_group_ids: set[UUID] = set()
    for member_org_id in user_org_ids:
        direct_group_ids, inherited_group_ids = get_user_org_group_ids(db, user_id, member_org_id)
        all_user_org_group_ids |= direct_group_ids | inherited_group_ids
    project_ids_via_nested_org_group = (
        set(
            db.scalars(
                select(ProjectGroup.project_id)
                .join(ProjectGroupMember, ProjectGroupMember.project_group_id == ProjectGroup.id)
                .where(ProjectGroupMember.org_group_id.in_(all_user_org_group_ids))
            ).all()
        )
        if all_user_org_group_ids
        else set()
    )
    project_ids_via_direct_group_role = (
        set(
            db.scalars(
                select(OrgGroupProjectRole.project_id).where(
                    OrgGroupProjectRole.org_group_id.in_(all_user_org_group_ids)
                )
            ).all()
        )
        if all_user_org_group_ids
        else set()
    )
    accessible_ids = (
        project_ids_via_role
        | project_ids_via_group
        | project_ids_via_org_wide
        | project_ids_via_nested_org_group
        | project_ids_via_direct_group_role
    )

    frontier = set(accessible_ids)
    iterations = 0
    while frontier and iterations < _ACCESSIBLE_EXPANSION_ITERATION_CAP:
        iterations += 1
        candidate_children = set(
            db.scalars(
                select(Project.id).where(
                    Project.parent_project_id.in_(frontier),
                    Project.role_inheritance_mode != ProjectRoleInheritanceMode.NONE,
                )
            ).all()
        )
        OwnerProject = aliased(Project)
        candidate_via_member_source = set(
            db.scalars(
                select(ProjectMemberSource.project_id)
                .join(Project, Project.id == ProjectMemberSource.source_project_id)
                .join(OwnerProject, OwnerProject.id == ProjectMemberSource.project_id)
                .where(
                    ProjectMemberSource.source_project_id.in_(frontier),
                    Project.organization_id == OwnerProject.organization_id,
                )
            ).all()
        )
        GroupOwnerProject = aliased(Project)
        candidate_via_project_ref_group = set(
            db.scalars(
                select(ProjectGroup.project_id)
                .join(ProjectGroupMember, ProjectGroupMember.project_group_id == ProjectGroup.id)
                .join(GroupOwnerProject, GroupOwnerProject.id == ProjectGroup.project_id)
                .join(Project, Project.id == ProjectGroupMember.source_project_id)
                .where(
                    ProjectGroupMember.source_project_id.in_(frontier),
                    Project.organization_id == GroupOwnerProject.organization_id,
                )
            ).all()
        )
        new_frontier: set[UUID] = set()
        for candidate_id in (
            candidate_children | candidate_via_member_source | candidate_via_project_ref_group
        ) - accessible_ids:
            if get_effective_project_roles(db, user_id, candidate_id):
                accessible_ids.add(candidate_id)
                new_frontier.add(candidate_id)
        frontier = new_frontier

    return accessible_ids


def _project_out_with_redacted_parent(db: Session, current_user: User, project: Project) -> ProjectOut:
    """Builds a `ProjectOut` with `parent_project_id`/`parent_project_name`
    redacted unless the caller has effective view access to the parent, or
    manages `project` itself — the same visibility-boundary rule
    `list_projects` already applies to `ProjectListItemOut`, extended here
    to every endpoint that returns a single `Project` directly (`GET/PATCH/
    POST .../archive/.../unarchive/.../terminology`). Without the general
    redaction, `GET /{project_id}` — gated by `require_project_view`, not
    manage — would let *any* project viewer learn a hidden parent's
    identity just by fetching the project directly, even though
    `list_projects`/`/ancestors` correctly redact it.

    The manager exemption closes a real gap found in this branch's own
    hardening pass: `ProjectAdminPage.tsx`'s settings form (frontend) has
    always assumed — per its own inline comment and docs/decisions.md's
    "Hierarchical projects" entry ("a project's own manager already holds
    the highest level of authority over this relationship and needs to see
    it to do their job") — that a project's manager sees the true parent
    here, never a redacted one. Before this fix that assumption was false:
    a manager with no independent view access to the parent (a realistic,
    common case — nothing ties managing a child to having any role on its
    parent) saw `parent_project_id: null`, the same as any other viewer.
    Combined with `saveSettings()` unconditionally resending
    `parent_project_id` on every save (not just when the field was
    actually touched), this silently detached the project from its real
    parent on the next unrelated settings save — a genuine, unannounced
    structural mutation the manager never intended. A project's own
    manager already has unilateral authority to detach or reparent this
    exact relationship via this same endpoint, so showing them the true
    value they already have the power to change is not a new disclosure.
    """
    out = ProjectOut.model_validate(project)
    if project.parent_project_id is None:
        return out
    if can_manage_project_settings(db, current_user, project) or project.parent_project_id in _accessible_project_ids(
        db, current_user.id
    ):
        parent = db.get(Project, project.parent_project_id)
        out.parent_project_name = parent.name if parent is not None else None
        return out
    out.parent_project_id = None
    return out


def _ensure_project_has_a_manager(db: Session, project: Project, fallback_user_id: UUID) -> None:
    """C-U-08 fallback: guarantees `project` has at least one effective
    manager, granting `fallback_user_id` one if it doesn't.

    Shared by both of `create_project`'s branches (follow-up UX batch Phase
    C, 2026-08-31 — previously only the template-clone branch needed this
    at all, since the non-template branch always auto-created its own
    manager-role `ProjectGroup` and added the creator to it directly).
    Prefers adding `fallback_user_id` to an existing manager-role
    `ProjectGroup` on `project` if one exists (only possible here via a
    template clone that copied a user-created manager-role group — a
    from-scratch project has zero groups at the point this is called, so
    that branch is structurally unreachable there and this always falls
    through to the direct grant); otherwise grants a direct
    `PROJECT_MANAGER` `UserProjectRole`, mirroring the guarantee
    `import_project_bundle` (`services.project_export`) gives its own
    importer for the same reason.
    """
    if get_effective_project_managers(db, project.id):
        return
    fallback_group = db.scalar(
        select(ProjectGroup)
        .join(ProjectGroupRole, ProjectGroupRole.project_group_id == ProjectGroup.id)
        .where(ProjectGroup.project_id == project.id, ProjectGroupRole.role == ProjectRole.PROJECT_MANAGER)
    )
    if fallback_group is not None:
        db.add(ProjectGroupMember(project_group_id=fallback_group.id, user_id=fallback_user_id))
    else:
        db.add(UserProjectRole(user_id=fallback_user_id, project_id=project.id, role=ProjectRole.PROJECT_MANAGER))


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
def create_project(
    payload: ProjectCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Creates a project within an organisation.

    Two authorization paths (hierarchical-projects decision 11 in
    docs/decisions.md):
      1. Org-level (C-U-01: project_creator/org_admin) — today's original
         behaviour, unchanged. Works with or without `parent_project_id`.
      2. Relaxed, parent-scoped — the caller lacks an org-level role but
         `parent_project_id` is set, they manage that exact parent
         (`can_manage_project_settings`), and the organisation hasn't
         turned this path off (`Organization.allow_relaxed_child_project_
         creation`, default on). This is what makes "Add sub-project" from
         a project's own page usable by an ordinary project manager. The
         resulting project is marked `parent_required=True` — see
         `Project.parent_required`'s docstring for why, and
         `update_project` below for the one behavioural consequence.
    Either path: if `parent_project_id` is set, the caller must also manage
    the target parent (not just view it) — attaching to a parent is
    authorized by *both* sides, unlike detaching (see decision 12).

    On creation, the creator is granted a direct `PROJECT_MANAGER`
    `UserProjectRole` (C-U-10) — unless a template project is used (C-E-05),
    per C-U-10's explicit "unless using a template project" clause:
    groups/members (and, as of the follow-up UX batch's Phase C, direct role
    grants too) are copied from the template instead, via `clone_project`.
    If that leaves the new project with no manager at all, the creator is
    still added as a fallback (the exact same
    `get_effective_project_managers`-then-fallback-`UserProjectRole` code
    path both branches below now share) so C-U-08 (every project must have
    a manager) can never be violated. This is unconditional regardless of
    `parent_project_id`/`role_inheritance_mode` — a newly created project
    always gets its own direct, individually accountable manager, so
    creation-time C-U-08 never depends on inheritance being present or
    stable later.

    Prior to the follow-up UX batch's Phase C (2026-08-31), the non-template
    path instead auto-created four "standard" `ProjectGroup` rows
    (`is_default=True`) and added the creator to the manager-role one —
    see docs/decisions.md's entry on that migration for why this changed
    (in short: those four groups could never be deleted, existed on every
    project whether wanted or not, and made group membership the only path
    to a first manager even though direct grants were always the simpler,
    equally-supported mechanism for a single person).

    `organization_id` lives in the request body here (the project doesn't
    exist yet to have a path segment of its own), so — unlike every other
    org/project-scoped endpoint — it isn't covered by `require_org_role`'s
    or `require_project_*`'s built-in PAT-scope check; enforced explicitly
    here instead.
    """
    check_pat_scope(request, payload.organization_id)
    org = db.get(Organization, payload.organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")

    org_roles = get_effective_org_roles(db, current_user.id, payload.organization_id)
    has_org_level_create_rights = bool(org_roles & {OrgRole.ORG_ADMIN, OrgRole.PROJECT_CREATOR})

    parent_project: Project | None = None
    if payload.parent_project_id is not None:
        parent_project = db.get(Project, payload.parent_project_id)
        if parent_project is None or parent_project.organization_id != payload.organization_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "parent_project_id must be a project in this organisation.")
        if not can_manage_project_settings(db, current_user, parent_project):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You must manage the parent project to create a child under it.")
        if not parent_project.can_be_parent:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "This project has not been made eligible to be a parent — enable "
                "\"Allow this project to be a parent\" on it first.",
            )

    parent_required = False
    if not has_org_level_create_rights:
        if parent_project is None or not org.allow_relaxed_child_project_creation:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only org admins or project creators may create projects.")
        parent_required = True

    template_project_id = payload.template_project_id
    if template_project_id is None:
        # C-E-04: fall back to the organisation's configured default template
        # when the caller didn't specify one. The frontend's "New project"
        # form pre-selects this same default in its template dropdown so a
        # user can still explicitly override it before submitting.
        template_project_id = org.default_template_project_id

    if template_project_id is not None:
        template = db.get(Project, template_project_id)
        if (
            template is None
            or template.organization_id != payload.organization_id
            or not template.is_template
        ):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "template_project_id must be a template project in this organisation.")
        project = clone_project(
            db, template, name=payload.name, summary=payload.summary, creator=current_user,
            parent_project_id=payload.parent_project_id,
        )
        db.flush()
        _ensure_project_has_a_manager(db, project, current_user.id)
    else:
        project = Project(
            organization_id=payload.organization_id, name=payload.name, summary=payload.summary,
            status_id=get_default_project_status_id(db, payload.organization_id),
            parent_project_id=payload.parent_project_id,
        )
        db.add(project)
        db.flush()

        db.add(ProjectStage(project_id=project.id, name="Scoping", status=StageStatus.SCOPING, sort_order=0, is_current=True))

        # C-U-10: the creator becomes the project's initial manager via a
        # direct grant — no group is auto-created any more (follow-up UX
        # batch Phase C, 2026-08-31; see docs/decisions.md). This project
        # has zero groups at this point, so `_ensure_project_has_a_manager`'s
        # "existing manager-role group" branch is unreachable here and it
        # always takes the direct-grant path — the exact same fallback the
        # template-clone branch above uses, reused rather than duplicated.
        _ensure_project_has_a_manager(db, project, current_user.id)

        # Default action types (Review, Test) — seeded fresh for a manually-
        # created project. A template-cloned project instead *copies* the
        # template's own action types (see `clone_project`), the same
        # treatment as its custom field definitions, so an admin's
        # customisations to a template carry over rather than being
        # silently reset to defaults. A project created with a parent is
        # skipped entirely: it starts with zero of its own and immediately
        # falls back to the nearest ancestor's
        # (`services.project_hierarchy.resolve_effective_action_types`),
        # always on regardless of the RBAC inheritance settings above.
        if payload.parent_project_id is None:
            seed_action_types(db, project.id)

    if payload.terminology:
        project.terminology = payload.terminology
    if payload.is_template:
        project.is_template = True
    # Always explicit, never inherited from a cloned template — see
    # ProjectCreate.visibility's docstring.
    project.visibility = payload.visibility
    project.role_inheritance_mode = payload.role_inheritance_mode
    project.role_inheritance_filter_role = payload.role_inheritance_filter_role
    project.parent_required = parent_required
    project.can_be_parent = payload.can_be_parent

    log_event(
        db, entity_type="project", entity_id=project.id, action="created", actor_id=current_user.id,
        organization_id=payload.organization_id, project_id=project.id,
        detail={"template_project_id": str(template_project_id)} if template_project_id else None,
    )
    if payload.parent_project_id is not None:
        log_event(
            db, entity_type="project", entity_id=project.id, action="parented", actor_id=current_user.id,
            organization_id=payload.organization_id, project_id=project.id,
            detail={
                "parent_project_id": str(payload.parent_project_id),
                "parent_required": parent_required,
                "role_inheritance_mode": payload.role_inheritance_mode.value,
            },
        )
    db.commit()
    db.refresh(project)
    return _project_out_with_redacted_parent(db, current_user, project)


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


@router.get("/tree", response_model=list[ProjectTreeNodeOut])
def get_project_tree(
    organization_id: UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Returns the full project hierarchy for one organisation, restricted
    to the caller's accessible set — a node whose real parent isn't
    accessible is rendered as a root, never omitted or hinting at a hidden
    parent (visibility-boundary rule, see docs/decisions.md). Registered
    before `GET /{project_id}` so the static "/tree" path isn't swallowed
    by that dynamic route (same reasoning as `POST /import`'s ordering).
    """
    accessible_ids = _accessible_project_ids(db, current_user.id)
    # Defence in depth: same-org is already enforced when parent_project_id
    # is set, but build_project_tree also re-filters by organization_id
    # itself, matching this codebase's existing pattern of re-checking a
    # write-time invariant on the read side too.
    return build_project_tree(db, organization_id, accessible_ids)


@router.get("", response_model=list[ProjectListItemOut])
def list_projects(
    response: Response,
    archived: bool = False,
    search: str | None = None,
    role: ProjectRole | None = None,
    stage_status: StageStatus | None = None,
    organization_id: UUID | None = None,
    favorite_only: bool = False,
    limit: int | None = Query(None, ge=1),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Project list view (U-E-03, U-E-04): active/archived projects the user can access.

    `favorite_only` powers `FavouritesPage`, the same shape as every other
    filter here rather than a separate endpoint — a favourited-projects
    listing is otherwise identical to this one (search, org filter, and
    pagination all still make sense over it, and it needs sorted-favourites-
    first no more or less than the unfiltered list already gets below).

    Supports an optional `role` filter (only projects where the caller holds
    the given effective project role), `stage_status` filter (only projects
    whose current stage is in the given status) for U-E-05, and
    `organization_id` (only projects in that organisation — for a user
    belonging to more than one, this replaces having to visit each
    organisation separately to see just its projects). Results are sorted
    with the caller's favourited projects (U-U-03) first, then by name.
    `limit`/`offset` (U-P-06) are optional pagination — see
    `list_requirements` for the same pattern and its rationale.

    `X-Total-Unfiltered-Count` (persistent "showing X of Y" result count,
    2026-08 UX audit roadmap) is a second response header reporting the
    count within only the mandatory accessible-projects + default
    archived-visibility scope, before `organization_id`/`search`/`role`/
    `stage_status`/`favorite_only` narrow it further — unlike
    `X-Total-Count`, it does not change when the caller applies one of
    those filters.
    """
    # No server-admin bypass here (I-M-05): project listings are "data within
    # organisations", so even server admins only see projects they hold a
    # genuine role in, same as anyone else.
    accessible_ids = _accessible_project_ids(db, current_user.id)
    if not accessible_ids:
        projects = []
        response.headers["X-Total-Unfiltered-Count"] = "0"
    else:
        # Joins to Organization to exclude projects belonging to a disabled
        # org (`Organization.is_active`) — a disabled org locks out its own
        # content everywhere else (`rbac._require_org_active`), and this
        # aggregate cross-org listing had been the one place that check
        # didn't reach, since it filters by project accessible-ids rather
        # than going through a per-org `require_org_role` dependency.
        #
        # `base_conditions` (no `organization_id`) is the mandatory scope
        # for the unfiltered count above — `organization_id` is itself a
        # FilterPanel filter (the "Organisation" dropdown), the same
        # relationship `category_id` has to `RequirementsPage`'s unfiltered
        # count, so it's added only to `conditions` below, after the count
        # is taken.
        base_conditions = [
            Project.id.in_(accessible_ids),
            Project.is_archived == archived,
            Organization.is_active.is_(True),
        ]
        response.headers["X-Total-Unfiltered-Count"] = str(
            db.scalar(
                select(func.count()).select_from(
                    select(Project.id)
                    .join(Organization, Organization.id == Project.organization_id)
                    .where(*base_conditions)
                    .subquery()
                )
            )
        )
        conditions = list(base_conditions)
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

    # Hierarchical projects: parent_project_name/children are populated only
    # from projects in `accessible_ids` — the caller's own accessible set,
    # already computed above — so a hidden parent/child never surfaces even
    # from a project the caller *can* see (visibility-boundary rule, see
    # docs/decisions.md), **or** from a project in an organisation the
    # caller is `org_admin` of — added as a narrow, explicit OR-condition
    # here (not a change to what `_accessible_project_ids` itself returns)
    # so an org admin sees the true hierarchy of any project in their own
    # organisation regardless of their own role on the parent/child, per
    # the "Project hierarchy on Project Overview" entry in
    # docs/decisions.md. Safe to key off each row's own `organization_id`
    # for both its parent and its children: `parent_project_id` is
    # validated same-organisation at write time (`create_project`/
    # `update_project`, "must be a project in this organisation"), so a
    # project's parent/children always share its own organisation.
    # `admin_org_ids` is computed once per distinct organisation actually
    # present in `projects`, not per row.
    admin_org_ids = {
        oid for oid in {p.organization_id for p in projects} if is_org_admin(db, current_user.id, oid)
    }
    visible_parent_ids = {p.parent_project_id for p in projects if p.parent_project_id is not None} & accessible_ids
    visible_parent_ids |= {
        p.parent_project_id
        for p in projects
        if p.parent_project_id is not None and p.organization_id in admin_org_ids
    }
    parent_names = (
        dict(db.execute(select(Project.id, Project.name).where(Project.id.in_(visible_parent_ids))).all())
        if visible_parent_ids
        else {}
    )
    children_by_parent: dict[UUID, list[ProjectAncestorOut]] = {}
    project_ids = {p.id for p in projects}
    if project_ids:
        for child_id, child_parent_id, child_name in db.execute(
            select(Project.id, Project.parent_project_id, Project.name).where(
                Project.parent_project_id.in_(project_ids),
                or_(Project.id.in_(accessible_ids), Project.organization_id.in_(admin_org_ids)),
            )
        ).all():
            children_by_parent.setdefault(child_parent_id, []).append(
                ProjectAncestorOut(id=child_id, name=child_name)
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
        parent_visible = p.parent_project_id is not None and p.parent_project_id in parent_names
        out.append(
            ProjectListItemOut(
                id=p.id, organization_id=p.organization_id, name=p.name, summary=p.summary,
                created_at=p.created_at, updated_at=p.updated_at,
                is_archived=p.is_archived, is_template=p.is_template,
                allow_member_change_requests=p.allow_member_change_requests, visibility=p.visibility,
                terminology=p.terminology, status_id=p.status_id,
                current_stage_name=stage.name if stage else None,
                current_stage_status=stage.status if stage else None,
                my_roles=list(roles),
                is_favorite=p.id in favorite_ids,
                organization_name=org_names.get(p.organization_id, ""),
                requirement_count=requirement_counts.get(p.id, 0),
                parent_project_id=p.parent_project_id if parent_visible else None,
                parent_project_name=parent_names.get(p.parent_project_id) if parent_visible else None,
                role_inheritance_mode=p.role_inheritance_mode,
                role_inheritance_filter_role=p.role_inheritance_filter_role,
                can_be_parent=p.can_be_parent,
                children=children_by_parent.get(p.id, []),
            )
        )
    if favorite_only:
        out = [item for item in out if item.is_favorite]
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
def get_project(
    project_id: UUID, current_user: User = Depends(require_project_view_or_manage), db: Session = Depends(get_db)
):
    """Returns a single project.

    Gated by `require_project_view_or_manage`, not `require_project_view`
    — an org admin of the project's organisation can already unilaterally
    change every field this returns via `PATCH` (`require_project_manage`
    has the same `can_manage_project_settings`/`is_org_admin` bypass), so
    blocking them from *reading* it first was a real, pre-existing
    inconsistency, not a deliberate narrower boundary: it silently forced
    a "manage settings you can't see" experience and, concretely, made
    `_project_out_with_redacted_parent`'s own manager/org-admin exemption
    (below) unreachable for an org admin who holds no independent role on
    `project_id` itself. Confirmed via `require_project_view_or_manage`'s
    own precedent (`list_project_groups` already uses it for the same
    "structure, not content" reasoning) and via a full grep of this
    endpoint's existing test coverage before switching it — see
    docs/decisions.md's "Project hierarchy on Project Overview" entry.
    """
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    return _project_out_with_redacted_parent(db, current_user, project)


@router.get("/{project_id}/files", response_model=list[ProjectFileOut])
def list_project_files(
    project_id: UUID,
    response: Response,
    limit: int | None = Query(None, ge=1),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_project_view),
    db: Session = Depends(get_db),
):
    """Lists every file reachable from this project: direct requirement
    attachments (C-M-02, including linked organisation shared resources —
    `RequirementFile` covers both), requirement action attachments, and
    files attached to a comment on one of the project's own requirements.
    Fills the gap `ProjectMetricsOut.file_count` only anticipated as a
    metric (U-P-05's "number of files in project, if files are
    implemented") without ever listing them — `FileAsset` has no
    `project_id` of its own, so this joins through each of the three
    context-specific link tables that connect a file back to a project.

    Each row carries the context needed to make sense of a flat,
    project-wide list (which requirement/action/comment it came from,
    uploader, upload time) rather than a bare array of file metadata with
    no way to tell where any of them came from — see `ProjectFileOut`.

    Same-target-scoped resolution, not "has access somewhere": every join
    below filters directly on `project_id` (via `Requirement.project_id`
    for attachment/comment rows, `RequirementAction.project_id` for action
    rows), so a file belonging to a different project — even one the
    caller can also view — can never appear here. Comments on a *change
    request's* discussion thread are deliberately excluded, matching
    `ProjectMetricsOut.file_count`'s existing scope (requirement-attached
    content only).

    `limit`/`offset` (U-P-06) — same optional pagination and
    `X-Total-Count` header convention as `list_requirements`/
    `list_projects`.
    """
    entries: list[dict] = []

    for asset, linked_at, req_id, req_code, req_name in db.execute(
        select(FileAsset, RequirementFile.created_at, Requirement.id, Requirement.unique_code, RequirementVersion.name)
        .join(RequirementFile, RequirementFile.file_id == FileAsset.id)
        .join(Requirement, Requirement.id == RequirementFile.requirement_id)
        .join(
            RequirementVersion,
            (RequirementVersion.requirement_id == Requirement.id) & (RequirementVersion.valid_to.is_(None)),
        )
        .where(Requirement.project_id == project_id)
    ).all():
        entries.append({
            "file": asset, "linked_at": linked_at, "source": "requirement_attachment",
            "requirement_id": req_id, "requirement_unique_code": req_code, "requirement_name": req_name,
        })

    # Joined directly on RequirementAction.project_id rather than via a
    # linked requirement: an action may be linked to zero, one, or several
    # requirements (RequirementActionLink), so it has no single owning
    # requirement to attribute the file to.
    for asset, linked_at, action_id, action_code, action_title in db.execute(
        select(FileAsset, RequirementActionFile.created_at, RequirementAction.id, RequirementAction.unique_code, RequirementAction.title)
        .join(RequirementActionFile, RequirementActionFile.file_id == FileAsset.id)
        .join(RequirementAction, RequirementAction.id == RequirementActionFile.action_id)
        .where(RequirementAction.project_id == project_id)
    ).all():
        entries.append({
            "file": asset, "linked_at": linked_at, "source": "action_attachment",
            "action_id": action_id, "action_unique_code": action_code, "action_title": action_title,
        })

    for asset, uploaded_at, comment_id, req_id, req_code, req_name in db.execute(
        select(FileAsset, CommentFile.created_at, ReviewComment.id, Requirement.id, Requirement.unique_code, RequirementVersion.name)
        .join(CommentFile, CommentFile.file_id == FileAsset.id)
        .join(ReviewComment, ReviewComment.id == CommentFile.comment_id)
        .join(
            Requirement,
            (Requirement.id == ReviewComment.target_id) & (ReviewComment.target_type == ReviewTargetType.REQUIREMENT),
        )
        .join(
            RequirementVersion,
            (RequirementVersion.requirement_id == Requirement.id) & (RequirementVersion.valid_to.is_(None)),
        )
        .where(Requirement.project_id == project_id)
    ).all():
        entries.append({
            "file": asset, "linked_at": uploaded_at, "source": "comment_attachment",
            "requirement_id": req_id, "requirement_unique_code": req_code, "requirement_name": req_name,
            "comment_id": comment_id,
        })

    entries.sort(key=lambda e: e["linked_at"], reverse=True)

    uploader_ids = {e["file"].uploaded_by for e in entries}
    uploader_names = (
        dict(db.execute(select(User.id, User.display_name).where(User.id.in_(uploader_ids))).all())
        if uploader_ids else {}
    )

    out = [
        ProjectFileOut(
            file=FileAssetOut.model_validate(e["file"]),
            uploaded_by_display_name=uploader_names.get(e["file"].uploaded_by, ""),
            source=e["source"],
            requirement_id=e.get("requirement_id"),
            requirement_unique_code=e.get("requirement_unique_code"),
            requirement_name=e.get("requirement_name"),
            action_id=e.get("action_id"),
            action_unique_code=e.get("action_unique_code"),
            action_title=e.get("action_title"),
            comment_id=e.get("comment_id"),
        )
        for e in entries
    ]

    response.headers["X-Total-Count"] = str(len(out))
    if limit is not None:
        out = out[offset:offset + limit]
    return out


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
    toggle (C-U-13), the template flag (C-E-05), visibility, status, and
    hierarchical-projects settings (parent, forward RBAC inheritance mode).

    Parent/inheritance validation order (see docs/decisions.md's
    "Hierarchical projects" entry):
      1. Attaching to a new/different parent requires the caller to manage
         *both* this project and the target parent (decision 12) — same-org
         too — and the target parent must have `can_be_parent=True` (a
         project isn't eligible to be a parent until its own manager opts
         in; see `Project.can_be_parent`'s docstring).
      2. Detaching (clearing `parent_project_id` to null) is instead gated
         by `Project.parent_required` (decision 11): rejected unless it's
         `False` or the current actor holds `ORG_ADMIN`/`PROJECT_CREATOR`
         in this project's organisation.
      3. Cycle prevention (attach/reparent only).
      4. The `role_inheritance_mode`/`role_inheritance_filter_role`
         MIRROR_ROLE invariant, enforced against the fully-merged proposed
         state.
      5. C-U-08: if the change would leave zero effective managers
         (`get_effective_project_managers` with the proposed values),
         reject — inside the same row lock as the write, to close the
         TOCTOU window a separate check-then-write would leave open.
    """
    if payload.name is not None:
        project.name = payload.name
    if payload.summary is not None:
        project.summary = payload.summary
    if payload.allow_member_change_requests is not None:
        project.allow_member_change_requests = payload.allow_member_change_requests
    if payload.is_template is not None:
        project.is_template = payload.is_template
    if payload.can_be_parent is not None:
        project.can_be_parent = payload.can_be_parent
    if payload.visibility is not None:
        project.visibility = payload.visibility
    if payload.status_id is not None:
        new_status = db.get(ProjectStatusDefinition, payload.status_id)
        if new_status is None or new_status.organization_id != project.organization_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "status_id must be a project status defined in this project's organisation.")
        project.status_id = payload.status_id

    parent_changing = "parent_project_id" in payload.model_fields_set and payload.parent_project_id != project.parent_project_id
    new_parent_id = payload.parent_project_id if "parent_project_id" in payload.model_fields_set else project.parent_project_id
    mode_sent = payload.role_inheritance_mode is not None
    new_mode = payload.role_inheritance_mode if mode_sent else project.role_inheritance_mode
    new_filter_role = (
        payload.role_inheritance_filter_role if payload.role_inheritance_filter_role is not None
        else project.role_inheritance_filter_role
    )
    if new_mode != ProjectRoleInheritanceMode.MIRROR_ROLE:
        new_filter_role = None
    elif new_filter_role not in {ProjectRole.STAKEHOLDER, ProjectRole.PROJECT_ADMINISTRATOR, ProjectRole.PROJECT_MANAGER}:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "role_inheritance_filter_role must be one of stakeholder, project_administrator, project_manager "
            "when role_inheritance_mode is mirror_role.",
        )
    inheritance_settings_changing = (
        new_mode != project.role_inheritance_mode or new_filter_role != project.role_inheritance_filter_role
    )

    if parent_changing:
        lock_project_for_update(db, project_id)
        if new_parent_id is not None:
            # Attach/reparent: both sides must be managed by the caller.
            target_parent = db.get(Project, new_parent_id)
            if target_parent is None or target_parent.organization_id != project.organization_id:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "parent_project_id must be a project in this organisation.")
            if not can_manage_project_settings(db, current_user, target_parent):
                raise HTTPException(status.HTTP_403_FORBIDDEN, "You must manage the parent project to attach this project to it.")
            if not target_parent.can_be_parent:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    "This project has not been made eligible to be a parent — enable "
                    "\"Allow this project to be a parent\" on it first.",
                )
            if would_create_project_cycle(db, project_id, new_parent_id):
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "This would create a cycle in the project hierarchy.")
        else:
            # Detach: gated by parent_required, not by managing the old parent.
            if project.parent_required:
                org_roles = get_effective_org_roles(db, current_user.id, project.organization_id)
                if not org_roles & {OrgRole.ORG_ADMIN, OrgRole.PROJECT_CREATOR}:
                    raise HTTPException(
                        status.HTTP_403_FORBIDDEN,
                        "This project was created without organisation-level project-creation rights and must "
                        "remain nested under a parent; only an organisation admin or project creator can make "
                        "it standalone.",
                    )

    mode_changing_from_manager_contributing = (
        project.role_inheritance_mode == ProjectRoleInheritanceMode.MIRROR_ALL
        or (
            project.role_inheritance_mode == ProjectRoleInheritanceMode.MIRROR_ROLE
            and project.role_inheritance_filter_role == ProjectRole.PROJECT_MANAGER
        )
    )
    new_mode_manager_contributing = (
        new_mode == ProjectRoleInheritanceMode.MIRROR_ALL
        or (new_mode == ProjectRoleInheritanceMode.MIRROR_ROLE and new_filter_role == ProjectRole.PROJECT_MANAGER)
    )
    if mode_changing_from_manager_contributing and (not new_mode_manager_contributing or parent_changing):
        if not parent_changing:
            # Already locked above when parent_changing is True.
            lock_project_for_update(db, project_id)
        proposed_managers = get_effective_project_managers(
            db, project_id,
            mode_override=new_mode, filter_role_override_set=True, filter_role_override=new_filter_role,
            parent_override_set=True, parent_override=new_parent_id,
        )
        if not proposed_managers:
            parent_name = None
            if project.parent_project_id is not None:
                parent = db.get(Project, project.parent_project_id)
                parent_name = parent.name if parent is not None else None
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"This project's only manager is inherited from '{parent_name}'; assign a direct project manager "
                "before disabling inheritance or changing its parent." if parent_name
                else "This project's only manager is inherited from its parent; assign a direct project manager "
                "before disabling inheritance or changing its parent.",
            )

    if parent_changing:
        project.parent_project_id = new_parent_id
    if inheritance_settings_changing:
        project.role_inheritance_mode = new_mode
        project.role_inheritance_filter_role = new_filter_role

    log_event(db, entity_type="project", entity_id=project_id, action="settings_updated",
              actor_id=current_user.id, project_id=project_id, organization_id=project.organization_id,
              detail={"visibility": payload.visibility.value} if payload.visibility is not None else None)
    if parent_changing or inheritance_settings_changing:
        log_event(
            db, entity_type="project", entity_id=project_id, action="parented", actor_id=current_user.id,
            project_id=project_id, organization_id=project.organization_id,
            detail={
                "parent_project_id": str(new_parent_id) if new_parent_id else None,
                "role_inheritance_mode": new_mode.value,
                "role_inheritance_filter_role": new_filter_role.value if new_filter_role else None,
            },
        )
    db.commit()
    db.refresh(project)
    return _project_out_with_redacted_parent(db, current_user, project)


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
    return _project_out_with_redacted_parent(db, current_user, project)


@router.get("/{project_id}/ancestors", response_model=list[ProjectAncestorOut])
def get_project_ancestors(
    project_id: UUID, current_user: User = Depends(require_project_view_or_manage), db: Session = Depends(get_db),
):
    """Returns `project_id`'s ancestor chain, root-first, for a breadcrumb.

    Truncated at the first ancestor the caller can't view — never skips
    over an inaccessible ancestor and continues listing further-up ones,
    since that would present a broken/misleading breadcrumb (visibility-
    boundary rule, see docs/decisions.md).

    Org-admin bypass: an org admin of `project_id`'s own organisation sees
    the true, untruncated chain regardless of their own role/membership on
    any ancestor — added as an explicit `or is_org_admin(...)` at this call
    site only, not a change to what `_accessible_project_ids` itself
    returns (see docs/decisions.md's "Project hierarchy on Project
    Overview" entry). Safe to key off `project_id`'s own organisation for
    every ancestor in the chain: `parent_project_id` is validated
    same-organisation at write time in both `create_project` and
    `update_project` (grepped both, "must be a project in this
    organisation"), so the whole chain is guaranteed to share one
    organisation — gated by `require_project_view_or_manage`, so this is
    only reachable at all once the caller can view or manage `project_id`
    itself.
    """
    anchor_organization_id = db.scalar(select(Project.organization_id).where(Project.id == project_id))
    admin_bypass = anchor_organization_id is not None and is_org_admin(db, current_user.id, anchor_organization_id)
    accessible_ids = _accessible_project_ids(db, current_user.id)
    chain = get_ancestor_chain(db, project_id)
    result: list[ProjectAncestorOut] = []
    for ancestor in chain:
        if not admin_bypass and ancestor.id not in accessible_ids:
            break
        result.append(ProjectAncestorOut(id=ancestor.id, name=ancestor.name))
    return result


@router.get("/{project_id}/children", response_model=list[ProjectListItemOut])
def get_project_children(
    project_id: UUID, current_user: User = Depends(require_project_view_or_manage), db: Session = Depends(get_db),
):
    """Returns `project_id`'s direct children, filtered to the caller's
    accessible set — no hidden-count hint for the ones omitted, same
    visibility-boundary rule as `list_projects`'s `children` field.

    Org-admin bypass: an org admin of `project_id`'s own organisation sees
    every true child regardless of their own role/membership on it — a
    child is always same-organisation as its parent (enforced at write
    time, see `get_project_ancestors`'s docstring above), so `project_id`'s
    own organisation is the correct one to check for every child returned
    here.
    """
    anchor_organization_id = db.scalar(select(Project.organization_id).where(Project.id == project_id))
    admin_bypass = anchor_organization_id is not None and is_org_admin(db, current_user.id, anchor_organization_id)
    accessible_ids = _accessible_project_ids(db, current_user.id)
    children_filter = (
        Project.parent_project_id == project_id
        if admin_bypass
        else (Project.parent_project_id == project_id) & Project.id.in_(accessible_ids)
    )
    children = db.scalars(select(Project).where(children_filter)).all()
    favorite_ids = set(
        db.scalars(select(FavoriteProject.project_id).where(FavoriteProject.user_id == current_user.id)).all()
    )
    org_names = dict(
        db.execute(
            select(Organization.id, Organization.name).where(
                Organization.id.in_({c.organization_id for c in children})
            )
        ).all()
    )
    out = []
    for c in children:
        stage = db.scalar(select(ProjectStage).where(ProjectStage.project_id == c.id, ProjectStage.is_current.is_(True)))
        roles = sorted(get_effective_project_roles(db, current_user.id, c.id), key=lambda r: r.value)
        out.append(
            ProjectListItemOut(
                id=c.id, organization_id=c.organization_id, name=c.name, summary=c.summary,
                created_at=c.created_at, updated_at=c.updated_at,
                is_archived=c.is_archived, is_template=c.is_template,
                allow_member_change_requests=c.allow_member_change_requests, visibility=c.visibility,
                terminology=c.terminology, status_id=c.status_id,
                current_stage_name=stage.name if stage else None,
                current_stage_status=stage.status if stage else None,
                my_roles=list(roles), is_favorite=c.id in favorite_ids,
                organization_name=org_names.get(c.organization_id, ""),
                parent_project_id=project_id, parent_project_name=None,
                role_inheritance_mode=c.role_inheritance_mode, role_inheritance_filter_role=c.role_inheritance_filter_role,
                can_be_parent=c.can_be_parent,
            )
        )
    return out


@router.get("/{project_id}/member-sources", response_model=list[ProjectMemberSourceOut])
def list_member_sources(
    project_id: UUID, current_user: User = Depends(require_project_view), db: Session = Depends(get_db),
):
    """Lists the other same-organisation projects `project_id` currently
    consumes members from (the reverse/source->receiving RBAC mechanism —
    see `models.project.ProjectMemberSource`'s docstring)."""
    rows = db.execute(
        select(
            ProjectMemberSource.source_project_id, Project.name,
            ProjectMemberSource.mirror_mode, ProjectMemberSource.mirror_filter_role,
        )
        .join(Project, Project.id == ProjectMemberSource.source_project_id)
        .where(ProjectMemberSource.project_id == project_id)
    ).all()
    return [
        ProjectMemberSourceOut(source_project_id=sid, source_project_name=name, mirror_mode=mode, mirror_filter_role=filter_role)
        for sid, name, mode, filter_role in rows
    ]


@router.post("/{project_id}/member-sources", response_model=ProjectMemberSourceOut, status_code=status.HTTP_201_CREATED)
def add_member_source(
    project_id: UUID, payload: ProjectMemberSourceAdd, project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Adds another project to `project_id`'s member-source list — gated by
    managing `project_id` (the *receiving* side) only, never the source,
    per the authorization-asymmetry design described in `models.project.
    ProjectMemberSource`'s docstring and docs/decisions.md.

    `source_project_id` must belong to `project_id`'s own organisation —
    originally restricted further, to a direct child only; generalized
    (docs/decisions.md) to any project in the same organisation, since the
    original parent/child-only restriction was the actual limitation this
    generalization exists to remove. No separate accessible-set check on
    top of the same-org requirement: the caller already manages
    `project_id` itself, and requiring them to *also* independently hold a
    role on the specific source would defeat the feature's own purpose —
    a manager must be able to consume members from any project they know
    about in their organisation, including one with no existing role
    structure of its own yet. Project names are not confidential within an
    organisation (a manager can already see every project in their org via
    the ordinary project list), so this doesn't create an existence-oracle
    concern the way an accessible-set restriction on `parent_project_id`
    selection does elsewhere.
    """
    source_project_id = payload.source_project_id
    if source_project_id == project_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "source_project_id must not be this project itself.")
    source_project = db.get(Project, source_project_id)
    if source_project is None or source_project.organization_id != project.organization_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "source_project_id must belong to this project's organisation.")
    existing = db.scalar(
        select(ProjectMemberSource).where(
            ProjectMemberSource.project_id == project_id, ProjectMemberSource.source_project_id == source_project_id
        )
    )
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This project is already a member source.")
    db.add(ProjectMemberSource(
        project_id=project_id, source_project_id=source_project_id,
        mirror_mode=payload.mirror_mode, mirror_filter_role=payload.mirror_filter_role,
    ))
    log_event(
        db, entity_type="project_member_source", entity_id=project_id, action="added", actor_id=current_user.id,
        project_id=project_id, organization_id=project.organization_id,
        detail={
            "source_project_id": str(source_project_id), "mirror_mode": payload.mirror_mode.value,
            "mirror_filter_role": payload.mirror_filter_role.value if payload.mirror_filter_role else None,
        },
    )
    db.commit()
    return ProjectMemberSourceOut(
        source_project_id=source_project_id, source_project_name=source_project.name,
        mirror_mode=payload.mirror_mode, mirror_filter_role=payload.mirror_filter_role,
    )


@router.delete("/{project_id}/member-sources/{source_project_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member_source(
    project_id: UUID, source_project_id: UUID, project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Removes a child from `project_id`'s member-source list — always
    allowed (removing a grant is safe unilaterally), including for an
    already-stale entry."""
    existing = db.scalar(
        select(ProjectMemberSource).where(
            ProjectMemberSource.project_id == project_id, ProjectMemberSource.source_project_id == source_project_id
        )
    )
    if existing is not None:
        db.delete(existing)
        log_event(
            db, entity_type="project_member_source", entity_id=project_id, action="removed", actor_id=current_user.id,
            project_id=project_id, organization_id=project.organization_id,
            detail={"source_project_id": str(source_project_id)},
        )
        db.commit()


@router.delete("/{project_id}/children/{child_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_child_project(
    child_id: UUID, project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Lets a parent detach a specific child from its own side, without
    needing `require_project_manage` on the child itself (decision 12 in
    docs/decisions.md) — gated purely on managing `project_id` (the
    parent — `require_project_manage`'s own `{project_id}` path parameter
    name is why this route uses `project_id` rather than `parent_id`, even
    though "parent" is the more natural name for what it means here).
    Still subject to the child's own `Project.parent_required` gate
    (decision 11): a parent's own manage rights are not sufficient on
    their own to force a `parent_required` child loose, the same rule
    `update_project` applies to a child-initiated detach.
    """
    parent_id = project.id
    child = db.get(Project, child_id)
    if child is None or child.parent_project_id != parent_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This project is not a direct child of the given parent.")
    lock_project_for_update(db, child_id)
    if child.parent_required:
        org_roles = get_effective_org_roles(db, current_user.id, child.organization_id)
        if not org_roles & {OrgRole.ORG_ADMIN, OrgRole.PROJECT_CREATOR}:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "This project was created without organisation-level project-creation rights and must remain "
                "nested under a parent; only an organisation admin or project creator can detach it.",
            )
    proposed_managers = get_effective_project_managers(
        db, child_id, parent_override_set=True, parent_override=None,
    )
    if not proposed_managers:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"'{child.name}''s only manager is inherited from this project; it must be given a direct project "
            "manager before it can be detached.",
        )
    child.parent_project_id = None
    log_event(
        db, entity_type="project", entity_id=child_id, action="detached_by_parent", actor_id=current_user.id,
        project_id=child_id, organization_id=child.organization_id, detail={"former_parent_id": str(parent_id)},
    )
    db.commit()


@router.get("/{project_id}/effective-members", response_model=list[EffectiveMemberOut])
def get_effective_members(
    project_id: UUID,
    response: Response,
    search: str | None = None,
    limit: int | None = Query(None, ge=1),
    offset: int = Query(0, ge=0),
    project: Project = Depends(require_project_manage),
    db: Session = Depends(get_db),
):
    """Every user with effective access to this project, with provenance —
    direct (and, since the follow-up UX batch's Phase D, which of the five
    direct sources specifically — see `MemberSourceProvenanceOut`'s
    docstring), or inherited (and how) — for the project admin/access-review
    view (decision 10 in docs/decisions.md) and the unified Members table
    (decision 11). `require_project_manage`-gated rather than view-only:
    this is an access-review surface, appropriately restricted to people who
    already manage the project — see the forward/member-source-inheritance
    blast-radius discussion in docs/decisions.md for why that's not a new
    disclosure beyond what `role_inheritance_mode` already implies once
    enabled.

    `search` (name/email substring, case-insensitive) and `limit`/`offset`
    are optional, same contract as `list_project_groups`: omitting `limit`
    returns every matching member unpaginated, and the pre-slice
    (post-search) total is returned via `X-Total-Count`.

    IMPORTANT — this is application-level pagination, not database-level:
    `get_effective_project_members_with_provenance` still resolves every
    candidate user's full provenance in Python before any sorting/filtering
    happens here (see that function's own docstring — it iterates every
    user in the organisation, one admin-only view opened occasionally, not
    a request-hot-path RBAC check). `search`/`limit`/`offset` are applied as
    an in-memory slice *after* that full resolution and a deterministic
    sort by `display_name` (case-insensitive), not pushed down into SQL —
    this gets the directory pattern's UI/UX (search box, `LoadMoreButton`)
    without restructuring the underlying query engine, and does not scale
    indefinitely the way a real DB-level `LIMIT`/`OFFSET` would. A future
    pass should not assume this endpoint scales past a project admin's
    realistic member-list size without revisiting `get_effective_project_
    members_with_provenance` itself.
    """
    provenance = get_effective_project_members_with_provenance(db, project_id)
    project_name_cache: dict[UUID, str] = {}

    def project_name(pid: UUID | None) -> str | None:
        if pid is None:
            return None
        if pid not in project_name_cache:
            p = db.get(Project, pid)
            project_name_cache[pid] = p.name if p is not None else ""
        return project_name_cache[pid] or None

    out: list[EffectiveMemberOut] = []
    for user_id, entries in provenance.items():
        user = db.get(User, user_id)
        if user is None:
            continue
        effective_roles = get_effective_project_roles(db, user_id, project_id)
        if not effective_roles:
            continue
        if ProjectRole.PROJECT_MANAGER in effective_roles:
            effective_role = ProjectRole.PROJECT_MANAGER
        elif ProjectRole.PROJECT_ADMINISTRATOR in effective_roles:
            effective_role = ProjectRole.PROJECT_ADMINISTRATOR
        elif ProjectRole.STAKEHOLDER in effective_roles:
            effective_role = ProjectRole.STAKEHOLDER
        else:
            effective_role = ProjectRole.MEMBER
        out.append(
            EffectiveMemberOut(
                user_id=user_id, display_name=user.display_name, email=user.email, effective_role=effective_role,
                sources=[
                    {
                        "kind": e["kind"], "role": e["role"], "via_project_id": e["via_project_id"],
                        "via_project_name": project_name(e["via_project_id"]), "via_mode": e["via_mode"],
                        "via_group_id": e["via_group_id"], "via_group_name": e["via_group_name"],
                    }
                    for e in entries
                ],
            )
        )

    out.sort(key=lambda m: m.display_name.lower())
    if search:
        needle = search.lower()
        out = [m for m in out if needle in m.display_name.lower() or needle in m.email.lower()]

    response.headers["X-Total-Count"] = str(len(out))
    if limit is not None:
        out = out[offset:offset + limit]
    return out


@router.post("/{project_id}/materialize-inherited-access", response_model=MaterializeResultOut)
def materialize_inherited_access(
    project_id: UUID, project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Snapshots every currently forward- or member-source-inherited user
    onto a direct `UserProjectRole` row at their currently-effective role
    (decision 9 in docs/decisions.md) — a one-time conversion, not an
    ongoing sync, so those users keep access once inheritance is
    subsequently disabled/changed/removed. Idempotent: skips anyone who
    already holds an equal-or-higher direct role. Offered proactively
    (before disabling a manager-contributing mode, reparenting, or
    removing a member-source entry) so nobody's access silently
    disappears.
    """
    _ROLE_RANK = {
        ProjectRole.MEMBER: 0, ProjectRole.STAKEHOLDER: 1,
        ProjectRole.PROJECT_ADMINISTRATOR: 1, ProjectRole.PROJECT_MANAGER: 2,
    }
    provenance = get_effective_project_members_with_provenance(db, project_id)
    created: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    for user_id, entries in provenance.items():
        inherited_roles = {e["role"] for e in entries if e["kind"] in ("forward_inherited", "member_source_inherited")}
        if not inherited_roles:
            continue
        best_inherited = max(inherited_roles, key=lambda r: _ROLE_RANK[r])
        direct_roles = set(
            db.scalars(
                select(UserProjectRole.role).where(UserProjectRole.user_id == user_id, UserProjectRole.project_id == project_id)
            ).all()
        )
        direct_rank = max((_ROLE_RANK[r] for r in direct_roles), default=-1)
        if direct_rank >= _ROLE_RANK[best_inherited]:
            skipped.append({"user_id": str(user_id), "role": best_inherited.value})
            continue
        db.add(UserProjectRole(user_id=user_id, project_id=project_id, role=best_inherited))
        created.append({"user_id": str(user_id), "role": best_inherited.value})
    if created:
        log_event(
            db, entity_type="project", entity_id=project_id, action="inherited_access_materialized",
            actor_id=current_user.id, project_id=project_id, organization_id=project.organization_id,
            detail={"created": created},
        )
        db.commit()
    return MaterializeResultOut(created=created, skipped=skipped)


@router.post("/{project_id}/materialize-inherited-access/{user_id}", response_model=MaterializeResultOut)
def materialize_inherited_access_for_user(
    project_id: UUID, user_id: UUID, project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Per-row counterpart to `materialize_inherited_access` (PR6 of the
    members/groups directory rework plan) — `ProjectMembersTable`'s
    per-member "Convert inherited access to direct roles" action. Same
    rank logic, idempotency, and audit action as the bulk endpoint, just
    filtered to `user_id`'s own provenance entries rather than iterating
    every member: skip (no-op) if this user holds no forward-/member-
    source-inherited role at all, or if their existing direct role already
    ranks at or above their best inherited one. Treated as access-mutating
    (identify -> verify -> remediate review, docs/decisions.md) since it
    can create a new, independently-revocable `UserProjectRole` row, same
    as the bulk endpoint it reuses the logic of.
    """
    _ROLE_RANK = {
        ProjectRole.MEMBER: 0, ProjectRole.STAKEHOLDER: 1,
        ProjectRole.PROJECT_ADMINISTRATOR: 1, ProjectRole.PROJECT_MANAGER: 2,
    }
    provenance = get_effective_project_members_with_provenance(db, project_id)
    entries = provenance.get(user_id, [])
    inherited_roles = {e["role"] for e in entries if e["kind"] in ("forward_inherited", "member_source_inherited")}
    created: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    if inherited_roles:
        best_inherited = max(inherited_roles, key=lambda r: _ROLE_RANK[r])
        direct_roles = set(
            db.scalars(
                select(UserProjectRole.role).where(UserProjectRole.user_id == user_id, UserProjectRole.project_id == project_id)
            ).all()
        )
        direct_rank = max((_ROLE_RANK[r] for r in direct_roles), default=-1)
        if direct_rank >= _ROLE_RANK[best_inherited]:
            skipped.append({"user_id": str(user_id), "role": best_inherited.value})
        else:
            db.add(UserProjectRole(user_id=user_id, project_id=project_id, role=best_inherited))
            created.append({"user_id": str(user_id), "role": best_inherited.value})
    if created:
        log_event(
            db, entity_type="project", entity_id=project_id, action="inherited_access_materialized",
            actor_id=current_user.id, project_id=project_id, organization_id=project.organization_id,
            detail={"created": created, "target_user_id": str(user_id)},
        )
        db.commit()
    return MaterializeResultOut(created=created, skipped=skipped)


@router.post("/{project_id}/materialize-inherited-access/group/{org_group_id}", response_model=MaterializeResultOut)
def materialize_inherited_access_for_group(
    project_id: UUID, org_group_id: UUID, project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Group-scoped counterpart to `materialize_inherited_access` (PR6) —
    converts an org group's *own* forward-/member-source-inherited role on
    this project (`get_group_inherited_project_roles`, walking ancestor/
    source projects' `OrgGroupProjectRole` grants for this exact group —
    PR4's inheritance-cascade extension) into a direct `OrgGroupProjectRole`
    grant, parallel to how the per-user endpoint above converts a user's
    inherited role into a direct `UserProjectRole`.

    Same cross-tenant re-check `assign_group_project_role` already applies
    to its own `org_group_id` target, the same rank-based "skip if an
    equal-or-higher direct role is already held" idempotency as the bulk/
    per-user endpoints, and the same audit action
    (`"inherited_access_materialized"`) — entity type `org_group_project_
    role` rather than `project`/`user_project_role`, matching `assign_
    group_project_role`'s own entity-type choice for the same mechanism.

    No UI currently renders a group row in an "inherited" state to offer
    this action from (see docs/decisions.md's PR6 entry): the unified
    Groups directory (`ProjectAdminPage.tsx`'s `groupsTabRows`) only has
    `ProjectGroup` rows (direct by construction since PR7) and
    `ProjectMemberSource` virtual rows (a different mechanism, no
    "inherited" state of its own to convert) — no row kind represents an
    org group's own `OrgGroupProjectRole` provenance the way this endpoint
    needs. The endpoint exists and is tested directly via the API
    regardless, since the underlying provenance kind is real (PR4 built the
    cascade) and a future UI surfacing a group's direct-grant provenance
    should be able to call straight into this without a backend change.
    """
    org_group = db.get(OrgGroup, org_group_id)
    if org_group is None or org_group.organization_id != project.organization_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "org_group_id must belong to the project's organisation.")

    _ROLE_RANK = {
        ProjectRole.MEMBER: 0, ProjectRole.STAKEHOLDER: 1,
        ProjectRole.PROJECT_ADMINISTRATOR: 1, ProjectRole.PROJECT_MANAGER: 2,
    }
    inherited_roles = get_group_inherited_project_roles(db, org_group_id, project_id)
    created: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    if inherited_roles:
        best_inherited = max(inherited_roles, key=lambda r: _ROLE_RANK[r])
        direct_roles = set(
            db.scalars(
                select(OrgGroupProjectRole.role).where(
                    OrgGroupProjectRole.org_group_id == org_group_id, OrgGroupProjectRole.project_id == project_id,
                )
            ).all()
        )
        direct_rank = max((_ROLE_RANK[r] for r in direct_roles), default=-1)
        if direct_rank >= _ROLE_RANK[best_inherited]:
            skipped.append({"org_group_id": str(org_group_id), "role": best_inherited.value})
        else:
            db.add(OrgGroupProjectRole(org_group_id=org_group_id, project_id=project_id, role=best_inherited))
            created.append({"org_group_id": str(org_group_id), "role": best_inherited.value})
    if created:
        log_event(
            db, entity_type="org_group_project_role", entity_id=org_group_id, action="inherited_access_materialized",
            actor_id=current_user.id, project_id=project_id, organization_id=project.organization_id,
            detail={"created": created},
        )
        db.commit()
    return MaterializeResultOut(created=created, skipped=skipped)


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
    return _project_out_with_redacted_parent(db, current_user, project)


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
    return _project_out_with_redacted_parent(db, current_user, project)


@router.get("/{project_id}/changes", response_model=list[ChangeEntryOut])
def get_project_changes_endpoint(
    project_id: UUID,
    response: Response,
    since: datetime | None = None,
    until: datetime | None = None,
    include_comments: bool = False,
    entity_type: str | None = None,
    limit: int | None = Query(None, ge=1),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_project_view),
    db: Session = Depends(get_db),
):
    """Project changes-over-time view (C-A-10): a unified timeline of
    requirement/change-request/audit events, with an optional time range
    and entity-type filter. Discussion comments are excluded unless
    `include_comments=true`.

    `limit`/`offset` (U-P-06) are optional, same contract as
    `list_requirements`: omitting both returns the full timeline unchanged
    from before pagination existed. When `limit` is given, the total match
    count (before slicing) is returned in the `X-Total-Count` response
    header. Slicing happens here rather than in `get_project_changes`
    itself, since that function has two other, unpaginated callers
    (`requirements.py`/`change_requests.py`'s per-entity activity panels)
    that need its complete merged-and-sorted result to filter down
    themselves.
    """
    entries = get_project_changes(
        db, project_id, since=since, until=until, include_comments=include_comments, entity_type=entity_type,
    )
    response.headers["X-Total-Count"] = str(len(entries))
    if limit is not None:
        entries = entries[offset:offset + limit]
    return entries


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
        # C-G-11: completion is `Requirement.is_completed`, an overlay
        # marker independent of `RequirementVersion.status` (no longer a
        # `RequirementStatus` value at all) — queried directly off the
        # identity row, not the version.
        completed = len(
            db.scalars(
                select(Requirement.id).where(
                    Requirement.id.in_(requirement_ids), Requirement.is_completed.is_(True)
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
                        select(Requirement.id).where(
                            Requirement.id.in_(item_requirement_ids), Requirement.is_completed.is_(True)
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
    _notify_stage_transition(db, project, stage, current_user.id)
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

    _notify_stage_transition(db, project, stage, current_user.id)
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


def _notify_stage_transition(db: Session, project: Project, stage: ProjectStage, actor_id: UUID) -> None:
    """Notifies all project members of stage transitions (C-N-01), including
    a newly created stage entering scoping.

    Per the requirement's "unless brand new project" clarification, a brand
    new *project's* very first stage must not notify — but that stage is
    created directly in `create_project` (never through this function), so
    every actual caller of `_notify_stage_transition` (a subsequent stage
    being created via `create_stage`, or an existing stage transitioning via
    `transition_stage`) is, by construction, never that excluded case.

    `actor_id` is whoever created the stage or triggered the transition —
    excluded from this broadcast so they're not told about the very change
    they just made (e.g. the project manager who approved the stage).
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
                actor_id=actor_id,
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
    result = move_ordered(db, ProjectComponent, [ProjectComponent.project_id == project.id], component_id, payload.direction)
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
    result = move_ordered(db, ProjectCategory, [ProjectCategory.component_id == category.component_id], category_id, payload.direction)
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
    """Creates a bare project group with no role at all (PR7, docs/
    decisions.md) — a role is a separate, explicit grant added afterward via
    `POST /{project_id}/groups/{group_id}/roles`, symmetric with how
    `create_org_group` already creates an org group bare."""
    group = ProjectGroup(project_id=project.id, name=payload.name)
    db.add(group)
    db.flush()
    log_event(
        db, entity_type="project_group", entity_id=group.id, action="created", actor_id=current_user.id,
        project_id=project.id, detail={"name": group.name},
    )
    db.commit()
    db.refresh(group)
    return ProjectGroupOut(id=group.id, name=group.name, roles=[],
                            member_user_ids=[], member_org_group_ids=[], member_source_project_ids=[])


@router.get("/{project_id}/groups", response_model=list[ProjectGroupOut])
def list_project_groups(
    project_id: UUID,
    response: Response,
    search: str | None = None,
    order: str = Query("asc", pattern="^(asc|desc)$"),
    limit: int | None = Query(None, ge=1),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_project_view_or_manage),
    db: Session = Depends(get_db),
):
    """Lists a project's groups, each with its resolved member/nested-org-
    group id lists.

    `search` (name substring, case-insensitive) and `limit`/`offset`
    (U-P-06, 2026-08 UX audit "Directories at scale") are optional, same
    contract as `list_org_groups`: omitting `limit` returns every group
    unpaginated, and the pre-slice total is returned via `X-Total-Count`
    when given.

    `order` (Phase B, follow-up UX batch, 2026-08-31 — same reasoning as
    `list_org_groups`'s own `order` param) flips the existing name
    ascending order to descending; `DirectoryTable`'s Name column is this
    list's only sortable column, so there's no separate `sort` field param.
    """
    query = select(ProjectGroup).where(ProjectGroup.project_id == project_id)
    if search:
        query = query.where(ProjectGroup.name.ilike(f"%{search}%"))
    name_order = ProjectGroup.name.desc() if order == "desc" else ProjectGroup.name
    groups = db.scalars(query.order_by(name_order)).all()

    response.headers["X-Total-Count"] = str(len(groups))
    if limit is not None:
        groups = groups[offset:offset + limit]

    out = []
    for g in groups:
        members = db.scalars(select(ProjectGroupMember).where(ProjectGroupMember.project_group_id == g.id)).all()
        roles = db.scalars(select(ProjectGroupRole.role).where(ProjectGroupRole.project_group_id == g.id)).all()
        out.append(ProjectGroupOut(
            id=g.id, name=g.name, roles=list(roles),
            member_user_ids=[m.user_id for m in members if m.user_id],
            member_org_group_ids=[m.org_group_id for m in members if m.org_group_id],
            member_source_project_ids=[m.source_project_id for m in members if m.source_project_id],
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


def _project_group_out(db: Session, group: ProjectGroup) -> ProjectGroupOut:
    """Shared `ProjectGroupOut` assembly for the endpoints below that return
    a single, already-persisted group with its resolved membership/role
    lists — factored out of `list_project_groups`'s per-row loop so the
    group-role grant/revoke endpoints don't duplicate the same queries."""
    members = db.scalars(select(ProjectGroupMember).where(ProjectGroupMember.project_group_id == group.id)).all()
    roles = db.scalars(select(ProjectGroupRole.role).where(ProjectGroupRole.project_group_id == group.id)).all()
    return ProjectGroupOut(
        id=group.id, name=group.name, roles=list(roles),
        member_user_ids=[m.user_id for m in members if m.user_id],
        member_org_group_ids=[m.org_group_id for m in members if m.org_group_id],
        member_source_project_ids=[m.source_project_id for m in members if m.source_project_id],
    )


@router.post("/{project_id}/groups/{group_id}/roles", status_code=status.HTTP_204_NO_CONTENT)
def assign_project_group_role(
    project_id: UUID, group_id: UUID, payload: ProjectGroupRoleAssign,
    project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Grants a project group one more role (PR7, docs/decisions.md) —
    replaces the old `PATCH /{project_id}/groups/{group_id}` "change the
    group's one role" endpoint now that a group can hold zero, one, or
    several roles at once: each is its own independently-revocable
    `ProjectGroupRole` row rather than a single mutable field. Mirrors
    `assign_group_project_role` (PR4's org-group-role grant) as closely as
    sensible, adapted for a project-group target instead of an org-group
    one — same 204-no-body shape, and no cross-tenant check is needed here
    (unlike that endpoint's `org_group_id` re-validation), since a
    `ProjectGroup` already belongs to exactly one project by construction;
    `_get_group_in_project` already 404s if `group_id` doesn't belong to
    `project_id` at all.

    Idempotent like `assign_group_project_role`/`assign_project_role`:
    granting an already-held role is a silent no-op, not a 409 — no audit
    event or commit happens on the no-op path.
    """
    _get_group_in_project(db, project.id, group_id)
    existing = db.scalar(
        select(ProjectGroupRole).where(
            ProjectGroupRole.project_group_id == group_id, ProjectGroupRole.role == payload.role,
        )
    )
    if existing is None:
        db.add(ProjectGroupRole(project_group_id=group_id, role=payload.role))
        log_event(
            db, entity_type="project_group", entity_id=group_id, action="role_granted", actor_id=current_user.id,
            project_id=project.id, detail={"role": payload.role.value},
        )
        db.commit()


@router.delete("/{project_id}/groups/{group_id}/roles/{role}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_project_group_role(
    project_id: UUID, group_id: UUID, role: ProjectRole,
    project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Revokes one role from a project group (PR7) — the group-scoped
    C-U-08 guard site this PR adds, shaped like `delete_project_group`'s
    (lock the project row, perform the delete, flush, then re-check
    `get_effective_project_managers` before commit) rather than a single-
    user pre-check, since revoking a group's role can remove effective
    access from every member of that group at once. Same defense-in-depth
    reasoning as `revoke_group_project_role`'s own C-U-08 guard: a
    `ProjectGroup`'s *direct user* members DO count towards the C-U-08
    floor via `_direct_project_managers` (unlike a nested/direct org
    group), so this guard is the one that actually matters in practice for
    this mechanism, not just a defensive fallback — see docs/decisions.md's
    identify/verify/remediate entry for this endpoint.
    """
    _get_group_in_project(db, project.id, group_id)
    if role == ProjectRole.PROJECT_MANAGER:
        lock_project_for_update(db, project.id)
    removed = db.execute(
        ProjectGroupRole.__table__.delete().where(
            ProjectGroupRole.project_group_id == group_id, ProjectGroupRole.role == role,
        )
    )
    db.flush()
    if role == ProjectRole.PROJECT_MANAGER and not get_effective_project_managers(db, project.id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A project must have at least one project manager.")
    if removed.rowcount:
        log_event(
            db, entity_type="project_group", entity_id=group_id, action="role_revoked", actor_id=current_user.id,
            project_id=project.id, detail={"role": role.value},
        )
        # Same per-member engagement cleanup `revoke_group_project_role`
        # applies for its own (potentially many-user) revocation: a group's
        # role can be one of several sources a member holds it through, so
        # only clean up subscriptions/favourites for someone this actually
        # left with no remaining access at all.
        affected_user_ids = {
            m.user_id
            for m in db.scalars(
                select(ProjectGroupMember).where(
                    ProjectGroupMember.project_group_id == group_id, ProjectGroupMember.user_id.is_not(None),
                )
            ).all()
        }
        for affected_user_id in affected_user_ids:
            if not get_effective_project_roles(db, affected_user_id, project.id):
                engagement.remove_subscriptions_and_favorites_for_projects(db, affected_user_id, [project.id])
    db.commit()


@router.delete("/{project_id}/groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project_group(
    project_id: UUID, group_id: UUID,
    project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Deletes a project group entirely; its `ProjectGroupMember` rows go
    with it via `ondelete="CASCADE"`. No group is specially protected from
    deletion any more (follow-up UX batch Phase C, 2026-08-31 removed the
    four auto-created "standard" groups and their `is_default` flag
    entirely — see docs/decisions.md) — the only thing standing between a
    delete and an unmanaged project is the C-U-08 guard immediately below,
    which applies identically to every group regardless of how it was
    created.

    Same C-U-08 guard as `assign_project_group_role`/`revoke_project_group_
    role`, shaped for a whole-group removal rather than a single-role
    change: if this group currently holds a `PROJECT_MANAGER` grant (PR7:
    checked against `ProjectGroupRole`, not the old scalar `ProjectGroup.
    role`), the project row is locked first, then the group (and every
    membership/role under it) is deleted and flushed, then `get_effective_
    project_managers` is re-checked before commit. The check has to run
    *after* the delete is flushed, not before, unlike `remove_project_group_
    member`'s single-membership check — a whole-group delete removes every
    membership at once, so a pre-check would have to reproduce "what would
    managers look like without this group" rather than just asking the
    normal live-state question afterward.
    """
    group = _get_group_in_project(db, project.id, group_id)

    group_roles = list(db.scalars(select(ProjectGroupRole.role).where(ProjectGroupRole.project_group_id == group_id)).all())
    is_manager_group = ProjectRole.PROJECT_MANAGER in group_roles
    if is_manager_group:
        lock_project_for_update(db, project.id)

    log_event(
        db, entity_type="project_group", entity_id=group_id, action="deleted", actor_id=current_user.id,
        project_id=project.id, detail={"name": group.name, "roles": [r.value for r in group_roles]},
    )
    db.delete(group)
    db.flush()
    if is_manager_group and not get_effective_project_managers(db, project.id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A project must have at least one project manager.")
    db.commit()


@router.post("/{project_id}/groups/{group_id}/members", status_code=status.HTTP_204_NO_CONTENT)
def add_project_group_member(
    project_id: UUID, group_id: UUID, payload: ProjectGroupMemberAdd,
    project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    target_count = sum(x is not None for x in (payload.user_id, payload.org_group_id, payload.source_project_id))
    if target_count != 1:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Provide exactly one of user_id, org_group_id, source_project_id.")
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
    if payload.source_project_id is not None:
        # Same cross-tenant boundary as org_group_id above, plus a
        # self-reference guard (a project referencing its own roster is
        # meaningless and would recurse straight into itself if the
        # non-recursive one-hop guarantee ever changed) — see
        # `models.project.ProjectGroupMember.source_project_id`'s docstring.
        if payload.source_project_id == project.id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "source_project_id must not be this project itself.")
        source_project = db.get(Project, payload.source_project_id)
        if source_project is None or source_project.organization_id != project.organization_id:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "source_project_id must belong to the project's organisation."
            )
    db.add(ProjectGroupMember(
        project_group_id=group_id, user_id=payload.user_id, org_group_id=payload.org_group_id,
        source_project_id=payload.source_project_id,
    ))
    log_event(
        db, entity_type="project_group", entity_id=group_id, action="member_added", actor_id=current_user.id,
        project_id=project.id,
        detail={"user_id": str(payload.user_id) if payload.user_id else None,
                "org_group_id": str(payload.org_group_id) if payload.org_group_id else None,
                "source_project_id": str(payload.source_project_id) if payload.source_project_id else None},
    )
    if payload.user_id is not None:
        added_user = db.get(User, payload.user_id)
        if added_user is not None:
            group = db.get(ProjectGroup, group_id)
            notify(
                db, added_user, notification_type=NotificationType.PROJECT_JOINED,
                title=f"You were added to {project.name}",
                body=f"You were added to the '{group.name}' group." if group else "",
                project_id=project.id, actor_id=current_user.id,
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

    Blocks the removal if `group` currently holds a `PROJECT_MANAGER` grant
    (PR7: checked against `ProjectGroupRole`, not the old scalar
    `ProjectGroup.role` — a group can now hold that grant alongside others)
    and `member_id` is currently the project's only manager (C-U-08),
    mirroring the same guard `revoke_project_role` applies to direct role
    revocation — a project must always retain at least one manager. Same
    `is_inherited_manager` exception as that guard: removing this
    membership is safe if `member_id` would remain a manager via forward
    inheritance alone (member_id may be a user id, an org-group id, or a
    source-project id here — `is_inherited_manager` only applies to a real
    user, so a group/project-reference removal always falls through to the
    block, unchanged from before).
    """
    _get_group_in_project(db, project.id, group_id)
    group_is_manager = db.scalar(
        select(ProjectGroupRole).where(
            ProjectGroupRole.project_group_id == group_id, ProjectGroupRole.role == ProjectRole.PROJECT_MANAGER,
        )
    ) is not None
    if group_is_manager:
        lock_project_for_update(db, project.id)
        managers = get_effective_project_managers(db, project.id)
        if managers == {member_id} and not is_inherited_manager(db, member_id, project.id):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "A project must have at least one project manager.")
    removed_member = db.scalar(
        select(ProjectGroupMember).where(
            ProjectGroupMember.project_group_id == group_id,
            (ProjectGroupMember.user_id == member_id)
            | (ProjectGroupMember.org_group_id == member_id)
            | (ProjectGroupMember.source_project_id == member_id),
        )
    )
    db.execute(
        ProjectGroupMember.__table__.delete().where(
            ProjectGroupMember.project_group_id == group_id,
            (ProjectGroupMember.user_id == member_id)
            | (ProjectGroupMember.org_group_id == member_id)
            | (ProjectGroupMember.source_project_id == member_id),
        )
    )
    log_event(
        db, entity_type="project_group", entity_id=group_id, action="member_removed", actor_id=current_user.id,
        project_id=project.id, detail={"member_id": str(member_id)},
    )
    # Resolve the real user(s) this removal can actually affect. `member_id`
    # may be a real user id, an org-group id, or a source-project id (see
    # this function's own docstring) — only the first can be checked
    # directly against get_effective_project_roles. Pre-existing gap fixed
    # here (found while building revoke_group_project_role's own equivalent
    # cleanup — see docs/decisions.md): for the other two kinds this used to
    # call get_effective_project_roles(db, member_id, ...) with a group/
    # project id standing in for a user id — since no real user has that id,
    # the check always vacuously "passed" and remove_subscriptions_and_
    # favorites_for_projects was called with that same non-user id, so a
    # nested-group or project-reference removal never actually cleaned up
    # the real former members' subscriptions/favourites. Resolves each
    # kind's real member set first instead, same pattern
    # revoke_group_project_role uses for its own group-level cleanup.
    if removed_member is None:
        affected_user_ids: set[UUID] = set()
    elif removed_member.user_id is not None:
        affected_user_ids = {removed_member.user_id}
    elif removed_member.org_group_id is not None:
        affected_user_ids = set(
            db.scalars(
                select(OrgGroupMember.user_id).where(
                    OrgGroupMember.org_group_id.in_(
                        {removed_member.org_group_id} | _descendant_org_group_ids(db, {removed_member.org_group_id})
                    ),
                    OrgGroupMember.user_id.is_not(None),
                )
            ).all()
        )
    else:
        affected_user_ids = _direct_project_member_ids_base(db, removed_member.source_project_id)
    # A group can grant a role alongside other direct/group roles a user
    # holds on the same project, so only clean up subscriptions/favourites
    # for someone this removal actually left with no remaining access — not
    # on every membership change.
    for affected_user_id in affected_user_ids:
        if not get_effective_project_roles(db, affected_user_id, project.id):
            engagement.remove_subscriptions_and_favorites_for_projects(db, affected_user_id, [project.id])
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
                project_id=project.id, actor_id=current_user.id,
            )
        db.commit()


@router.post("/{project_id}/group-roles", status_code=status.HTTP_204_NO_CONTENT)
def assign_group_project_role(
    project_id: UUID, payload: OrgGroupProjectRoleAssign,
    project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Assigns a direct (non-nested) project role to an organisation group —
    the group-level counterpart to `assign_project_role`, and a genuinely
    separate mechanism from nesting an org group inside a `ProjectGroup`
    (C-U-12, `add_project_group_member`): this creates the group's own
    independently-revocable `OrgGroupProjectRole` row, parallel to how
    `UserProjectRole` already works for a single user. Both mechanisms
    coexist by design — see `docs/decisions.md`'s identify/verify/remediate
    entry for this endpoint.

    Same cross-tenant check `add_project_group_member` already applies to
    its own `org_group_id` target: the group must belong to this project's
    own organisation, re-validated here rather than trusted from the
    frontend. Idempotent like `assign_project_role`: granting an
    already-held (group, project, role) triple is a silent no-op, not a
    409 — no audit event or commit happens on the no-op path, matching that
    endpoint's exact behavior.

    No per-member notification is sent (matching `add_project_group_member`'s
    own `org_group_id` path, not `assign_project_role`'s single-user path)
    — a group grant potentially affects many users at once, and this
    codebase's existing group-membership endpoints don't notify on
    group-level composition changes either.
    """
    org_group = db.get(OrgGroup, payload.org_group_id)
    if org_group is None or org_group.organization_id != project.organization_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "org_group_id must belong to the project's organisation.")
    existing = db.scalar(
        select(OrgGroupProjectRole).where(
            OrgGroupProjectRole.org_group_id == payload.org_group_id, OrgGroupProjectRole.project_id == project.id,
            OrgGroupProjectRole.role == payload.role,
        )
    )
    if existing is None:
        db.add(OrgGroupProjectRole(org_group_id=payload.org_group_id, project_id=project.id, role=payload.role))
        log_event(
            db, entity_type="org_group_project_role", entity_id=payload.org_group_id, action="granted",
            actor_id=current_user.id, project_id=project.id, detail={"role": payload.role.value},
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
            project_id=project.id, actor_id=current_user.id,
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


def _pending_invite_out(invite: PendingInvite) -> PendingInviteOut:
    """Shared status computation for both endpoints below — `status` is
    derived from `expires_at` at read time rather than stored, so it's
    always current."""
    return PendingInviteOut(
        id=invite.id,
        email=invite.email,
        role=invite.project_role,
        status="pending" if invite.expires_at > datetime.now(UTC) else "expired",
        created_at=invite.created_at,
        expires_at=invite.expires_at,
    )


def _get_pending_invite_in_project(db: Session, project_id: UUID, invite_id: UUID) -> PendingInvite:
    """Loads a `PendingInvite` and 404s unless it targets `project_id`.

    Without this check, a manager of *some* project (any project — that's
    all `require_project_manage` validates) could pass the `invite_id` of a
    *different* project's pending invite and resend it (rotating its
    token and re-sending its email), the same cross-project-boundary shape
    `_get_group_in_project` already guards against for group membership.
    """
    invite = db.get(PendingInvite, invite_id)
    if invite is None or invite.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invite not found.")
    return invite


@router.get("/{project_id}/pending-invites", response_model=list[PendingInviteOut])
def list_pending_project_invites(
    project_id: UUID,
    project: Project = Depends(require_project_manage),
    db: Session = Depends(get_db),
):
    """Lists this project's outstanding (unaccepted) `PendingInvite`s, most
    recent first — including already-expired ones, since an expired invite
    is exactly the case `resend_pending_project_invite` exists to fix.

    Standard (non-SSO) `PendingInvite` flow only (Phase 3 scope decision,
    docs/decisions.md) — an `sso_only` org's by-email invites are
    provisioned immediately via `services.invites.provision_sso_invite`
    and never create a row here. Gated the same as
    `assign_project_role_by_email`, the only endpoint that creates these
    rows, since listing/resending them is a continuation of that same
    capability.
    """
    invites_list = db.scalars(
        select(PendingInvite)
        .where(PendingInvite.project_id == project.id, PendingInvite.accepted_at.is_(None))
        .order_by(PendingInvite.created_at.desc())
    ).all()
    return [_pending_invite_out(invite) for invite in invites_list]


@router.post("/{project_id}/pending-invites/{invite_id}/resend", response_model=PendingInviteOut)
def resend_pending_project_invite(
    project_id: UUID, invite_id: UUID,
    project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Rotates the invite's token/`expires_at` and re-sends the signup-link
    email (`services.invites.resend_pending_invite`) — for "the original
    invite email never arrived" or reviving an invite that's since
    expired. Works in either case (still-pending or already-expired);
    only an already-*accepted* invite is rejected, since there's nothing
    left to resend once someone's redeemed it.
    """
    invite = _get_pending_invite_in_project(db, project.id, invite_id)
    if invite.accepted_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This invite has already been accepted.")
    org = db.get(Organization, project.organization_id)
    invites.resend_pending_invite(db, invite, organization=org, project=project)
    log_event(
        db, entity_type="pending_invite", entity_id=invite.id, action="invite_resent",
        actor_id=current_user.id, organization_id=org.id, project_id=project.id,
        detail={"email": invite.email},
    )
    db.commit()
    return _pending_invite_out(invite)


@router.delete("/{project_id}/roles/{user_id}/{role}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_project_role(
    project_id: UUID, user_id: UUID, role: ProjectRole,
    project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Revokes a direct project role, blocking removal of the last manager
    (C-U-08). Removing user_id's *direct* manager role is allowed even when
    they're currently the only effective manager, as long as they'd remain
    one via forward inheritance alone (`is_inherited_manager`) — otherwise
    this would over-block a safe removal for any manager who happens to
    also be a direct manager of a project they inherit that same role
    from."""
    if role == ProjectRole.PROJECT_MANAGER:
        lock_project_for_update(db, project.id)
        managers = get_effective_project_managers(db, project.id)
        if managers == {user_id} and not is_inherited_manager(db, user_id, project.id):
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
            actor_id=current_user.id,
        )
    # Only clean up subscriptions/favourites if the user has no other role
    # (direct or group-derived) left granting them access to this project.
    if not get_effective_project_roles(db, user_id, project.id):
        engagement.remove_subscriptions_and_favorites_for_projects(db, user_id, [project.id])
    db.commit()


@router.delete("/{project_id}/group-roles/{org_group_id}/{role}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_group_project_role(
    project_id: UUID, org_group_id: UUID, role: ProjectRole,
    project: Project = Depends(require_project_manage),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Revokes a direct (non-nested) project role from an organisation
    group — the group-level counterpart to `revoke_project_role`.

    C-U-08 guard shaped like `delete_project_group`'s (lock the project row,
    perform the delete, flush, then re-check `get_effective_project_
    managers` before commit) rather than `revoke_project_role`'s
    single-user pre-check (`managers == {user_id}`): revoking a group's
    role can remove effective access from every member of that group at
    once, not just one user, so there's no single user id to compare
    against. In practice this rarely actually trips for a *group* role
    specifically: `get_effective_project_managers`/`_direct_project_
    managers` deliberately never count any group-derived manager — neither
    the pre-existing nested-org-group mechanism (`ProjectGroup` +
    `ProjectGroupMember.org_group_id`) nor this new direct-grant mechanism
    — towards the C-U-08 "at least one manager" floor (see that function's
    own docstring: only direct `UserProjectRole` grants and a group's
    *direct user* members count as "concrete, individually accountable"
    managers). This guard is kept anyway, for defense-in-depth and
    consistency with `delete_project_group`/`update_project_group`, which
    apply the identical pattern for the identical reason: it still
    correctly catches the case where the project already had zero
    individually-accountable managers at the moment of this call. See
    docs/decisions.md's identify/verify/remediate entry for this endpoint
    for the full reasoning on why C-U-08 was not extended to count
    group-derived managers here — that would be a materially larger,
    separate change to a longstanding invariant, not something this PR
    introduces.
    """
    if role == ProjectRole.PROJECT_MANAGER:
        lock_project_for_update(db, project.id)
    db.execute(
        OrgGroupProjectRole.__table__.delete().where(
            OrgGroupProjectRole.org_group_id == org_group_id, OrgGroupProjectRole.project_id == project.id,
            OrgGroupProjectRole.role == role,
        )
    )
    db.flush()
    if role == ProjectRole.PROJECT_MANAGER and not get_effective_project_managers(db, project.id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A project must have at least one project manager.")
    log_event(
        db, entity_type="org_group_project_role", entity_id=org_group_id, action="revoked",
        actor_id=current_user.id, project_id=project.id, detail={"role": role.value},
    )
    # Clean up subscriptions/favourites for every member of this group (direct
    # or via a nested subgroup, same descendant-expansion `_direct_project_
    # role_holder_ids` uses to resolve this mechanism) who has no other role
    # left granting them access to this project — mirrors `revoke_project_
    # role`'s own per-user cleanup, extended to the (potentially many) users
    # a group-level revocation can affect at once.
    affected_user_ids = set(
        db.scalars(
            select(OrgGroupMember.user_id).where(
                OrgGroupMember.org_group_id.in_({org_group_id} | _descendant_org_group_ids(db, {org_group_id})),
                OrgGroupMember.user_id.is_not(None),
            )
        ).all()
    )
    for affected_user_id in affected_user_ids:
        if not get_effective_project_roles(db, affected_user_id, project.id):
            engagement.remove_subscriptions_and_favorites_for_projects(db, affected_user_id, [project.id])
    db.commit()
