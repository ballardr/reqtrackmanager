"""
Module: routers.projects.hierarchy

Parent/child project hierarchy (ancestors/children breadcrumb, detach),
the member-source mechanism (`models.project.ProjectMemberSource`), and
the access-inheritance visibility surfaces built on both: effective
members with provenance, and the "materialize inherited access" endpoints
that snapshot an inherited role onto a direct grant (decisions 9/10/11 in
docs/decisions.md).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models.enums import OrgRole, ProjectRole
from app.models.module_role import UserModuleRole
from app.models.organization import Organization, OrgGroup
from app.models.project import FavoriteProject, OrgGroupProjectRole, Project, ProjectMemberSource, ProjectStage, UserProjectRole
from app.models.user import User
from app.modules.registry import list_enabled_module_roles
from app.routers.projects.core import _accessible_project_ids
from app.schemas.org import ModuleRoleGrantOut
from app.schemas.project import (
    EffectiveMemberOut,
    MaterializeResultOut,
    ProjectAncestorOut,
    ProjectListItemOut,
    ProjectMemberSourceAdd,
    ProjectMemberSourceOut,
)
from app.services.audit import log_event
from app.services.project_hierarchy import get_ancestor_chain
from app.services.rbac import (
    get_effective_org_roles,
    get_effective_project_managers,
    get_effective_project_members_with_provenance,
    get_effective_project_roles,
    get_group_inherited_project_roles,
    is_org_admin,
    lock_project_for_update,
    require_project_manage,
    require_project_view,
    require_project_view_or_manage,
)

router = APIRouter(tags=["projects-hierarchy"])

_ROLE_RANK = {
    ProjectRole.MEMBER: 0, ProjectRole.STAKEHOLDER: 1,
    ProjectRole.PROJECT_ADMINISTRATOR: 1, ProjectRole.PROJECT_MANAGER: 2,
}


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
                allow_member_change_requests=c.allow_member_change_requests,
                require_change_request_for_approved_links=c.require_change_request_for_approved_links,
                exempt_from_org_link_lock=c.exempt_from_org_link_lock, allow_ai_approvals=c.allow_ai_approvals,
                visibility=c.visibility,
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

    # Module system Phase 2: this project's module-contributed role grants,
    # filtered to currently-*enabled* modules only (see `ModuleRoleGrantOut`'s
    # docstring for the "filter, don't delete" rationale) — computed once
    # for the whole response, then attached per member below.
    enabled_project_role_keys = {
        (module_key, role.role_key)
        for module_key, role in list_enabled_module_roles(db, project.organization_id, "project")
    }
    module_roles_by_user: dict[UUID, list[ModuleRoleGrantOut]] = {}
    if enabled_project_role_keys:
        module_role_rows = db.execute(
            select(UserModuleRole.user_id, UserModuleRole.module_key, UserModuleRole.role_key).where(
                UserModuleRole.project_id == project_id
            )
        ).all()
        for user_id, module_key, role_key in module_role_rows:
            if (module_key, role_key) in enabled_project_role_keys:
                module_roles_by_user.setdefault(user_id, []).append(
                    ModuleRoleGrantOut(module_key=module_key, role_key=role_key)
                )

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
                module_roles=module_roles_by_user.get(user_id, []),
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
