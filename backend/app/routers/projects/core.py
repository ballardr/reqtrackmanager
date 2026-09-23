"""
Module: routers.projects.core

Core project CRUD (create/import/list/tree/get/patch), favouriting,
project-scoped file listing, export, terminology, the changes-over-time
timeline, and overview metrics (U-P-05) — plus `_accessible_project_ids`,
the shared project-visibility computation every other `routers.projects`
sub-module (and `routers.orgs`'s org overview-stats endpoint) builds on.

Split out of the former flat `routers/projects.py` (now the `projects`
package) as a pure code-organization refactor — see
`routers/projects/__init__.py`'s module docstring for the package layout.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, aliased

from app.database import get_db
from app.deps import get_current_user
from app.models.change_request import ChangeRequest, ReviewComment
from app.models.enums import (
    ChangeRequestStatus,
    OrgRole,
    ProjectRole,
    ProjectRoleInheritanceMode,
    ProjectVisibility,
    ReviewTargetType,
    StageStatus,
)
from app.models.file import CommentFile, FileAsset, RequirementActionFile, RequirementFile
from app.models.organization import Organization, UserOrgRole
from app.models.project import (
    FavoriteProject,
    OrgGroupProjectRole,
    Project,
    ProjectGroup,
    ProjectGroupMember,
    ProjectGroupRole,
    ProjectMemberSource,
    ProjectStage,
    UserProjectRole,
)
from app.models.project_status import ProjectStatusDefinition
from app.models.requirement import Baseline, BaselineItem, Requirement, RequirementVersion
from app.models.requirement_action import RequirementAction
from app.models.user import User
from app.modules.registry import run_on_project_created_hooks
from app.schemas.changes import ChangeEntryOut
from app.schemas.file import FileAssetOut, ProjectFileOut
from app.schemas.project import (
    ProjectAncestorOut,
    ProjectCreate,
    ProjectImportResult,
    ProjectListItemOut,
    ProjectMetricsOut,
    ProjectOut,
    ProjectTreeNodeOut,
    ProjectUpdate,
    StageProgressOut,
    TerminologyUpdate,
)
from app.services.audit import log_event
from app.services.changes import get_project_changes
from app.services.definitions import get_default_project_status_id, seed_action_types
from app.services.downloads import filename_safe
from app.services.project_export import build_project_bundle, import_project_bundle
from app.services.project_hierarchy import build_project_tree, would_create_project_cycle
from app.services.rbac import (
    can_manage_project_settings,
    check_pat_scope,
    get_effective_org_roles,
    get_effective_project_managers,
    get_effective_project_roles,
    get_user_org_group_ids,
    is_org_admin,
    lock_project_for_update,
    require_project_manage,
    require_project_view,
    require_project_view_or_manage,
)
from app.services.templates import clone_project

router = APIRouter(tags=["projects-core"])

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


def _require_user_in_org(db: Session, user_id: UUID, organization_id: UUID) -> None:
    """C-U-02: "All Project users, must be an organisation user." Raises 400
    if `user_id` holds no role at all in `organization_id`, so a project
    manager can't grant project-level access to someone outside the
    organisation. Shared by `routers.projects.groups` and `.roles`.
    """
    if not get_effective_org_roles(db, user_id, organization_id):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "The user must be a member of this project's organisation first."
        )


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
    # Generic module-contributed project-creation reaction (e.g.
    # Compliance's Phase 20 reconciliation of `applies_to_all_projects`
    # standards) — this core router never imports a specific module; see
    # `ModuleDefinition.on_project_created`'s own docstring for why
    # project-creation time, not a module-enable hook, is where this has to
    # run.
    run_on_project_created_hooks(db, project, current_user.id)

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
                allow_member_change_requests=p.allow_member_change_requests,
                require_change_request_for_approved_links=p.require_change_request_for_approved_links,
                exempt_from_org_link_lock=p.exempt_from_org_link_lock, allow_ai_approvals=p.allow_ai_approvals,
                visibility=p.visibility,
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
    # requirements (via untyped `ArtefactLink` rows), so it has no single
    # owning requirement to attribute the file to.
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
    if payload.require_change_request_for_approved_links is not None:
        project.require_change_request_for_approved_links = payload.require_change_request_for_approved_links
    if payload.exempt_from_org_link_lock is not None:
        project.exempt_from_org_link_lock = payload.exempt_from_org_link_lock
    if payload.allow_ai_approvals is not None:
        # AI approval via MCP (docs/decisions.md) — project half of the
        # two-level opt-in gate; see Project.allow_ai_approvals's docstring.
        # The frontend requires an explicit acknowledgment dialog before
        # ever sending `allow_ai_approvals=true`, same as the org-level
        # counterpart in update_advanced_settings.
        project.allow_ai_approvals = payload.allow_ai_approvals
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
