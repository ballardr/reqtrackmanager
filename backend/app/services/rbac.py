"""
Module: services.rbac

Computes a user's effective organisation and project roles and exposes
FastAPI dependencies that enforce them (C-U-01, C-U-03).

Effective project role resolution combines six sources:
    1. Direct per-user role assignments (UserProjectRole).
    2. Membership in a project group (ProjectGroupMember with user_id set).
    3. Membership in an org group that is itself nested inside a project
       group (ProjectGroupMember with org_group_id set, resolved via
       OrgGroupMember) — transitively: a user who's only a *direct* member
       of a sub-group counts as a member of every ancestor group too, via
       OrgGroupMember's own self-nesting (OrgGroupMember.member_org_group_id,
       a distinct, fully transitive relationship from this one-hop
       org-group-in-project-group nesting — see `_ancestor_org_group_ids`/
       `_descendant_org_group_ids` and docs/decisions.md for why the two
       nesting relationships resolve differently).
    4. ProjectVisibility.ORG_WIDE: baseline MEMBER access for any user who
       holds any role in the project's own organisation, with no explicit
       assignment needed. Deliberately narrower than the other five
       sources — never implies PROJECT_MANAGER/ADMINISTRATOR/STAKEHOLDER,
       and deliberately not folded into `get_project_member_user_ids`
       (broadcast notification targeting, C-N-01) or
       `can_manage_project_settings` — org-wide visibility is a read grant,
       not a "this is now like being a real project member" shortcut.
    5. Forward (parent -> child) inheritance: `Project.role_inheritance_mode`
       — walks the parent chain, applying each hop's own mode
       (MIRROR_ALL/MIRROR_ROLE/MEMBER_ONLY) to that ancestor's *direct*
       roles (sources 1-4 above, computed at that ancestor — never an
       ancestor's own inherited roles), breaking at the first ancestor
       whose mode is NONE. Unlike ORG_WIDE, this is a real, potentially
       elevated grant (MIRROR_ALL/MIRROR_ROLE can convey PROJECT_MANAGER)
       and *is* folded into `get_project_member_user_ids` — see decision 5
       in docs/decisions.md's "Hierarchical projects" entry.
    6. Member-source (child -> parent) inheritance: `ProjectMemberSource`,
       an explicit list a project maintains of which of its own direct
       children it consumes members from, authorized entirely by the
       *parent's* own manage rights (not the child's) — see
       `models.project.ProjectMemberSource`'s docstring for why. Always
       grants baseline MEMBER only, walking down through a chain of
       explicit lists (each hop requires that hop's own list to name the
       next one down). Also folded into `get_project_member_user_ids`.

Sources 5 and 6 are kept fully decoupled from each other: the forward walk
only ever reads an ancestor's *direct* roles, and the member-source walk
only ever reads a descendant's *direct* roles (plus, recursively, whatever
that descendant has itself separately consumed via its own list) — neither
ever reads the other mechanism's result. This prevents a sibling-project
leak (a member-source-listed child's users ending up visible to an
unrelated sibling via the parent's own forward mirroring) and avoids any
mutual-recursion hazard between the two. See docs/decisions.md.

A project manager role implies project administrator and stakeholder
capabilities (C-U-03 clarification: "Project Managers can also perform all
project administrator and stakeholder tasks"). Holding any project role
implies baseline member-level view access. This normalization is applied
once, over the fully-combined set from all six sources — so e.g. a child's
own direct STAKEHOLDER role plus a forward-inherited PROJECT_MANAGER role
still correctly implies PROJECT_ADMINISTRATOR on the child.

Organisation admins do not automatically gain project content access
(C-U-01 clarification: "No Project access is guaranteed from any roles apart
from org admin being able to manage project settings") — that specific,
narrow capability is checked separately via `can_manage_project_settings`
rather than folded into the general project role set. Neither inheritance
mechanism changes this: both only ever propagate project-level roles
between projects, never touch org-role resolution.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models.enums import OrgRole, ProjectRole, ProjectRoleInheritanceMode, ProjectVisibility
from app.models.organization import Organization, OrgGroup, OrgGroupMember, UserOrgRole
from app.models.project import Project, ProjectGroup, ProjectGroupMember, ProjectMemberSource, UserProjectRole
from app.models.user import User

# Defensive circuit-breaker for the forward-inheritance and member-source
# walks below — matches `_ORG_GROUP_CLOSURE_ITERATION_CAP`'s own rationale:
# should never actually trip (project trees are realistically small), exists
# purely to bound worst-case query cost against a pathological tree.
_PROJECT_INHERITANCE_ITERATION_CAP = 1000


def check_pat_scope(request: Request, organization_id: UUID) -> None:
    """Enforces a Personal Access Token's org scope, on top of the caller's
    real RBAC roles (checked separately by each dependency below).

    `request.state.pat_allowed_org_ids` is only ever set by
    `deps._resolve_user_from_pat` — an ordinary session-JWT request never
    has the attribute at all, so this is a no-op (zero extra queries) for
    the overwhelming majority of requests. When it *is* set, a PAT is
    restricted to acting only within the orgs its creator chose for it,
    regardless of what org/project roles the underlying user otherwise
    holds — this is a restriction layered on top of RBAC, never a grant
    beyond it.

    Raises:
        HTTPException: 403 if the request was authenticated via a PAT not
            scoped to `organization_id`.
    """
    allowed = getattr(request.state, "pat_allowed_org_ids", None)
    if allowed is not None and organization_id not in allowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This access token is not scoped to this organisation.")


def check_pat_project_scope(request: Request, project_id: UUID) -> None:
    """Enforces a Personal Access Token's optional *project*-level scope,
    on top of `check_pat_scope`'s org-level check — a further restriction
    a token's creator can optionally add (`PersonalAccessToken.
    allowed_project_ids`), never a grant beyond the org scope or the
    user's real RBAC roles.

    `request.state.pat_allowed_project_ids` is `None` for a token with no
    project restriction (the default) or for a non-PAT request — a no-op
    in both cases, same shape as `check_pat_scope`.

    Raises:
        HTTPException: 403 if the request was authenticated via a PAT
            restricted to a set of projects that doesn't include
            `project_id`.
    """
    allowed = getattr(request.state, "pat_allowed_project_ids", None)
    if allowed is not None and project_id not in allowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This access token is not scoped to this project.")


def is_org_active(db: Session, organization_id: UUID) -> bool:
    """Boolean form of the check `_require_org_active` raises on. Exists for
    call sites that can't raise an `HTTPException` and need to translate
    "is this org disabled" into their own failure signal instead — e.g. the
    WebSocket router, which closes the connection with its own code rather
    than propagating an HTTP response."""
    return bool(db.scalar(select(Organization.is_active).where(Organization.id == organization_id)))


def _require_org_active(db: Session, organization_id: UUID) -> None:
    """Blocks every org/project-scoped request against a disabled
    organisation (`Organization.is_active`), regardless of the caller's
    role — a suspended org (e.g. non-payment) locks out even its own
    admins, not just ordinary members. Deliberately checked before the
    role check in every dependency below, so the failure reason is
    specific ("this org is disabled") rather than a generic permissions
    error. Only the disable/enable toggle endpoints themselves
    (`require_server_admin`, not any of these factories) bypass this.

    Every access path that reads org/project-scoped content must be gated
    by this (directly, or via one of the five dependency factories below)
    — a hardening-review pass found and fixed three call sites that read
    such content through a different mechanism and had silently never been
    wired to it: the WebSocket endpoint (`routers/ws.py`, its own inline
    auth check), the file-download endpoint (`routers/files.py`, authorizes
    via the raw `get_effective_*_roles` helpers rather than a `require_*`
    dependency, since it needs `?token=` query-param support those don't
    offer), and the cross-project reviews-due listing (`services/reviews.py`,
    which has no single `project_id`/`organization_id` to hang a dependency
    off in the first place). See docs/decisions.md's "Organisation disable
    and hard delete" hardening-pass follow-up for the full list.

    Raises:
        HTTPException: 403 if the organisation is disabled or doesn't exist
            (a nonexistent org is treated the same as a disabled one here —
            the more specific 404s already live on the endpoints that
            create/read organisations directly).
    """
    if not is_org_active(db, organization_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This organisation has been disabled.")


def _require_org_2fa(db: Session, organization_id: UUID, user: User) -> None:
    """Blocks org/project-scoped requests against an organisation with
    `Organization.require_2fa` set, for any caller without
    `User.is_2fa_enabled` — same bluntness as `_require_org_active`
    (applies to the org's own admins too), but with a self-service way out:
    `/auth/2fa/enroll`/`confirm` aren't org-scoped, so a blocked user can
    enroll immediately and regain access without an admin's help. Checked
    everywhere `_require_org_active` is, right after it, so a disabled org
    still produces the more specific "disabled" message rather than this
    one when both are true.

    Raises:
        HTTPException: 403 if the org requires 2FA and the caller doesn't
            have it enabled.
    """
    requires_2fa = bool(db.scalar(select(Organization.require_2fa).where(Organization.id == organization_id)))
    if requires_2fa and not user.is_2fa_enabled:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "This organisation requires two-factor authentication. Enable it in Preferences to continue.",
        )


def get_effective_org_roles(db: Session, user_id: UUID, organization_id: UUID) -> set[OrgRole]:
    """Returns the set of organisation roles a user holds in an organisation."""
    rows = db.scalars(
        select(UserOrgRole.role).where(
            UserOrgRole.user_id == user_id, UserOrgRole.organization_id == organization_id
        )
    ).all()
    return {OrgRole(r) for r in rows}


def is_org_admin(db: Session, user_id: UUID, organization_id: UUID) -> bool:
    """Returns True if the user holds the org_admin role in the organisation."""
    return OrgRole.ORG_ADMIN in get_effective_org_roles(db, user_id, organization_id)


def get_user_org_group_ids(db: Session, user_id: UUID, organization_id: UUID) -> tuple[set[UUID], set[UUID]]:
    """Returns `(direct_group_ids, inherited_group_ids)` — org groups the
    user is a direct member of in `organization_id`, and every additional
    group they're an effective member of transitively via nesting (see
    `_ancestor_org_group_ids`). Used by the self-service "my groups" view
    (`routers/auth.py::read_my_memberships`) and the server-admin
    access-review directory.

    Hardening-review finding: `_ancestor_org_group_ids` itself walks
    `OrgGroupMember` with no organisation filter (nesting is only ever
    same-org at write time, per `routers.orgs.add_org_group_member`'s
    cross-org rejection, so it should never actually cross a tenant
    boundary) — but both callers of this function place the result
    directly under `organization_id` in their response (a membership
    entry in `read_my_memberships`, a name list in the access-review
    directory) with no downstream re-check, unlike
    `get_effective_project_roles`'s equivalent nested-group resolution,
    which re-joins on `OrgGroup.organization_id` as defense in depth
    even though the same write-time check already applies there. Filtered
    here too, for the same reason: a bug elsewhere that ever let a
    cross-org edge through should never surface another organisation's
    group name under this one.
    """
    direct = set(
        db.scalars(
            select(OrgGroupMember.org_group_id)
            .join(OrgGroup, OrgGroup.id == OrgGroupMember.org_group_id)
            .where(OrgGroupMember.user_id == user_id, OrgGroup.organization_id == organization_id)
        ).all()
    )
    ancestors = _ancestor_org_group_ids(db, direct)
    if ancestors:
        ancestors = set(
            db.scalars(
                select(OrgGroup.id).where(OrgGroup.id.in_(ancestors), OrgGroup.organization_id == organization_id)
            ).all()
        )
    inherited = ancestors - direct
    return direct, inherited


def can_manage_project_settings(db: Session, user: User, project: Project) -> bool:
    """Whether the user may manage project setup, stages, components, categories.

    True for project administrators/managers, and for organisation admins of
    the project's organisation (C-U-01 clarification).
    """
    if is_org_admin(db, user.id, project.organization_id):
        return True
    roles = get_effective_project_roles(db, user.id, project.id)
    return bool(roles & {ProjectRole.PROJECT_MANAGER, ProjectRole.PROJECT_ADMINISTRATOR})


_ORG_GROUP_CLOSURE_ITERATION_CAP = 1000


def _ancestor_org_group_ids(db: Session, group_ids: set[UUID]) -> set[UUID]:
    """Returns every org group that (transitively) contains any group in
    `group_ids` as a nested member — walks "upward" through
    `OrgGroupMember.member_org_group_id` to find containing groups.

    An iterative BFS closure rather than a recursive SQL CTE, matching this
    module's existing style of explicit, readable Python-side set
    operations (see `get_effective_project_roles`'s own two-query-then-union
    shape) — org-group counts per organisation are small, so the extra
    round-trips are a non-issue. The iteration cap is defense in depth only:
    cycles are rejected at write time (`routers.orgs.add_org_group_member`),
    so this should never actually trip.
    """
    visited: set[UUID] = set()
    frontier = set(group_ids)
    iterations = 0
    while frontier and iterations < _ORG_GROUP_CLOSURE_ITERATION_CAP:
        iterations += 1
        parents = set(
            db.scalars(select(OrgGroupMember.org_group_id).where(OrgGroupMember.member_org_group_id.in_(frontier))).all()
        )
        new = parents - visited
        if not new:
            break
        visited.update(new)
        frontier = new
    return visited


def _descendant_org_group_ids(db: Session, group_ids: set[UUID]) -> set[UUID]:
    """Returns every org group nested (transitively) inside any group in
    `group_ids` — the inverse of `_ancestor_org_group_ids`, walking
    "downward" through `OrgGroupMember.member_org_group_id`."""
    visited: set[UUID] = set()
    frontier = set(group_ids)
    iterations = 0
    while frontier and iterations < _ORG_GROUP_CLOSURE_ITERATION_CAP:
        iterations += 1
        children = set(
            db.scalars(
                select(OrgGroupMember.member_org_group_id).where(
                    OrgGroupMember.org_group_id.in_(frontier), OrgGroupMember.member_org_group_id.is_not(None)
                )
            ).all()
        )
        new = children - visited
        if not new:
            break
        visited.update(new)
        frontier = new
    return visited


def would_create_org_group_cycle(db: Session, parent_group_id: UUID, child_group_id: UUID) -> bool:
    """True if nesting `child_group_id` as a member of `parent_group_id`
    would create a cycle — either they're the same group (self-nesting), or
    `parent_group_id` is already reachable as a descendant of
    `child_group_id` (i.e. `child_group_id` already, transitively,
    contains `parent_group_id`, so adding the reverse edge would close a
    loop). Checked at write time in `routers.orgs.add_org_group_member`.
    """
    if parent_group_id == child_group_id:
        return True
    return parent_group_id in _descendant_org_group_ids(db, {child_group_id})


def _direct_effective_project_roles(db: Session, user_id: UUID, project_id: UUID) -> set[ProjectRole]:
    """Returns the roles a user holds on `project_id` itself — sources 1-4
    of the module docstring (direct, direct group, nested-org-group,
    org-wide visibility) — with no cross-project inheritance and no
    PROJECT_MANAGER-implies-ADMINISTRATOR/STAKEHOLDER or
    any-role-implies-MEMBER normalization applied (`_normalize` does that,
    once, over the fully-combined result). This is the building block both
    inheritance mechanisms use to read an *other* project's roles without
    ever reading that project's own already-inherited results — see the
    module docstring's decoupling note.
    """
    roles: set[ProjectRole] = set()

    direct = db.scalars(
        select(UserProjectRole.role).where(
            UserProjectRole.user_id == user_id, UserProjectRole.project_id == project_id
        )
    ).all()
    roles.update(ProjectRole(r) for r in direct)

    direct_group_roles = db.scalars(
        select(ProjectGroup.role)
        .join(ProjectGroupMember, ProjectGroupMember.project_group_id == ProjectGroup.id)
        .where(ProjectGroup.project_id == project_id, ProjectGroupMember.user_id == user_id)
    ).all()
    roles.update(ProjectRole(r) for r in direct_group_roles)

    direct_org_group_ids = set(
        db.scalars(select(OrgGroupMember.org_group_id).where(OrgGroupMember.user_id == user_id)).all()
    )
    user_org_group_ids = direct_org_group_ids | _ancestor_org_group_ids(db, direct_org_group_ids)
    if user_org_group_ids:
        # Defense in depth: even though endpoints reject nesting an org
        # group from a different organisation into a project group at
        # write time, also constrain the read-side resolution to org
        # groups belonging to the project's own organisation, so a
        # cross-tenant row (however it got there) can never grant a role.
        nested_group_roles = db.scalars(
            select(ProjectGroup.role)
            .join(ProjectGroupMember, ProjectGroupMember.project_group_id == ProjectGroup.id)
            .join(Project, Project.id == ProjectGroup.project_id)
            .join(OrgGroup, OrgGroup.id == ProjectGroupMember.org_group_id)
            .where(
                ProjectGroup.project_id == project_id,
                ProjectGroupMember.org_group_id.in_(user_org_group_ids),
                OrgGroup.organization_id == Project.organization_id,
            )
        ).all()
        roles.update(ProjectRole(r) for r in nested_group_roles)

    project_row = db.execute(
        select(Project.visibility, Project.organization_id).where(Project.id == project_id)
    ).first()
    if project_row is not None:
        visibility, organization_id = project_row
        if visibility == ProjectVisibility.ORG_WIDE and get_effective_org_roles(db, user_id, organization_id):
            roles.add(ProjectRole.MEMBER)

    return roles


def _normalize(roles: set[ProjectRole]) -> set[ProjectRole]:
    """Applies the PROJECT_MANAGER-implies-ADMINISTRATOR/STAKEHOLDER and
    any-role-implies-MEMBER rules — see module docstring."""
    if ProjectRole.PROJECT_MANAGER in roles:
        roles.add(ProjectRole.PROJECT_ADMINISTRATOR)
        roles.add(ProjectRole.STAKEHOLDER)
    if roles:
        roles.add(ProjectRole.MEMBER)
    return roles


def _direct_project_member_ids(db: Session, project_id: UUID) -> set[UUID]:
    """Set-returning sibling of `_direct_effective_project_roles`, minus its
    `ProjectVisibility.ORG_WIDE` source: every user with a direct, group, or
    nested-org-group role on `project_id` itself, no inheritance.

    Deliberately excludes `ORG_WIDE`'s implicit baseline grant — the same
    exclusion `get_project_member_user_ids` already applies today (see
    module docstring), preserved here rather than reintroduced through a
    side channel: if this included `ORG_WIDE`, an org-wide-visible ancestor
    would flow its *entire organisation's* membership through forward
    inheritance or the member-source mechanism into every notification and
    every "does this descendant have a real member" check, exactly the mass
    side effect the existing exclusion exists to prevent. `_forward_
    inherited_roles` (the per-user, `get_effective_project_roles` path)
    correctly keeps using `_direct_effective_project_roles`, which *does*
    include `ORG_WIDE` — access resolution and notification-membership
    resolution are different questions with different existing answers, and
    this helper is only for the latter (used by `get_project_member_user_ids`
    and both member-source helpers).
    """
    user_ids: set[UUID] = set(
        db.scalars(select(UserProjectRole.user_id).where(UserProjectRole.project_id == project_id)).all()
    )
    user_ids.update(
        db.scalars(
            select(ProjectGroupMember.user_id)
            .join(ProjectGroup, ProjectGroup.id == ProjectGroupMember.project_group_id)
            .where(ProjectGroup.project_id == project_id, ProjectGroupMember.user_id.is_not(None))
        ).all()
    )
    nested_org_group_ids = set(
        db.scalars(
            select(ProjectGroupMember.org_group_id)
            .join(ProjectGroup, ProjectGroup.id == ProjectGroupMember.project_group_id)
            .where(ProjectGroup.project_id == project_id, ProjectGroupMember.org_group_id.is_not(None))
        ).all()
    )
    if nested_org_group_ids:
        all_org_group_ids = nested_org_group_ids | _descendant_org_group_ids(db, nested_org_group_ids)
        user_ids.update(
            db.scalars(
                select(OrgGroupMember.user_id).where(
                    OrgGroupMember.org_group_id.in_(all_org_group_ids), OrgGroupMember.user_id.is_not(None)
                )
            ).all()
        )
    return user_ids


def _direct_project_role_holder_ids(db: Session, project_id: UUID, role: ProjectRole) -> set[UUID]:
    """Set-returning "who holds exactly `role` directly on `project_id`",
    including nested-org-group-derived holders (unlike the pre-existing
    `get_project_users_by_role`, which deliberately excludes that source for
    a different purpose — notification-role-targeting, not inheritance).
    Used by `_forward_contributed_member_ids`'s `MIRROR_ROLE` case, so a
    `MIRROR_ROLE`-filtered contribution only ever includes users who
    actually hold the filtered role on the ancestor, matching `_forward_
    inherited_roles`'s per-user `role_inheritance_filter_role in
    parent_roles` check exactly — unioning in every member regardless of
    their actual role would notify people who gain no access to the child
    at all.
    """
    user_ids: set[UUID] = set(
        db.scalars(
            select(UserProjectRole.user_id).where(
                UserProjectRole.project_id == project_id, UserProjectRole.role == role
            )
        ).all()
    )
    user_ids.update(
        db.scalars(
            select(ProjectGroupMember.user_id)
            .join(ProjectGroup, ProjectGroup.id == ProjectGroupMember.project_group_id)
            .where(
                ProjectGroup.project_id == project_id, ProjectGroup.role == role,
                ProjectGroupMember.user_id.is_not(None),
            )
        ).all()
    )
    nested_org_group_ids = set(
        db.scalars(
            select(ProjectGroupMember.org_group_id)
            .join(ProjectGroup, ProjectGroup.id == ProjectGroupMember.project_group_id)
            .where(
                ProjectGroup.project_id == project_id, ProjectGroup.role == role,
                ProjectGroupMember.org_group_id.is_not(None),
            )
        ).all()
    )
    if nested_org_group_ids:
        all_org_group_ids = nested_org_group_ids | _descendant_org_group_ids(db, nested_org_group_ids)
        user_ids.update(
            db.scalars(
                select(OrgGroupMember.user_id).where(
                    OrgGroupMember.org_group_id.in_(all_org_group_ids), OrgGroupMember.user_id.is_not(None)
                )
            ).all()
        )
    return user_ids


def _forward_contributed_member_ids(db: Session, project_id: UUID) -> set[UUID]:
    """Set-returning sibling of `_forward_inherited_roles`, for
    `get_project_member_user_ids`: walks `project_id`'s parent chain
    upward exactly the same way (breaking at the first ancestor whose mode
    is NONE), applying each hop's own mode — `MIRROR_ALL`/`MEMBER_ONLY`
    union in the ancestor's full `_direct_project_member_ids` (not
    `_direct_effective_project_roles`, so `ORG_WIDE` stays excluded — see
    that helper's docstring), `MIRROR_ROLE` unions in only the holders of
    the specific filtered role (`_direct_project_role_holder_ids`) — for
    notification purposes, any forward-inherited grant counts as real
    membership (decision 5 in docs/decisions.md), but only for users who
    actually gain something from it.
    """
    contributed: set[UUID] = set()
    visited: set[UUID] = {project_id}
    current_id = project_id
    iterations = 0
    while iterations < _PROJECT_INHERITANCE_ITERATION_CAP:
        iterations += 1
        row = db.execute(
            select(Project.parent_project_id, Project.role_inheritance_mode, Project.role_inheritance_filter_role)
            .where(Project.id == current_id)
        ).first()
        if row is None or row.role_inheritance_mode == ProjectRoleInheritanceMode.NONE or row.parent_project_id is None:
            break
        parent_id = row.parent_project_id
        if parent_id in visited:
            break
        visited.add(parent_id)
        if row.role_inheritance_mode == ProjectRoleInheritanceMode.MIRROR_ROLE:
            if row.role_inheritance_filter_role is not None:
                contributed |= _direct_project_role_holder_ids(db, parent_id, row.role_inheritance_filter_role)
        else:
            contributed |= _direct_project_member_ids(db, parent_id)
        current_id = parent_id
    return contributed


def _forward_inherited_roles(db: Session, user_id: UUID, project_id: UUID) -> set[ProjectRole]:
    """Walks `project_id`'s parent chain upward, applying each hop's own
    `role_inheritance_mode` to that ancestor's *direct* roles (never an
    ancestor's own inherited roles) — source 5 of the module docstring.
    Breaks at the first ancestor whose mode is NONE, or that has no parent.
    Iterative, visited-set guarded — never recursive, never unbounded.
    """
    inherited: set[ProjectRole] = set()
    visited: set[UUID] = {project_id}
    current_id = project_id
    iterations = 0
    while iterations < _PROJECT_INHERITANCE_ITERATION_CAP:
        iterations += 1
        row = db.execute(
            select(Project.parent_project_id, Project.role_inheritance_mode, Project.role_inheritance_filter_role)
            .where(Project.id == current_id)
        ).first()
        if row is None or row.role_inheritance_mode == ProjectRoleInheritanceMode.NONE or row.parent_project_id is None:
            break
        parent_id = row.parent_project_id
        if parent_id in visited:
            break
        visited.add(parent_id)
        parent_roles = _direct_effective_project_roles(db, user_id, parent_id)
        if row.role_inheritance_mode == ProjectRoleInheritanceMode.MIRROR_ALL:
            inherited |= parent_roles
        elif row.role_inheritance_mode == ProjectRoleInheritanceMode.MIRROR_ROLE:
            if row.role_inheritance_filter_role is not None and row.role_inheritance_filter_role in parent_roles:
                inherited.add(row.role_inheritance_filter_role)
        elif row.role_inheritance_mode == ProjectRoleInheritanceMode.MEMBER_ONLY:
            if parent_roles:
                inherited.add(ProjectRole.MEMBER)
        current_id = parent_id
    return inherited


def _member_source_frontier(db: Session, frontier: set[UUID]) -> set[UUID]:
    """One BFS layer for the member-source (reverse) walk: every
    `source_project_id` listed by any project in `frontier`, live-
    revalidated against `Project.parent_project_id` (per
    `ProjectMemberSource`'s docstring — a row whose `source_project_id` was
    reparented elsewhere is inert). Shared by `_has_member_source_access`/
    `_member_source_contributed_user_ids` below.
    """
    if not frontier:
        return set()
    return set(
        db.execute(
            select(ProjectMemberSource.source_project_id)
            .join(Project, Project.id == ProjectMemberSource.source_project_id)
            .where(
                ProjectMemberSource.project_id.in_(frontier),
                Project.parent_project_id == ProjectMemberSource.project_id,
            )
        ).scalars().all()
    )


def _has_member_source_access(db: Session, user_id: UUID, project_id: UUID) -> bool:
    """True if `user_id` should get member-source-derived `MEMBER` access on
    `project_id` — source 6 of the module docstring. Walks *down* through
    `project_id`'s own `ProjectMemberSource` list, breadth-first: true if
    the user has any *direct* role on a listed child, else continues into
    that child's own member-source list (so a grandchild's members reach
    the grandparent only if both the grandchild and the intermediate child
    have opted in via their own lists). Never reads a descendant's
    forward-inherited roles — only its direct ones — per the module
    docstring's decoupling note.

    Uses `_direct_project_member_ids` (not `_direct_effective_project_roles`)
    for the same reason that helper's own docstring gives:
    `ProjectVisibility.ORG_WIDE`'s baseline grant must stay excluded here too.
    An earlier version of this function checked
    `_direct_effective_project_roles(db, user_id, source_id)` directly, which
    *does* include the ORG_WIDE baseline — so listing an ORG_WIDE-visible
    child as a member source silently granted every user in the
    organisation real `MEMBER` access to the parent (a genuine RBAC escalation:
    `get_effective_project_roles` is the live authorization gate behind
    `require_project_view`, not just a notification-targeting helper), exactly
    the mass side effect `_direct_project_member_ids`'s own docstring already
    warned against reintroducing "through a side channel". Fixed to match
    `_member_source_contributed_user_ids`'s sibling (bulk) resolution, which
    already excluded ORG_WIDE correctly.

    Iterative (not recursive) and capped at
    `_PROJECT_INHERITANCE_ITERATION_CAP` layers, matching every other
    unlimited-depth tree walk in this module — a project tree several
    hundred levels deep would otherwise risk a Python `RecursionError`
    here, since this runs on essentially every RBAC check.
    """
    visited: set[UUID] = {project_id}
    frontier: set[UUID] = {project_id}
    iterations = 0
    while frontier and iterations < _PROJECT_INHERITANCE_ITERATION_CAP:
        iterations += 1
        new = _member_source_frontier(db, frontier) - visited
        if not new:
            break
        for source_id in new:
            if user_id in _direct_project_member_ids(db, source_id):
                return True
        visited |= new
        frontier = new
    return False


def _member_source_contributed_user_ids(db: Session, project_id: UUID) -> set[UUID]:
    """Set-returning sibling of `_has_member_source_access`, for
    `get_project_member_user_ids`/`get_project_users_by_role` — see that
    function's docstring for the iteration cap rationale."""
    contributed: set[UUID] = set()
    visited: set[UUID] = {project_id}
    frontier: set[UUID] = {project_id}
    iterations = 0
    while frontier and iterations < _PROJECT_INHERITANCE_ITERATION_CAP:
        iterations += 1
        new = _member_source_frontier(db, frontier) - visited
        if not new:
            break
        for source_id in new:
            contributed |= _direct_project_member_ids(db, source_id)
        visited |= new
        frontier = new
    return contributed


def get_effective_project_roles(db: Session, user_id: UUID, project_id: UUID) -> set[ProjectRole]:
    """Returns the set of project roles a user effectively holds.

    See module docstring for the resolution algorithm (six sources: direct,
    direct group, nested-org-group, org-wide visibility, forward
    inheritance, member-source inheritance).
    """
    roles = _direct_effective_project_roles(db, user_id, project_id)
    roles |= _forward_inherited_roles(db, user_id, project_id)
    if _has_member_source_access(db, user_id, project_id):
        roles.add(ProjectRole.MEMBER)
    return _normalize(roles)


def _direct_project_managers(db: Session, project_id: UUID) -> set[UUID]:
    """Returns the user ids who hold (directly or via group) the manager
    role on `project_id` itself — no inheritance. The "concrete,
    individually accountable users" building block
    `get_effective_project_managers` extends with forward-inherited
    managers.
    """
    manager_ids: set[UUID] = set(
        db.scalars(
            select(UserProjectRole.user_id).where(
                UserProjectRole.project_id == project_id,
                UserProjectRole.role == ProjectRole.PROJECT_MANAGER,
            )
        ).all()
    )
    manager_ids.update(
        db.scalars(
            select(ProjectGroupMember.user_id)
            .join(ProjectGroup, ProjectGroup.id == ProjectGroupMember.project_group_id)
            .where(
                ProjectGroup.project_id == project_id,
                ProjectGroup.role == ProjectRole.PROJECT_MANAGER,
                ProjectGroupMember.user_id.is_not(None),
            )
        ).all()
    )
    return manager_ids


def get_effective_project_managers(
    db: Session,
    project_id: UUID,
    *,
    mode_override: ProjectRoleInheritanceMode | None = None,
    filter_role_override_set: bool = False,
    filter_role_override: ProjectRole | None = None,
    parent_override_set: bool = False,
    parent_override: UUID | None = None,
) -> set[UUID]:
    """Returns the user ids who hold the manager role on `project_id`,
    directly/via group, plus (per decision 7 in docs/decisions.md) anyone
    who holds it via forward inheritance — only `MIRROR_ALL` and
    `MIRROR_ROLE` filtered to `PROJECT_MANAGER` can ever contribute one;
    `MEMBER_ONLY` and the member-source mechanism never can, since both cap
    at `MEMBER` by construction.

    Used to enforce "a project must have at least one project manager"
    (C-U-08) and the org-removal fallback rule (C-U-09) — replaces
    `_direct_project_managers` at every call site that previously used the
    now-removed `get_project_managers`, since an inherited manager is a
    real, concrete, individually accountable user for these purposes too.

    The `*_override` parameters let a caller ask "what would the manager
    set be if `project_id`'s own `role_inheritance_mode`/
    `role_inheritance_filter_role`/`parent_project_id` were set to these
    values instead" — used by `routers.projects.update_project` to validate
    a *proposed* change (disabling inheritance, reparenting) before
    committing it, inside the same row lock as the write
    (`lock_project_for_update`) to avoid a TOCTOU window. `parent_override`
    only takes effect when `parent_override_set=True`, and
    `filter_role_override` only takes effect when
    `filter_role_override_set=True` — each independently, so a caller can
    override just one of mode/filter_role/parent without the others
    silently falling back to a *different* override's presence as a proxy
    for "was this one set" (a real bug an earlier version of this function
    had: `filter_role_override` was gated on `mode_override is not None`
    instead of its own flag, harmless only because every caller so far
    always passes both together).
    """
    manager_ids = _direct_project_managers(db, project_id)

    visited: set[UUID] = {project_id}
    current_id = project_id
    first_hop = True
    iterations = 0
    while iterations < _PROJECT_INHERITANCE_ITERATION_CAP:
        iterations += 1
        row = db.execute(
            select(Project.parent_project_id, Project.role_inheritance_mode, Project.role_inheritance_filter_role)
            .where(Project.id == current_id)
        ).first()
        if row is None:
            break
        # Overrides only ever apply at the first hop (project_id's own
        # settings, hypothetically changed) — every hop beyond that uses
        # its real stored values, since the override only asks "what if
        # *this* project's own settings were different", not its ancestors'.
        if first_hop:
            mode = mode_override if mode_override is not None else row.role_inheritance_mode
            filter_role = filter_role_override if filter_role_override_set else row.role_inheritance_filter_role
            parent_id = parent_override if parent_override_set else row.parent_project_id
            first_hop = False
        else:
            mode, filter_role, parent_id = row.role_inheritance_mode, row.role_inheritance_filter_role, row.parent_project_id

        if mode == ProjectRoleInheritanceMode.NONE or parent_id is None:
            break
        if parent_id in visited:
            break
        visited.add(parent_id)
        if mode == ProjectRoleInheritanceMode.MIRROR_ALL:
            manager_ids |= _direct_project_managers(db, parent_id)
        elif mode == ProjectRoleInheritanceMode.MIRROR_ROLE and filter_role == ProjectRole.PROJECT_MANAGER:
            manager_ids |= _direct_project_managers(db, parent_id)
        # MEMBER_ONLY, or MIRROR_ROLE filtered to a role other than
        # PROJECT_MANAGER, contributes no managers at this hop — but the
        # walk still continues to the next hop up, exactly like
        # `_forward_inherited_roles`: only mode == NONE stops it.
        current_id = parent_id

    return manager_ids


def is_inherited_manager(db: Session, user_id: UUID, project_id: UUID) -> bool:
    """True if `user_id` would hold `PROJECT_MANAGER` on `project_id` via
    forward inheritance alone, independent of any direct/group role they
    also happen to hold on `project_id` itself.

    Used by `routers.projects.revoke_project_role`'s C-U-08 guard: without
    this, `managers == {user_id}` (the "is this the project's only
    effective manager" check) can't distinguish "removing this user's
    direct role would leave zero managers" from "this user is both a
    direct *and* an inherited manager, so removing the direct role is
    perfectly safe" — the naive check would over-block the latter, a real
    correctness gap `get_effective_project_managers`'s inheritance-
    awareness introduced (hierarchical projects; see docs/decisions.md).
    """
    return ProjectRole.PROJECT_MANAGER in _forward_inherited_roles(db, user_id, project_id)


def lock_project_for_update(db: Session, project_id: UUID) -> None:
    """Acquires a Postgres row lock on the project for the rest of the
    current transaction.

    Serializes concurrent "is this the project's last manager?" checks
    (`revoke_project_role`, `remove_project_group_member`,
    `leave_organization`, `deactivate_org_user`'s C-U-09 fallback) against
    each other. Without this, two concurrent removals — e.g. an org admin
    revoking manager A's role while manager B simultaneously leaves the org
    — can each independently observe the other as still-present backup and
    both proceed, leaving the project with zero managers even though each
    individual check correctly enforced C-U-08 against the state it saw.
    """
    db.execute(select(Project.id).where(Project.id == project_id).with_for_update())


def lock_organization_for_update(db: Session, organization_id: UUID) -> None:
    """Acquires a Postgres row lock on the organisation for the rest of the
    current transaction, serializing concurrent org-membership-count-
    sensitive operations (currently: `leave_organization`'s sole-admin
    check) against each other — see `lock_project_for_update` for the same
    race shape one level up."""
    db.execute(select(Organization.id).where(Organization.id == organization_id).with_for_update())


def get_project_users_by_role(db: Session, project_id: UUID, role: ProjectRole) -> set[UUID]:
    """Returns the user ids who effectively hold `role` on `project_id` —
    direct, group, or nested-org-group (`_direct_project_role_holder_ids`),
    plus forward-inherited holders of that same role (decision 5 in
    docs/decisions.md: an inherited role is real access, so it counts for
    notification targeting the same as `get_project_member_user_ids`
    already does — a user who is only a `PROJECT_MANAGER` of a project via
    `role_inheritance_mode=MIRROR_ALL`/`MIRROR_ROLE` has real approval
    authority and must not silently miss change-request notifications
    (`routers.change_requests.py`) just because their role came from a
    parent). Member-source contribution is included too when `role ==
    MEMBER` (the only role that mechanism can ever grant) for the same
    reason, though today's callers only ever pass `PROJECT_MANAGER`/
    `STAKEHOLDER`.

    An earlier version of this function excluded nested-org-group holders,
    matching `_direct_project_managers`'s deliberately narrower "concrete,
    individually accountable user" semantics for C-U-08's manager-floor
    invariant — but that narrowing was never a deliberate choice for
    *notification* targeting specifically, and widening it here brings this
    function in line with `get_effective_project_roles`'s own resolution
    (which already includes nested-org-group), which is more accurate for
    C-N-01's purpose than the previous, narrower behaviour.
    """
    user_ids = _direct_project_role_holder_ids(db, project_id, role)

    visited: set[UUID] = {project_id}
    current_id = project_id
    iterations = 0
    while iterations < _PROJECT_INHERITANCE_ITERATION_CAP:
        iterations += 1
        row = db.execute(
            select(Project.parent_project_id, Project.role_inheritance_mode, Project.role_inheritance_filter_role)
            .where(Project.id == current_id)
        ).first()
        if row is None or row.role_inheritance_mode == ProjectRoleInheritanceMode.NONE or row.parent_project_id is None:
            break
        parent_id = row.parent_project_id
        if parent_id in visited:
            break
        visited.add(parent_id)
        if row.role_inheritance_mode == ProjectRoleInheritanceMode.MIRROR_ALL:
            user_ids |= _direct_project_role_holder_ids(db, parent_id, role)
        elif row.role_inheritance_mode == ProjectRoleInheritanceMode.MIRROR_ROLE:
            if row.role_inheritance_filter_role == role:
                user_ids |= _direct_project_role_holder_ids(db, parent_id, role)
        elif row.role_inheritance_mode == ProjectRoleInheritanceMode.MEMBER_ONLY and role == ProjectRole.MEMBER:
            user_ids |= _direct_project_member_ids(db, parent_id)
        current_id = parent_id

    if role == ProjectRole.MEMBER:
        user_ids |= _member_source_contributed_user_ids(db, project_id)

    return user_ids


def get_project_member_user_ids(db: Session, project_id: UUID) -> set[UUID]:
    """Returns every user id with any access to a project, for broadcast-style
    notifications (C-N-01) — direct roles, direct group membership, members
    of org groups nested into a project group, plus (decision 5 in
    docs/decisions.md) forward-inherited and member-source-inherited users.
    `ProjectVisibility.ORG_WIDE`'s baseline grant stays excluded throughout,
    same as before hierarchical projects existed — see
    `_direct_project_member_ids`'s docstring.
    """
    user_ids = _direct_project_member_ids(db, project_id)
    user_ids |= _forward_contributed_member_ids(db, project_id)
    user_ids |= _member_source_contributed_user_ids(db, project_id)
    return user_ids


def get_effective_project_members_with_provenance(db: Session, project_id: UUID) -> dict[UUID, list[dict]]:
    """Returns, for every user with any effective role on `project_id`, a
    list of provenance entries — `{kind, role, via_project_id, via_mode}` —
    powering `GET /{id}/effective-members` (decision 10 in
    docs/decisions.md: project admin views must show whether a user's
    access is direct or inherited, and how) and
    `POST /{id}/materialize-inherited-access` (decision 9: converting
    currently-inherited access to direct roles before disabling
    inheritance). A user can appear multiple times if they have more than
    one source (e.g. a direct `STAKEHOLDER` grant plus a forward-inherited
    `PROJECT_MANAGER`) — both entries are returned, not collapsed.

    `kind` is one of:
      - `"direct"`: any of the four direct sources on `project_id` itself
        (`UserProjectRole`, `ProjectGroup`, nested-org-group, or org-wide
        visibility) — not further subdivided, since the distinction that
        matters for this admin-facing view is direct vs. inherited, not
        which of the four direct sources specifically.
      - `"forward_inherited"`: via `role_inheritance_mode`, with
        `via_project_id` naming the ancestor hop that contributed it and
        `via_mode` naming that hop's mode.
      - `"member_source_inherited"`: via the `ProjectMemberSource`
        mechanism — always `MEMBER`. `via_project_id` is left `None` here
        (not attempting to pin down which specific hop in a multi-level
        chain contributed it, unlike the forward case, since a user can be
        reachable through more than one branch of the chain simultaneously
        — a deliberate simplification for this admin-visibility view, not
        used for any access-control decision).

    Not optimised for the request-hot-path RBAC checks the rest of this
    module is (it iterates every user in the organisation) — acceptable
    here since this is an admin-only view opened occasionally, not
    something evaluated on every request like `get_effective_project_roles`.
    """
    project = db.get(Project, project_id)
    if project is None:
        return {}
    result: dict[UUID, list[dict]] = {}
    candidate_user_ids = set(
        db.scalars(select(UserOrgRole.user_id).where(UserOrgRole.organization_id == project.organization_id)).all()
    )

    for user_id in candidate_user_ids:
        for role in _direct_effective_project_roles(db, user_id, project_id):
            result.setdefault(user_id, []).append(
                {"kind": "direct", "role": role, "via_project_id": None, "via_mode": None}
            )

    visited: set[UUID] = {project_id}
    current_id = project_id
    iterations = 0
    while iterations < _PROJECT_INHERITANCE_ITERATION_CAP:
        iterations += 1
        row = db.execute(
            select(Project.parent_project_id, Project.role_inheritance_mode, Project.role_inheritance_filter_role)
            .where(Project.id == current_id)
        ).first()
        if row is None or row.role_inheritance_mode == ProjectRoleInheritanceMode.NONE or row.parent_project_id is None:
            break
        parent_id = row.parent_project_id
        if parent_id in visited:
            break
        visited.add(parent_id)
        if row.role_inheritance_mode == ProjectRoleInheritanceMode.MIRROR_ALL:
            for user_id in candidate_user_ids:
                for role in _direct_effective_project_roles(db, user_id, parent_id):
                    result.setdefault(user_id, []).append(
                        {"kind": "forward_inherited", "role": role, "via_project_id": parent_id, "via_mode": "mirror_all"}
                    )
        elif row.role_inheritance_mode == ProjectRoleInheritanceMode.MIRROR_ROLE and row.role_inheritance_filter_role is not None:
            for user_id in _direct_project_role_holder_ids(db, parent_id, row.role_inheritance_filter_role):
                result.setdefault(user_id, []).append(
                    {
                        "kind": "forward_inherited", "role": row.role_inheritance_filter_role,
                        "via_project_id": parent_id, "via_mode": "mirror_role",
                    }
                )
        elif row.role_inheritance_mode == ProjectRoleInheritanceMode.MEMBER_ONLY:
            for user_id in _direct_project_member_ids(db, parent_id):
                result.setdefault(user_id, []).append(
                    {
                        "kind": "forward_inherited", "role": ProjectRole.MEMBER,
                        "via_project_id": parent_id, "via_mode": "member_only",
                    }
                )
        current_id = parent_id

    for user_id in _member_source_contributed_user_ids(db, project_id):
        result.setdefault(user_id, []).append(
            {"kind": "member_source_inherited", "role": ProjectRole.MEMBER, "via_project_id": None, "via_mode": None}
        )

    return result


def require_server_admin(request: Request, current_user: User = Depends(get_current_user)) -> User:
    """FastAPI dependency requiring the cross-tenant server admin role (I-M-05).

    Personal Access Tokens can never satisfy this, even for a genuine
    server admin's own token: a PAT's whole design is "which orgs can it
    access," which is meaningless for a deployment-wide action — I-M-05's
    "server admin does not give access to data within organisations"
    extends naturally to treating a PAT as an inherently org-scoped
    credential, full stop.
    """
    if getattr(request.state, "pat_allowed_org_ids", None) is not None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Personal access tokens cannot be used for server administration.")
    if not current_user.is_server_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Server admin permission required.")
    return current_user


def require_org_role(*allowed: OrgRole):
    """FastAPI dependency factory requiring one of the given org roles.

    Expects an `organization_id` path parameter.

    Server admins do NOT bypass this check. I-M-05 is explicit that the
    server admin role "does not give access to data within organisations" —
    the only documented carve-out is creating the *initial* user in a new
    organisation, which uses `require_org_admin_or_server_admin` below
    instead of this factory.
    """

    def _dependency(
        organization_id: UUID,
        request: Request,
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        """See the enclosing `require_org_role` factory's docstring."""
        check_pat_scope(request, organization_id)
        _require_org_active(db, organization_id)
        _require_org_2fa(db, organization_id, current_user)
        roles = get_effective_org_roles(db, current_user.id, organization_id)
        if not roles & set(allowed):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient organisation permissions.")
        return current_user

    return _dependency


def require_org_admin_or_server_admin(
    organization_id: UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    """Dependency for the one documented server-admin carve-out (I-M-05
    clarification): "This permission needs to be able to create users in
    organisations, such that they can create the initial organisation user."
    Used only by the create-org-user endpoint — every other org-scoped
    endpoint requires a genuine org role via `require_org_role`.
    """
    check_pat_scope(request, organization_id)
    _require_org_active(db, organization_id)
    _require_org_2fa(db, organization_id, current_user)
    if current_user.is_server_admin:
        return current_user
    roles = get_effective_org_roles(db, current_user.id, organization_id)
    if OrgRole.ORG_ADMIN not in roles:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient organisation permissions.")
    return current_user


def _project_organization_id(db: Session, project_id: UUID) -> UUID | None:
    """Resolves a project's owning organisation id, or None if the project
    doesn't exist — used to gate project-scoped dependencies on the org's
    active state without masking a bogus `project_id` behind a misleading
    "organisation disabled" message (a nonexistent project should still
    fall through to the normal "not a member"/"insufficient permissions"
    response below, not this check)."""
    return db.scalar(select(Project.organization_id).where(Project.id == project_id))


def require_project_role(*allowed: ProjectRole):
    """FastAPI dependency factory requiring one of the given project roles.

    Expects a `project_id` path parameter. Server admins do NOT bypass this
    check (I-M-05) — project content is "data within organisations".
    """

    def _dependency(
        project_id: UUID,
        request: Request,
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        """See the enclosing `require_project_role` factory's docstring."""
        check_pat_scope_for_project(request, db, project_id)
        organization_id = _project_organization_id(db, project_id)
        if organization_id is not None:
            _require_org_active(db, organization_id)
            _require_org_2fa(db, organization_id, current_user)
        roles = get_effective_project_roles(db, current_user.id, project_id)
        if not roles & set(allowed):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient project permissions.")
        return current_user

    return _dependency


def check_pat_scope_for_project(request: Request, db: Session, project_id: UUID) -> None:
    """Like `check_pat_scope`, but for a `project_id` path parameter — one
    extra `Project.organization_id` lookup, only paid when the request is
    actually PAT-authenticated (a no-op read for ordinary session-JWT
    requests, which are the overwhelming majority)."""
    check_pat_project_scope(request, project_id)
    if getattr(request.state, "pat_allowed_org_ids", None) is None:
        return
    organization_id = db.scalar(select(Project.organization_id).where(Project.id == project_id))
    if organization_id is not None:
        check_pat_scope(request, organization_id)


def require_project_view(
    project_id: UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    """Dependency requiring any project role (member-level content access).

    Org admins are not automatically included here: per C-U-01 clarification,
    org admin only guarantees the ability to manage project settings, not
    general content access (see `require_project_manage`). Server admins do
    not bypass this either (I-M-05).
    """
    check_pat_scope_for_project(request, db, project_id)
    organization_id = _project_organization_id(db, project_id)
    if organization_id is not None:
        _require_org_active(db, organization_id)
        _require_org_2fa(db, organization_id, current_user)
    if not get_effective_project_roles(db, current_user.id, project_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not a member of this project.")
    return current_user


def require_project_view_or_manage(
    project_id: UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    """Dependency requiring either a genuine project role (`require_project_
    view`) or project-settings-management capability (`require_project_
    manage`'s `can_manage_project_settings` — org admins of the project's
    organisation, without needing a role of their own).

    For endpoints that expose role/group *structure* rather than
    requirement/change-request *content* — e.g. `list_project_groups` — so
    an org admin can see who's in which group well enough to manage a
    project's users (C-U-01 clarification) on a project they otherwise
    can't open, without this becoming a general content-access grant.
    """
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    check_pat_scope(request, project.organization_id)
    check_pat_project_scope(request, project_id)
    _require_org_active(db, project.organization_id)
    _require_org_2fa(db, project.organization_id, current_user)
    if get_effective_project_roles(db, current_user.id, project_id) or can_manage_project_settings(db, current_user, project):
        return current_user
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Not a member of this project.")


def require_project_manage(
    project_id: UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Project:
    """Dependency requiring project-settings-management capability.

    Grants access to project managers, project administrators, and
    organisation admins of the project's organisation (C-U-01 clarification,
    C-U-03 clarification). Server admins do not bypass this (I-M-05).
    Returns the Project so callers avoid a second lookup.
    """
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    check_pat_scope(request, project.organization_id)
    check_pat_project_scope(request, project.id)
    _require_org_active(db, project.organization_id)
    _require_org_2fa(db, project.organization_id, current_user)
    if not can_manage_project_settings(db, current_user, project):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient project permissions.")
    return project
