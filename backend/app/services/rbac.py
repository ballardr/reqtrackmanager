"""
Module: services.rbac

Computes a user's effective organisation and project roles and exposes
FastAPI dependencies that enforce them (C-U-01, C-U-03).

Effective project role resolution combines eight sources:
    1. Direct per-user role assignments (UserProjectRole).
    2. Membership in a project group (ProjectGroupMember with user_id set),
       for each role the group holds (ProjectGroupRole — PR7 of the
       members/groups directory rework plan replaced a group's old single,
       required `role` scalar with this separate grant table, mirroring
       source 8's own OrgGroupProjectRole shape: a group can now hold zero,
       one, or several roles at once, resolved here as one provenance entry
       per (group, granted role) pair a member's group membership matches).
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
       assignment needed. Deliberately narrower than the other sources —
       never implies PROJECT_MANAGER/ADMINISTRATOR/STAKEHOLDER, and
       deliberately not folded into `get_project_member_user_ids`
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
    6. Member-source (source -> receiving project) inheritance:
       `ProjectMemberSource`, an explicit list a project maintains of which
       other same-organisation projects it consumes members from,
       authorized entirely by the *receiving* project's own manage rights
       (not the source's) — see `models.project.ProjectMemberSource`'s
       docstring for why. Originally restricted to a direct child and
       always MEMBER-only; generalized (docs/decisions.md) to any
       same-organisation project, with each row's own `mirror_mode`/
       `mirror_filter_role` controlling what's mirrored — MIRROR_ALL/
       MIRROR_ROLE/MEMBER_ONLY, same vocabulary as source 5's forward
       mechanism, applied to the source's *direct* roles only (never the
       source's own inherited or member-sourced roles). Walks down through
       a chain of explicit lists (each hop requires that hop's own list to
       name the next one down, regardless of which mode granted access at
       an earlier hop). Also folded into `get_project_member_user_ids`.
    7. Project-referencing group membership: `ProjectGroupMember` with
       `source_project_id` set — "this group's members = that other
       project's direct members," resolved as one hop only (never that
       project's own inherited/member-sourced/project-referenced members)
       via `_direct_project_member_ids_base`, so two projects referencing
       each other can never cause unbounded recursion — a structural
       guarantee, not just an optimisation. Same-organisation only.
       Authorized purely by `require_project_manage` on the group's own
       project, mirroring source 6's receiving-side-only authorization.
       Treated as a "direct" source for provenance purposes (folded into
       `_direct_effective_project_roles`/`_direct_project_member_ids`/
       `_direct_project_role_holder_ids` alongside sources 1-4, the same
       way nested org groups already are) rather than a separate inherited
       kind, since it resolves at the project's own level via its own
       group configuration.
    8. Direct org-group project role assignment (`OrgGroupProjectRole`,
       added alongside the members/groups directory rework's PR4): an org
       group holding a project role directly, as its own
       independently-revocable record — parallel to source 1
       (`UserProjectRole`) but at the group level, and genuinely distinct
       from source 3 (nesting an org group inside a `ProjectGroup`, C-U-12):
       both mechanisms coexist by design, one is not a replacement for the
       other. Resolved for every org group the user belongs to, direct or
       transitively nested (`_ancestor_org_group_ids`, same closure source
       3 already uses), with the same live cross-tenant re-check
       (`OrgGroup.organization_id == Project.organization_id`) source 3
       applies. Provenance kind `"direct_org_group_role"`, with
       `via_group_id`/`via_group_name` naming the `OrgGroup` that granted
       it (not the same as `"direct_org_group"`'s provenance, which means
       "nested inside a project group" — kept as two distinct kinds so a UI
       can tell the two mechanisms apart). Folded into `_direct_effective_
       project_roles`/`_direct_project_member_ids`/`_direct_project_role_
       holder_ids` alongside sources 1-4/7 for the same reason source 7
       is — it resolves at the project's own level, not as a separate
       inherited kind — which is also what makes it cascade through
       forward inheritance (source 5) and the member-source mechanism
       (source 6) automatically: both walk an ancestor/source project's
       *direct* roles via these same shared helpers, so an org group's
       direct grant on a parent project is picked up by that walk exactly
       like a user's own direct grant already is, without either
       mechanism needing its own group-aware branch. See
       docs/decisions.md's identify/verify/remediate entry for this source.

Sources 5, 6, and 7 are kept decoupled from each other and from themselves:
the forward walk (5) only ever reads an ancestor's *direct* roles (which,
per source 8 above, now includes that ancestor's own `OrgGroupProjectRole`
grants); the member-source walk (6) only ever reads a source's *direct*
roles (plus, recursively, whatever that source has itself separately
consumed via its own member-source list — a deliberate, bounded chain); and
the project-reference arm (7) only ever reads a source's *base* direct
roles (`_direct_project_member_ids_base` — explicitly excluding even its
own project-reference arm, unlike 6's chaining). None of the three ever
reads another mechanism's already-resolved result. This prevents a
sibling-project leak (an unrelated project's users ending up visible via
someone else's mirroring) and avoids any mutual-recursion hazard. See
docs/decisions.md.

A project manager role implies project administrator and stakeholder
capabilities (C-U-03 clarification: "Project Managers can also perform all
project administrator and stakeholder tasks"). Holding any project role
implies baseline member-level view access. This normalization is applied
once, over the fully-combined set from all eight sources — so e.g. a child's
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
from sqlalchemy.orm import Session, aliased

from app.database import get_db
from app.deps import get_current_user
from app.models.enums import OrgRole, ProjectRole, ProjectRoleInheritanceMode, ProjectVisibility, ServerRole
from app.models.module_role import UserModuleRole
from app.models.organization import Organization, OrgGroup, OrgGroupMember, UserOrgRole
from app.models.project import (
    OrgGroupProjectRole,
    Project,
    ProjectGroup,
    ProjectGroupMember,
    ProjectGroupRole,
    ProjectMemberSource,
    UserProjectRole,
)
from app.models.server_role import UserServerRole
from app.models.user import User
from app.modules.registry import get_module, is_module_enabled

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


# The six sub-kinds `_direct_effective_project_roles_by_kind` distinguishes
# — see that function's docstring. Shared as a constant so callers (the
# provenance endpoint, tests) iterate a single source of truth for "what are
# all the possible direct-source kinds" rather than each hardcoding the list.
DIRECT_ROLE_KINDS: tuple[str, ...] = (
    "direct_role", "direct_group", "direct_org_group", "direct_project_ref", "direct_org_wide",
    "direct_org_group_role",
)


def _direct_effective_project_roles_by_kind(
    db: Session, user_id: UUID, project_id: UUID
) -> dict[str, set[ProjectRole] | set[tuple[ProjectRole, UUID, str]]]:
    """Same resolution as `_direct_effective_project_roles`, but keeping the
    six underlying sources (1-4 and 8 of the module docstring, plus org-wide
    visibility split out on its own) apart instead of collapsing them into
    one set.

    `"direct_group"`, `"direct_org_group"`, and `"direct_org_group_role"`
    hold `(role, group_id, group_name)` tuples rather than bare
    `ProjectRole`s — the group that actually granted the role, so provenance
    can name it. This means two *different* groups granting the same role
    produce two distinct tuple entries (they differ by group id/name even
    though the role matches), which is deliberate:
    `get_effective_project_members_with_provenance` must render one Source
    row per group, not collapse them. The other three kinds
    (`"direct_role"`, `"direct_project_ref"`, `"direct_org_wide"`) are
    unaffected and remain plain `set[ProjectRole]`.

    This is what makes `get_effective_project_members_with_provenance`'s
    provenance `kind` values safe to build an "is this role directly
    revocable" UI rule on (found in review before this split existed): a
    genuine `UserProjectRole` row (`"direct_role"`) is freely revocable via
    `DELETE /{project_id}/roles/{user_id}/{role}`, and a genuine
    `OrgGroupProjectRole` row (`"direct_org_group_role"`) is freely
    revocable via `DELETE /{project_id}/group-roles/{org_group_id}/{role}`
    — but a role arriving via a same-project group (`"direct_group"`), a
    nested org group (`"direct_org_group"`), a project-referencing group
    (`"direct_project_ref"`), or `ProjectVisibility.ORG_WIDE`
    (`"direct_org_wide"`) is not — neither endpoint above touches those
    rows, so offering either delete against any of those four kinds would
    204 as a silent no-op while a naive caller's UI showed the role as
    removed. Before the original split (Phase D, follow-up UX batch), all
    five of the then-existing kinds were collapsed into one `"direct"`
    bucket by `_direct_effective_project_roles` below, which can't support
    that distinction at all.

    `_direct_effective_project_roles` is now just this function's six sets
    unioned together — kept for the many existing callers that only need
    "does this project role exist at all," not which source it came from.

    Returns a dict with all of `DIRECT_ROLE_KINDS` always present as keys
    (value possibly an empty set).
    """
    by_kind: dict[str, set[ProjectRole] | set[tuple[ProjectRole, UUID, str]]] = {
        kind: set() for kind in DIRECT_ROLE_KINDS
    }

    direct = db.scalars(
        select(UserProjectRole.role).where(
            UserProjectRole.user_id == user_id, UserProjectRole.project_id == project_id
        )
    ).all()
    by_kind["direct_role"].update(ProjectRole(r) for r in direct)

    # Source 2: same-project group membership, for each role the group
    # holds (`ProjectGroupRole` — PR7 of the members/groups directory
    # rework plan replaced the group's old single, required `role` scalar
    # with this separate grant table, mirroring source 8's own
    # `OrgGroupProjectRole` shape). Joining through the grant table
    # (instead of reading `ProjectGroup.role` directly) produces one row
    # per (group, granted role) pair the membership matches — a group
    # holding two roles yields two entries here, same principle PR1 already
    # established for two *different* groups granting the same role.
    direct_group_rows = db.execute(
        select(ProjectGroupRole.role, ProjectGroup.id, ProjectGroup.name)
        .join(ProjectGroup, ProjectGroup.id == ProjectGroupRole.project_group_id)
        .join(ProjectGroupMember, ProjectGroupMember.project_group_id == ProjectGroup.id)
        .where(ProjectGroup.project_id == project_id, ProjectGroupMember.user_id == user_id)
    ).all()
    by_kind["direct_group"].update(
        (ProjectRole(role), group_id, group_name) for role, group_id, group_name in direct_group_rows
    )

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
        nested_group_rows = db.execute(
            select(ProjectGroupRole.role, OrgGroup.id, OrgGroup.name)
            .join(ProjectGroup, ProjectGroup.id == ProjectGroupRole.project_group_id)
            .join(ProjectGroupMember, ProjectGroupMember.project_group_id == ProjectGroup.id)
            .join(Project, Project.id == ProjectGroup.project_id)
            .join(OrgGroup, OrgGroup.id == ProjectGroupMember.org_group_id)
            .where(
                ProjectGroup.project_id == project_id,
                ProjectGroupMember.org_group_id.in_(user_org_group_ids),
                OrgGroup.organization_id == Project.organization_id,
            )
        ).all()
        by_kind["direct_org_group"].update(
            (ProjectRole(role), group_id, group_name) for role, group_id, group_name in nested_group_rows
        )

        # Source 8: org groups holding a role on this project *directly*
        # (`OrgGroupProjectRole`) rather than nested inside a `ProjectGroup`
        # — genuinely distinct from the `"direct_org_group"` block above.
        # Reuses `user_org_group_ids` (direct + transitively-nested org
        # groups) computed just above, and the same cross-tenant defense in
        # depth.
        direct_group_role_rows = db.execute(
            select(OrgGroupProjectRole.role, OrgGroup.id, OrgGroup.name)
            .join(OrgGroup, OrgGroup.id == OrgGroupProjectRole.org_group_id)
            .join(Project, Project.id == OrgGroupProjectRole.project_id)
            .where(
                OrgGroupProjectRole.project_id == project_id,
                OrgGroupProjectRole.org_group_id.in_(user_org_group_ids),
                OrgGroup.organization_id == Project.organization_id,
            )
        ).all()
        by_kind["direct_org_group_role"].update(
            (ProjectRole(role), group_id, group_name) for role, group_id, group_name in direct_group_role_rows
        )

    # Source 7: project-referencing group members ("this group = that other
    # project's direct members") — one hop only, via `_direct_project_
    # member_ids_base` so this can never recurse (see that function's
    # docstring and the module docstring's source-7 entry).
    SourceProject = aliased(Project)
    project_ref_rows = db.execute(
        select(ProjectGroupRole.role, ProjectGroupMember.source_project_id)
        .join(ProjectGroup, ProjectGroup.id == ProjectGroupRole.project_group_id)
        .join(ProjectGroupMember, ProjectGroupMember.project_group_id == ProjectGroup.id)
        .join(Project, Project.id == ProjectGroup.project_id)
        .join(SourceProject, SourceProject.id == ProjectGroupMember.source_project_id)
        .where(
            ProjectGroup.project_id == project_id,
            ProjectGroupMember.source_project_id.is_not(None),
            SourceProject.organization_id == Project.organization_id,
        )
    ).all()
    if project_ref_rows:
        member_cache: dict[UUID, set[UUID]] = {}
        for role, source_id in project_ref_rows:
            if source_id not in member_cache:
                member_cache[source_id] = _direct_project_member_ids_base(db, source_id)
            if user_id in member_cache[source_id]:
                by_kind["direct_project_ref"].add(ProjectRole(role))

    project_row = db.execute(
        select(Project.visibility, Project.organization_id).where(Project.id == project_id)
    ).first()
    if project_row is not None:
        visibility, organization_id = project_row
        if visibility == ProjectVisibility.ORG_WIDE and get_effective_org_roles(db, user_id, organization_id):
            by_kind["direct_org_wide"].add(ProjectRole.MEMBER)

    return by_kind


def _direct_effective_project_roles(db: Session, user_id: UUID, project_id: UUID) -> set[ProjectRole]:
    """Returns the roles a user holds on `project_id` itself — sources 1-4
    and 8 of the module docstring (direct, direct group, nested-org-group,
    org-wide visibility, direct org-group role) — with no cross-project
    inheritance and no PROJECT_MANAGER-implies-ADMINISTRATOR/STAKEHOLDER or
    any-role-implies-MEMBER normalization applied (`_normalize` does that,
    once, over the fully-combined result). This is the building block both
    inheritance mechanisms use to read an *other* project's roles without
    ever reading that project's own already-inherited results — see the
    module docstring's decoupling note. This is also, deliberately, what
    makes source 8 (an org group's direct role grant) cascade through
    forward inheritance automatically: `_forward_inherited_roles` reads an
    ancestor's roles via this exact function, so an ancestor's
    `OrgGroupProjectRole` grants are already included without that walk
    needing its own group-aware branch.

    Just `_direct_effective_project_roles_by_kind`'s six sets unioned
    together — see that function's docstring for the finer-grained,
    kind-preserving version this delegates to. Three of those six kinds
    (`"direct_group"`/`"direct_org_group"`/`"direct_org_group_role"`) hold
    `(role, group_id, group_name)` tuples rather than bare roles, so each
    entry is normalized down to just its role before being folded into the
    flat set this function returns.
    """
    roles: set[ProjectRole] = set()
    for kind_roles in _direct_effective_project_roles_by_kind(db, user_id, project_id).values():
        for entry in kind_roles:
            roles.add(entry[0] if isinstance(entry, tuple) else entry)
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


def _direct_project_member_ids_base(db: Session, project_id: UUID) -> set[UUID]:
    """The user_id/org_group_id `ProjectGroupMember` arms plus direct
    `UserProjectRole` assignments and direct `OrgGroupProjectRole` grants
    (source 8) — i.e. `_direct_project_member_ids` *without* its
    `source_project_id` "members of another project" arm.

    Used as the source-side resolution inside that third arm (see
    `_direct_project_member_ids`) precisely so a project-referencing group
    only ever reads a source project's own non-project-referenced direct
    members. This is what makes two projects referencing each other's
    rosters structurally incapable of unbounded recursion — `_direct_
    project_member_ids` and this function never call each other in a cycle,
    only ever this one, non-recursive direction.

    Including `OrgGroupProjectRole` here (added for the direct org-group
    role grant mechanism) is also what makes an ancestor/source project's
    group-level direct grants cascade through forward inheritance's
    `MIRROR_ALL`/`MEMBER_ONLY` modes and the member-source mechanism's
    equivalent modes the same way a user's own direct role already does —
    both walks read *this* function (via `_direct_project_member_ids`) at
    each ancestor/source hop.

    PR7 (members/groups directory rework plan, docs/decisions.md) added an
    `EXISTS` requirement to both `ProjectGroupMember` arms below — a group
    with zero roles (now possible; a group used to always have exactly one)
    no longer counts its members here. An earlier draft of this PR left
    plain membership counting regardless of role, reasoning that membership
    and role-holding were separate concepts elsewhere in this module — that
    was wrong in practice, caught by a failing test: `_accessible_project_
    ids` (`routers.projects`) has its own analogous `ProjectGroupMember`
    join for the same reason, and a user whose *only* connection to a
    project was membership in a now-zero-role group kept appearing in their
    own `GET /projects` listing (and, via this function, could be pulled
    into an unrelated *receiving* project through source 7's project-
    reference mechanism, or notified via `get_project_member_user_ids`)
    after every one of their actual effective roles had been revoked —
    while `get_effective_project_roles` (the authoritative check) correctly
    already saw zero roles for them. Both call sites are now consistent:
    membership in a group counts here only while that group still holds at
    least one role.
    """
    user_ids: set[UUID] = set(
        db.scalars(select(UserProjectRole.user_id).where(UserProjectRole.project_id == project_id)).all()
    )
    user_ids.update(
        db.scalars(
            select(ProjectGroupMember.user_id)
            .join(ProjectGroup, ProjectGroup.id == ProjectGroupMember.project_group_id)
            .join(ProjectGroupRole, ProjectGroupRole.project_group_id == ProjectGroup.id)
            .where(ProjectGroup.project_id == project_id, ProjectGroupMember.user_id.is_not(None))
        ).all()
    )
    nested_org_group_ids = set(
        db.scalars(
            select(ProjectGroupMember.org_group_id)
            .join(ProjectGroup, ProjectGroup.id == ProjectGroupMember.project_group_id)
            .join(ProjectGroupRole, ProjectGroupRole.project_group_id == ProjectGroup.id)
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
    # Source 8: org groups holding *any* role on `project_id` directly
    # (`OrgGroupProjectRole`) — same cross-tenant re-check and
    # descendant-expansion (a role held by a group extends to users who are
    # only members of a subgroup nested inside it) as the nested-group arm
    # just above.
    direct_role_group_ids = set(
        db.scalars(
            select(OrgGroupProjectRole.org_group_id)
            .join(OrgGroup, OrgGroup.id == OrgGroupProjectRole.org_group_id)
            .join(Project, Project.id == OrgGroupProjectRole.project_id)
            .where(OrgGroupProjectRole.project_id == project_id, OrgGroup.organization_id == Project.organization_id)
        ).all()
    )
    if direct_role_group_ids:
        all_direct_role_group_ids = direct_role_group_ids | _descendant_org_group_ids(db, direct_role_group_ids)
        user_ids.update(
            db.scalars(
                select(OrgGroupMember.user_id).where(
                    OrgGroupMember.org_group_id.in_(all_direct_role_group_ids), OrgGroupMember.user_id.is_not(None)
                )
            ).all()
        )
    return user_ids


def _direct_project_member_ids(db: Session, project_id: UUID) -> set[UUID]:
    """Set-returning sibling of `_direct_effective_project_roles`, minus its
    `ProjectVisibility.ORG_WIDE` source: every user with a direct, group,
    nested-org-group, or project-referenced role on `project_id` itself, no
    forward/member-source inheritance.

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

    The project-reference arm resolves each referenced source via
    `_direct_project_member_ids_base` (not this function) — see that
    function's docstring for why that's the one non-recursive direction.
    """
    user_ids = _direct_project_member_ids_base(db, project_id)
    SourceProject = aliased(Project)
    source_ids = set(
        db.scalars(
            select(ProjectGroupMember.source_project_id)
            .join(ProjectGroup, ProjectGroup.id == ProjectGroupMember.project_group_id)
            .join(Project, Project.id == ProjectGroup.project_id)
            .join(SourceProject, SourceProject.id == ProjectGroupMember.source_project_id)
            .where(
                ProjectGroup.project_id == project_id,
                ProjectGroupMember.source_project_id.is_not(None),
                SourceProject.organization_id == Project.organization_id,
            )
        ).all()
    )
    for source_id in source_ids:
        user_ids |= _direct_project_member_ids_base(db, source_id)
    return user_ids


def _direct_project_role_holder_ids(db: Session, project_id: UUID, role: ProjectRole) -> set[UUID]:
    """Set-returning "who holds exactly `role` directly on `project_id`",
    including nested-org-group-derived holders and direct-org-group-role
    (`OrgGroupProjectRole`, source 8) holders alike. (Pre-existing docstring
    note, corrected in passing: an *earlier* version of `get_project_users_
    by_role` used to deliberately exclude nested-org-group holders for a
    different purpose — notification-role-targeting, not inheritance — but
    that narrowing was removed; see that function's own docstring. Both
    functions now include nested-org-group and direct-org-group-role
    holders alike.)
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
            .join(ProjectGroupRole, ProjectGroupRole.project_group_id == ProjectGroup.id)
            .where(
                ProjectGroup.project_id == project_id, ProjectGroupRole.role == role,
                ProjectGroupMember.user_id.is_not(None),
            )
        ).all()
    )
    nested_org_group_ids = set(
        db.scalars(
            select(ProjectGroupMember.org_group_id)
            .join(ProjectGroup, ProjectGroup.id == ProjectGroupMember.project_group_id)
            .join(ProjectGroupRole, ProjectGroupRole.project_group_id == ProjectGroup.id)
            .where(
                ProjectGroup.project_id == project_id, ProjectGroupRole.role == role,
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

    # Source 8: org groups holding exactly `role` on `project_id` directly
    # (`OrgGroupProjectRole`) — same cross-tenant re-check and
    # descendant-expansion as the nested-group arm above.
    direct_role_group_ids = set(
        db.scalars(
            select(OrgGroupProjectRole.org_group_id)
            .join(OrgGroup, OrgGroup.id == OrgGroupProjectRole.org_group_id)
            .join(Project, Project.id == OrgGroupProjectRole.project_id)
            .where(
                OrgGroupProjectRole.project_id == project_id, OrgGroupProjectRole.role == role,
                OrgGroup.organization_id == Project.organization_id,
            )
        ).all()
    )
    if direct_role_group_ids:
        all_direct_role_group_ids = direct_role_group_ids | _descendant_org_group_ids(db, direct_role_group_ids)
        user_ids.update(
            db.scalars(
                select(OrgGroupMember.user_id).where(
                    OrgGroupMember.org_group_id.in_(all_direct_role_group_ids), OrgGroupMember.user_id.is_not(None)
                )
            ).all()
        )

    # Source 7: project-referencing group members granted exactly `role` —
    # resolved via `_direct_project_member_ids_base`, same non-recursive
    # direction as `_direct_project_member_ids`'s own third arm.
    SourceProject = aliased(Project)
    project_ref_source_ids = set(
        db.scalars(
            select(ProjectGroupMember.source_project_id)
            .join(ProjectGroup, ProjectGroup.id == ProjectGroupMember.project_group_id)
            .join(ProjectGroupRole, ProjectGroupRole.project_group_id == ProjectGroup.id)
            .join(Project, Project.id == ProjectGroup.project_id)
            .join(SourceProject, SourceProject.id == ProjectGroupMember.source_project_id)
            .where(
                ProjectGroup.project_id == project_id, ProjectGroupRole.role == role,
                ProjectGroupMember.source_project_id.is_not(None),
                SourceProject.organization_id == Project.organization_id,
            )
        ).all()
    )
    for source_id in project_ref_source_ids:
        user_ids |= _direct_project_member_ids_base(db, source_id)

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


def _member_source_rows(
    db: Session, frontier: set[UUID]
) -> list[tuple[UUID, UUID, ProjectRoleInheritanceMode, ProjectRole | None]]:
    """One BFS layer for the member-source (reverse) walk: every
    `(project_id, source_project_id, mirror_mode, mirror_filter_role)` row
    owned by any project in `frontier`, live-revalidated to require
    `source_project.organization_id == project.organization_id` (same
    organisation only — generalized from the original strict-parent/child
    requirement, see `models.project.ProjectMemberSource`'s docstring) and
    `source_project_id != project_id` (no self-reference). Shared by
    `_member_source_derived_roles`/`_member_source_contributed_user_ids`/
    `_member_source_role_holder_ids`/`get_effective_project_members_with_
    provenance` below.
    """
    if not frontier:
        return []
    OwnerProject = aliased(Project)
    return list(
        db.execute(
            select(
                ProjectMemberSource.project_id,
                ProjectMemberSource.source_project_id,
                ProjectMemberSource.mirror_mode,
                ProjectMemberSource.mirror_filter_role,
            )
            .join(Project, Project.id == ProjectMemberSource.source_project_id)
            .join(OwnerProject, OwnerProject.id == ProjectMemberSource.project_id)
            .where(
                ProjectMemberSource.project_id.in_(frontier),
                Project.organization_id == OwnerProject.organization_id,
                ProjectMemberSource.source_project_id != ProjectMemberSource.project_id,
            )
        ).all()
    )


def _direct_project_roles_excluding_org_wide(db: Session, user_id: UUID, project_id: UUID) -> set[ProjectRole]:
    """Like `_direct_effective_project_roles` but omitting the
    `ProjectVisibility.ORG_WIDE` baseline grant — the full-role-granularity
    counterpart to `_direct_project_member_ids`'s boolean membership
    exclusion of the same source, needed by `_member_source_derived_roles`'s
    `MIRROR_ALL` case (which must mirror a source's *actual* direct roles,
    not just "are they a member"). Includes nested-org-group and
    direct-org-group-role (`OrgGroupProjectRole`, source 8) grants alike.
    Excluding `ORG_WIDE` here for the same
    reason `_direct_project_member_ids`'s docstring gives: an ORG_WIDE-
    visible source project must never flow its entire organisation's
    implicit membership through the member-source mechanism into a
    receiving project as if it were a real, explicit grant.
    """
    roles: set[ProjectRole] = set(
        db.scalars(
            select(UserProjectRole.role).where(
                UserProjectRole.user_id == user_id, UserProjectRole.project_id == project_id
            )
        ).all()
    )
    roles.update(
        ProjectRole(r)
        for r in db.scalars(
            select(ProjectGroupRole.role)
            .join(ProjectGroup, ProjectGroup.id == ProjectGroupRole.project_group_id)
            .join(ProjectGroupMember, ProjectGroupMember.project_group_id == ProjectGroup.id)
            .where(ProjectGroup.project_id == project_id, ProjectGroupMember.user_id == user_id)
        ).all()
    )
    direct_org_group_ids = set(
        db.scalars(select(OrgGroupMember.org_group_id).where(OrgGroupMember.user_id == user_id)).all()
    )
    user_org_group_ids = direct_org_group_ids | _ancestor_org_group_ids(db, direct_org_group_ids)
    if user_org_group_ids:
        roles.update(
            ProjectRole(r)
            for r in db.scalars(
                select(ProjectGroupRole.role)
                .join(ProjectGroup, ProjectGroup.id == ProjectGroupRole.project_group_id)
                .join(ProjectGroupMember, ProjectGroupMember.project_group_id == ProjectGroup.id)
                .join(Project, Project.id == ProjectGroup.project_id)
                .join(OrgGroup, OrgGroup.id == ProjectGroupMember.org_group_id)
                .where(
                    ProjectGroup.project_id == project_id,
                    ProjectGroupMember.org_group_id.in_(user_org_group_ids),
                    OrgGroup.organization_id == Project.organization_id,
                )
            ).all()
        )
        # Source 8: org groups holding a role on `project_id` directly
        # (`OrgGroupProjectRole`) — same cross-tenant re-check as the
        # nested-group block above. Needed so a `MIRROR_ALL` member-source
        # row mirrors a source project's actual direct roles including this
        # mechanism, not just its `ProjectGroup`-nesting-derived ones.
        roles.update(
            ProjectRole(r)
            for r in db.scalars(
                select(OrgGroupProjectRole.role)
                .join(OrgGroup, OrgGroup.id == OrgGroupProjectRole.org_group_id)
                .join(Project, Project.id == OrgGroupProjectRole.project_id)
                .where(
                    OrgGroupProjectRole.project_id == project_id,
                    OrgGroupProjectRole.org_group_id.in_(user_org_group_ids),
                    OrgGroup.organization_id == Project.organization_id,
                )
            ).all()
        )
    return roles


def _member_source_derived_roles(db: Session, user_id: UUID, project_id: UUID) -> set[ProjectRole]:
    """The roles `user_id` gains on `project_id` via the member-source
    mechanism — source 6 of the module docstring. Walks *down* through
    `project_id`'s own `ProjectMemberSource` list, breadth-first, applying
    each row's own `mirror_mode`/`mirror_filter_role` to that row's source
    project: `MIRROR_ALL` mirrors the user's actual direct roles there
    (`_direct_project_roles_excluding_org_wide`), `MIRROR_ROLE` mirrors
    exactly `mirror_filter_role` if the user directly holds it there, and
    `MEMBER_ONLY` (the default, and the only behavior any row created
    before this generalization can have) grants bare `MEMBER` if the user
    has any direct role there — byte-identical to the original behavior.
    Then continues into that source's own member-source list in turn,
    regardless of which mode granted access at this hop, so a grandchild's
    members reach the grandparent only if both the grandchild and the
    intermediate hop have opted in via their own lists. Never reads a
    source's forward-inherited roles — only its direct ones — per the
    module docstring's decoupling note.

    Iterative (not recursive) and capped at
    `_PROJECT_INHERITANCE_ITERATION_CAP` layers, matching every other
    unlimited-depth tree walk in this module — this runs on essentially
    every RBAC check.
    """
    granted: set[ProjectRole] = set()
    visited: set[UUID] = {project_id}
    frontier: set[UUID] = {project_id}
    iterations = 0
    while frontier and iterations < _PROJECT_INHERITANCE_ITERATION_CAP:
        iterations += 1
        rows = _member_source_rows(db, frontier)
        next_frontier: set[UUID] = set()
        for _owner_id, source_id, mode, filter_role in rows:
            if mode == ProjectRoleInheritanceMode.MIRROR_ALL:
                granted |= _direct_project_roles_excluding_org_wide(db, user_id, source_id)
            elif mode == ProjectRoleInheritanceMode.MIRROR_ROLE:
                if filter_role is not None and user_id in _direct_project_role_holder_ids(db, source_id, filter_role):
                    granted.add(filter_role)
            else:  # MEMBER_ONLY — also the default/backward-compatible behavior
                if user_id in _direct_project_member_ids(db, source_id):
                    granted.add(ProjectRole.MEMBER)
            if source_id not in visited:
                next_frontier.add(source_id)
        visited |= next_frontier
        frontier = next_frontier
    return granted


def _group_forward_inherited_roles(db: Session, org_group_id: UUID, project_id: UUID) -> set[ProjectRole]:
    """Group-scoped counterpart to `_forward_inherited_roles` — walks
    `project_id`'s parent chain upward the same way (same iteration cap,
    same break conditions), but at each hop reads that ancestor's own
    *direct* `OrgGroupProjectRole` grant for `org_group_id` (source 8 of
    the module docstring) instead of a user's combined direct roles.

    Added for PR6 of the members/groups directory rework plan (per-group
    "convert inherited to direct" action,
    `materialize_inherited_access_for_group` in routers/projects.py): that
    action needs to know what an org group's *own* forward-inherited role
    on this project is, independent of any particular member — a question
    `_forward_inherited_roles` can't answer since it's scoped to a single
    user. Live cross-tenant re-check (`OrgGroup.organization_id ==
    Project.organization_id`) at each hop, matching every other
    `OrgGroupProjectRole` read in this module.
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
        parent_roles = set(
            db.scalars(
                select(OrgGroupProjectRole.role)
                .join(OrgGroup, OrgGroup.id == OrgGroupProjectRole.org_group_id)
                .join(Project, Project.id == OrgGroupProjectRole.project_id)
                .where(
                    OrgGroupProjectRole.org_group_id == org_group_id,
                    OrgGroupProjectRole.project_id == parent_id,
                    OrgGroup.organization_id == Project.organization_id,
                )
            ).all()
        )
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


def _group_member_source_inherited_roles(db: Session, org_group_id: UUID, project_id: UUID) -> set[ProjectRole]:
    """Group-scoped counterpart to `_member_source_derived_roles` — same
    breadth-first walk down `project_id`'s `ProjectMemberSource` list (same
    iteration cap, same `_member_source_rows` frontier expansion), but at
    each hop reads that source's own direct `OrgGroupProjectRole` grant for
    `org_group_id` instead of a user's direct roles there. See
    `_group_forward_inherited_roles`'s docstring for why this group-scoped
    read exists alongside the user-scoped original."""
    inherited: set[ProjectRole] = set()
    visited: set[UUID] = {project_id}
    frontier: set[UUID] = {project_id}
    iterations = 0
    while frontier and iterations < _PROJECT_INHERITANCE_ITERATION_CAP:
        iterations += 1
        rows = _member_source_rows(db, frontier)
        next_frontier: set[UUID] = set()
        for _owner_id, source_id, mode, filter_role in rows:
            source_roles = set(
                db.scalars(
                    select(OrgGroupProjectRole.role)
                    .join(OrgGroup, OrgGroup.id == OrgGroupProjectRole.org_group_id)
                    .join(Project, Project.id == OrgGroupProjectRole.project_id)
                    .where(
                        OrgGroupProjectRole.org_group_id == org_group_id,
                        OrgGroupProjectRole.project_id == source_id,
                        OrgGroup.organization_id == Project.organization_id,
                    )
                ).all()
            )
            if mode == ProjectRoleInheritanceMode.MIRROR_ALL:
                inherited |= source_roles
            elif mode == ProjectRoleInheritanceMode.MIRROR_ROLE:
                if filter_role is not None and filter_role in source_roles:
                    inherited.add(filter_role)
            else:  # MEMBER_ONLY
                if source_roles:
                    inherited.add(ProjectRole.MEMBER)
            if source_id not in visited:
                next_frontier.add(source_id)
        visited |= next_frontier
        frontier = next_frontier
    return inherited


def get_group_inherited_project_roles(db: Session, org_group_id: UUID, project_id: UUID) -> set[ProjectRole]:
    """Union of an org group's own forward-inherited and member-source-
    inherited roles on `project_id` — the group-level analogue of what
    `get_effective_project_members_with_provenance` computes per user,
    scoped to a single group's own `OrgGroupProjectRole` grants rather than
    any user's combined effective access.

    Powers `POST /{project_id}/materialize-inherited-access/group/
    {org_group_id}` (PR6 of the members/groups directory rework plan):
    whether this group has anything inherited worth converting to a direct
    `OrgGroupProjectRole` grant, and if so, which role ranks highest. Does
    not include the group's own already-direct grants on `project_id`
    itself — callers compare against those separately (the same
    idempotency shape `materialize_inherited_access`'s own per-user rank
    comparison already uses)."""
    return _group_forward_inherited_roles(db, org_group_id, project_id) | _group_member_source_inherited_roles(
        db, org_group_id, project_id
    )


def _member_source_contributed_user_ids(db: Session, project_id: UUID) -> set[UUID]:
    """Set-returning sibling of `_member_source_derived_roles`, for
    `get_project_member_user_ids` — any user who gains *any* role via the
    member-source mechanism counts as contributed, regardless of which
    specific role each hop's `mirror_mode` grants."""
    contributed: set[UUID] = set()
    visited: set[UUID] = {project_id}
    frontier: set[UUID] = {project_id}
    iterations = 0
    while frontier and iterations < _PROJECT_INHERITANCE_ITERATION_CAP:
        iterations += 1
        rows = _member_source_rows(db, frontier)
        next_frontier: set[UUID] = set()
        for _owner_id, source_id, mode, filter_role in rows:
            if mode == ProjectRoleInheritanceMode.MIRROR_ROLE:
                if filter_role is not None:
                    contributed |= _direct_project_role_holder_ids(db, source_id, filter_role)
            else:
                contributed |= _direct_project_member_ids(db, source_id)
            if source_id not in visited:
                next_frontier.add(source_id)
        visited |= next_frontier
        frontier = next_frontier
    return contributed


def _member_source_role_holder_ids(db: Session, project_id: UUID, role: ProjectRole) -> set[UUID]:
    """Role-scoped sibling of `_member_source_contributed_user_ids`, for
    `get_project_users_by_role` — same BFS, but only accumulates users who
    gain exactly `role` via the mechanism (so e.g. a `MIRROR_ALL` row can
    contribute a `PROJECT_MANAGER` notification target, not just `MEMBER`,
    matching what `_member_source_derived_roles` would actually grant that
    user)."""
    holder_ids: set[UUID] = set()
    visited: set[UUID] = {project_id}
    frontier: set[UUID] = {project_id}
    iterations = 0
    while frontier and iterations < _PROJECT_INHERITANCE_ITERATION_CAP:
        iterations += 1
        rows = _member_source_rows(db, frontier)
        next_frontier: set[UUID] = set()
        for _owner_id, source_id, mode, filter_role in rows:
            if mode == ProjectRoleInheritanceMode.MIRROR_ALL:
                holder_ids |= _direct_project_role_holder_ids(db, source_id, role)
            elif mode == ProjectRoleInheritanceMode.MIRROR_ROLE:
                if filter_role == role:
                    holder_ids |= _direct_project_role_holder_ids(db, source_id, role)
            elif role == ProjectRole.MEMBER:  # MEMBER_ONLY
                holder_ids |= _direct_project_member_ids(db, source_id)
            if source_id not in visited:
                next_frontier.add(source_id)
        visited |= next_frontier
        frontier = next_frontier
    return holder_ids


def get_effective_project_roles(db: Session, user_id: UUID, project_id: UUID) -> set[ProjectRole]:
    """Returns the set of project roles a user effectively holds.

    See module docstring for the resolution algorithm (eight sources:
    direct, direct group, nested-org-group, project-referencing group,
    org-wide visibility, forward inheritance, member-source inheritance,
    direct org-group role).
    """
    roles = _direct_effective_project_roles(db, user_id, project_id)
    roles |= _forward_inherited_roles(db, user_id, project_id)
    roles |= _member_source_derived_roles(db, user_id, project_id)
    return _normalize(roles)


def _direct_project_managers(db: Session, project_id: UUID) -> set[UUID]:
    """Returns the user ids who hold (directly or via group) the manager
    role on `project_id` itself — no inheritance. The "concrete,
    individually accountable users" building block
    `get_effective_project_managers` extends with forward-inherited
    managers.

    A `ProjectGroup`'s *direct user* members (`ProjectGroupMember.user_id`)
    DO count towards this — unlike a nested org group or an org group's own
    direct `OrgGroupProjectRole` grant, neither of which this function
    resolves at all (see `revoke_group_project_role`'s own docstring for
    why those two are deliberately excluded from the C-U-08 floor). PR7
    (docs/decisions.md) changed only *how* a group's manager-role status is
    read — joined through `ProjectGroupRole` now that a group can hold zero,
    one, or several roles, instead of the old scalar `ProjectGroup.role` —
    not whether a project group's direct members count at all.
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
            .join(ProjectGroupRole, ProjectGroupRole.project_group_id == ProjectGroup.id)
            .where(
                ProjectGroup.project_id == project_id,
                ProjectGroupRole.role == ProjectRole.PROJECT_MANAGER,
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
    parent). Member-source contribution is included too, for the same
    reason — originally only ever `MEMBER` (the only role that mechanism
    could grant), now scoped to whatever `role` each `ProjectMemberSource`
    row's own `mirror_mode` actually grants (`_member_source_role_holder_
    ids`), though today's callers only ever pass `PROJECT_MANAGER`/
    `STAKEHOLDER`/`MEMBER`.

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

    user_ids |= _member_source_role_holder_ids(db, project_id, role)

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
    list of provenance entries — `{kind, role, via_project_id, via_mode,
    via_group_id, via_group_name}` — powering `GET /{id}/effective-members`
    (decision 10 in
    docs/decisions.md: project admin views must show whether a user's
    access is direct or inherited, and how) and
    `POST /{id}/materialize-inherited-access` (decision 9: converting
    currently-inherited access to direct roles before disabling
    inheritance). A user can appear multiple times if they have more than
    one source (e.g. a direct `STAKEHOLDER` grant plus a forward-inherited
    `PROJECT_MANAGER`) — both entries are returned, not collapsed.

    `kind` is one of:
      - `"direct_role"`: a genuine, individually-revocable `UserProjectRole`
        row on `project_id` itself.
      - `"direct_group"`: same-project `ProjectGroup` membership —
        `via_group_id`/`via_group_name` name that `ProjectGroup`.
      - `"direct_org_group"`: an org group nested into a same-project
        `ProjectGroup` — `via_group_id`/`via_group_name` name that
        `OrgGroup` (not the wrapping `ProjectGroup`).
      - `"direct_project_ref"`: a `ProjectGroup` whose members are defined
        as "another project's direct members" (`ProjectGroupMember.
        source_project_id`).
      - `"direct_org_wide"`: `ProjectVisibility.ORG_WIDE`'s baseline MEMBER
        grant.
      - `"direct_org_group_role"`: an org group holding a role on
        `project_id` *directly* (`OrgGroupProjectRole`) — distinct from
        `"direct_org_group"` above, which means "nested inside a
        `ProjectGroup`" — `via_group_id`/`via_group_name` name that
        `OrgGroup`. Also a genuine, individually-revocable row (via
        `DELETE /{project_id}/group-roles/{org_group_id}/{role}`), just not
        one scoped to a single user the way `"direct_role"` is.
        (`"direct_role"`/`"direct_group"`/`"direct_org_group"`/
        `"direct_project_ref"`/`"direct_org_wide"` were split from a single
        collapsed `"direct"` kind — see `_direct_effective_project_roles_
        by_kind`'s docstring for why: only `"direct_role"` (and, since PR4,
        `"direct_org_group_role"` for a group-scoped equivalent) is safe to
        offer as freely toggle-off-able in a UI, since `DELETE /
        {project_id}/roles/{user_id}/{role}` only ever deletes
        `UserProjectRole` rows — treating any of the other three
        group/org-wide kinds as equally revocable would silently no-op.)
      - `"forward_inherited"`: via `role_inheritance_mode`, with
        `via_project_id` naming the ancestor hop that contributed it and
        `via_mode` naming that hop's mode.
      - `"member_source_inherited"`: via the `ProjectMemberSource`
        mechanism — `role`/`via_mode` reflect the contributing hop's own
        `mirror_mode` (`mirror_all`/`mirror_role`/`member_only`, no longer
        always `MEMBER`) and `via_project_id` names that hop's source
        project.

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
        by_kind = _direct_effective_project_roles_by_kind(db, user_id, project_id)
        for kind, roles in by_kind.items():
            for entry in roles:
                if kind in ("direct_group", "direct_org_group", "direct_org_group_role"):
                    role, via_group_id, via_group_name = entry
                else:
                    role, via_group_id, via_group_name = entry, None, None
                result.setdefault(user_id, []).append(
                    {
                        "kind": kind, "role": role, "via_project_id": None, "via_mode": None,
                        "via_group_id": via_group_id, "via_group_name": via_group_name,
                    }
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
                        {
                            "kind": "forward_inherited", "role": role, "via_project_id": parent_id,
                            "via_mode": "mirror_all", "via_group_id": None, "via_group_name": None,
                        }
                    )
        elif row.role_inheritance_mode == ProjectRoleInheritanceMode.MIRROR_ROLE and row.role_inheritance_filter_role is not None:
            for user_id in _direct_project_role_holder_ids(db, parent_id, row.role_inheritance_filter_role):
                result.setdefault(user_id, []).append(
                    {
                        "kind": "forward_inherited", "role": row.role_inheritance_filter_role,
                        "via_project_id": parent_id, "via_mode": "mirror_role",
                        "via_group_id": None, "via_group_name": None,
                    }
                )
        elif row.role_inheritance_mode == ProjectRoleInheritanceMode.MEMBER_ONLY:
            for user_id in _direct_project_member_ids(db, parent_id):
                result.setdefault(user_id, []).append(
                    {
                        "kind": "forward_inherited", "role": ProjectRole.MEMBER,
                        "via_project_id": parent_id, "via_mode": "member_only",
                        "via_group_id": None, "via_group_name": None,
                    }
                )
        current_id = parent_id

    ms_visited: set[UUID] = {project_id}
    ms_frontier: set[UUID] = {project_id}
    ms_iterations = 0
    while ms_frontier and ms_iterations < _PROJECT_INHERITANCE_ITERATION_CAP:
        ms_iterations += 1
        rows = _member_source_rows(db, ms_frontier)
        next_frontier: set[UUID] = set()
        for _owner_id, source_id, mode, filter_role in rows:
            if mode == ProjectRoleInheritanceMode.MIRROR_ALL:
                for user_id in candidate_user_ids:
                    for role in _direct_project_roles_excluding_org_wide(db, user_id, source_id):
                        result.setdefault(user_id, []).append(
                            {
                                "kind": "member_source_inherited", "role": role,
                                "via_project_id": source_id, "via_mode": "mirror_all",
                                "via_group_id": None, "via_group_name": None,
                            }
                        )
            elif mode == ProjectRoleInheritanceMode.MIRROR_ROLE and filter_role is not None:
                for user_id in _direct_project_role_holder_ids(db, source_id, filter_role):
                    result.setdefault(user_id, []).append(
                        {
                            "kind": "member_source_inherited", "role": filter_role,
                            "via_project_id": source_id, "via_mode": "mirror_role",
                            "via_group_id": None, "via_group_name": None,
                        }
                    )
            else:  # MEMBER_ONLY
                for user_id in _direct_project_member_ids(db, source_id):
                    result.setdefault(user_id, []).append(
                        {
                            "kind": "member_source_inherited", "role": ProjectRole.MEMBER,
                            "via_project_id": source_id, "via_mode": "member_only",
                            "via_group_id": None, "via_group_name": None,
                        }
                    )
            if source_id not in ms_visited:
                next_frontier.add(source_id)
        ms_visited |= next_frontier
        ms_frontier = next_frontier

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


def require_server_role(*allowed: ServerRole):
    """FastAPI dependency factory requiring one of the given server-tier
    roles (module system Phase 0), granted via `UserServerRole`.

    Composes with `User.is_server_admin` by design, not left for a later
    phase to discover: a genuine server admin always passes, regardless of
    which specific `allowed` roles were requested — the same "a higher tier
    already retains full access without needing every narrower role
    explicitly granted too" principle `require_org_role`'s own callers rely
    on for `ORG_ADMIN`, and the one Phase 2's `require_module_role` will
    extend to module-contributed roles. `ServerRole.SERVER_ADMIN` itself is
    never checked against a `UserServerRole` row — see that enum member's
    docstring for why `is_server_admin` remains its sole source of truth.

    Unlike `require_server_admin`, this has no PAT carve-out of its own:
    PATs are already blocked from every server-admin-tier action by
    `require_server_admin`, and nothing in this module system yet exposes a
    PAT-reachable endpoint gated by this dependency — revisit if one does.
    """

    def _dependency(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
        """See the enclosing `require_server_role` factory's docstring."""
        if current_user.is_server_admin:
            return current_user
        granted = set(
            db.scalars(
                select(UserServerRole.role).where(UserServerRole.user_id == current_user.id)
            ).all()
        )
        if not granted & set(allowed):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient server permissions.")
        return current_user

    return _dependency


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


def require_org_module_enabled(module_key: str):
    """FastAPI dependency factory requiring `module_key` to be effectively
    enabled (entitled AND enabled — `app.modules.registry.is_module_enabled`)
    for the org named by the `organization_id` path parameter, for a caller
    who is otherwise a member of that organisation (module system Phase 1).

    Expects an `organization_id` path parameter, same as `require_org_role`.

    Deliberately returns **404, not 403**, when the module is disabled or
    not entitled — compliance-module-plan.md Phase 1 is explicit that
    disabled/non-entitled functionality "should not be presented," which
    this codebase treats the same way it already treats a project a caller
    has no role on (`require_project_view`'s sibling 403) or a genuinely
    nonexistent resource: here, specifically 404, so a disabled module's
    endpoints are indistinguishable from endpoints that don't exist at all,
    rather than leaking their existence via a 403.

    No first-party module router is wired behind this yet (none exists
    until Phase 5) — this is infrastructure a module's own router uses
    internally once it has one, not something applied at the `app.main`
    mount-loop level (see `app.modules.registry`'s module docstring).
    """

    def _dependency(
        organization_id: UUID,
        request: Request,
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        """See the enclosing `require_org_module_enabled` factory's docstring."""
        check_pat_scope(request, organization_id)
        _require_org_active(db, organization_id)
        _require_org_2fa(db, organization_id, current_user)
        if not get_effective_org_roles(db, current_user.id, organization_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
        if not is_module_enabled(db, organization_id, module_key):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
        return current_user

    return _dependency


def require_project_module_enabled(module_key: str):
    """FastAPI dependency factory requiring `module_key` to be effectively
    enabled for the organisation owning the project named by the
    `project_id` path parameter, for a caller who is otherwise a member of
    that project (module system Phase 1). Project-scoped sibling of
    `require_org_module_enabled` — see that factory's docstring for the
    404-not-403 rationale, which applies identically here.

    Expects a `project_id` path parameter, same as `require_project_view`.
    """

    def _dependency(
        project_id: UUID,
        request: Request,
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        """See the enclosing `require_project_module_enabled` factory's docstring."""
        check_pat_scope_for_project(request, db, project_id)
        organization_id = _project_organization_id(db, project_id)
        if organization_id is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
        _require_org_active(db, organization_id)
        _require_org_2fa(db, organization_id, current_user)
        if not get_effective_project_roles(db, current_user.id, project_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
        if not is_module_enabled(db, organization_id, module_key):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
        return current_user

    return _dependency


def _has_module_role_grant(
    db: Session,
    user_id: UUID,
    module_key: str,
    role_key: str,
    *,
    organization_id: UUID | None = None,
    project_id: UUID | None = None,
) -> bool:
    """Returns whether `user_id` holds a direct `UserModuleRole` grant for
    `(module_key, role_key)`, optionally scoped to a specific
    `organization_id`/`project_id` (module system Phase 2).

    Direct-grant lookup only — no group/hierarchy inheritance, matching
    `UserModuleRole`'s own documented V1 scope boundary (see that model's
    docstring). `organization_id`/`project_id` are applied as equality
    filters only when given; `require_module_role`'s own callers always
    supply exactly one of them, matching the role's declared scope.
    """
    query = select(UserModuleRole.id).where(
        UserModuleRole.user_id == user_id,
        UserModuleRole.module_key == module_key,
        UserModuleRole.role_key == role_key,
    )
    if organization_id is not None:
        query = query.where(UserModuleRole.organization_id == organization_id)
    if project_id is not None:
        query = query.where(UserModuleRole.project_id == project_id)
    return db.scalar(query) is not None


def require_module_role(module_key: str, role_key: str):
    """FastAPI dependency factory requiring a specific module-contributed
    role, granted via `UserModuleRole` (module system Phase 2).

    Resolves the role's declared `scope` (`"org"` or `"project"`) once, at
    construction time — i.e. when a module's own router calls this factory
    at import time, the same "factory called at router-definition time, not
    at request time" convention `require_server_role`/`require_org_role`/
    `require_org_module_enabled` etc. all already follow. If `module_key`
    isn't registered, or is registered but declares no role with this
    `role_key`, this raises `ValueError` **immediately, at construction
    time** — a router wiring a nonexistent module/role is a code-time
    contract violation to catch during development/import, not something
    that should silently 500 on a live request.

    Depending on the resolved `scope`, the returned dependency is shaped
    exactly like `require_org_module_enabled`'s (`"org"`) or `require_
    project_module_enabled`'s (`"project"`) own inner dependency — same
    path parameter (`organization_id`/`project_id`), same `check_pat_scope`/
    `_require_org_active`/`_require_org_2fa` calls, and the same
    **404-not-403** response when the module is disabled/non-entitled for
    that org (see `require_org_module_enabled`'s own docstring for the
    full "disabled/non-entitled functionality should not be presented,
    indistinguishable from not existing" rationale — it applies identically
    here).

    Once the module-enabled check passes, the caller is authorized if
    **any** of the following hold — composed by design, not left for a
    later phase to discover, mirroring the same "a higher-tier admin
    already retains full access without needing every narrower role
    explicitly granted too" principle `require_server_role`/`require_org_
    role` already rely on for `SERVER_ADMIN`/`ORG_ADMIN`:
      - `current_user.is_server_admin` (always, at every scope).
      - For `scope == "org"`: `OrgRole.ORG_ADMIN` among the caller's
        effective roles on `organization_id`.
      - For `scope == "project"`: `ProjectRole.PROJECT_MANAGER` among the
        caller's effective roles on `project_id`.
      - The caller holds the specific `(module_key, role_key)`
        `UserModuleRole` grant itself (`_has_module_role_grant`), scoped
        to `organization_id`/`project_id` as appropriate.
    Otherwise, 403.

    This is generic module-system infrastructure with **no real caller
    yet** — the same position `require_org_module_enabled`/`require_
    project_module_enabled` were left in after Phase 1, until Phase 5
    registers the first module (Compliance) that actually declares roles
    and wires its own router's endpoints behind this. It is not dead code;
    it is the mechanism every future module's own RBAC gating will use,
    proven here against `tests/test_module_contributed_roles.py`'s fixture
    module in the absence of a real one yet.
    """
    definition = get_module(module_key)
    if definition is None:
        raise ValueError(f"require_module_role: no module registered with key {module_key!r}.")
    role = next((r for r in definition.roles if r.role_key == role_key), None)
    if role is None:
        raise ValueError(
            f"require_module_role: module {module_key!r} declares no role with key {role_key!r}."
        )
    scope = role.scope

    if scope == "org":

        def _org_dependency(
            organization_id: UUID,
            request: Request,
            current_user: User = Depends(get_current_user),
            db: Session = Depends(get_db),
        ) -> User:
            """See the enclosing `require_module_role` factory's docstring
            (org-scoped branch)."""
            check_pat_scope(request, organization_id)
            _require_org_active(db, organization_id)
            _require_org_2fa(db, organization_id, current_user)
            if not is_module_enabled(db, organization_id, module_key):
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
            if current_user.is_server_admin:
                return current_user
            if OrgRole.ORG_ADMIN in get_effective_org_roles(db, current_user.id, organization_id):
                return current_user
            if _has_module_role_grant(
                db, current_user.id, module_key, role_key, organization_id=organization_id
            ):
                return current_user
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions.")

        return _org_dependency

    def _project_dependency(
        project_id: UUID,
        request: Request,
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        """See the enclosing `require_module_role` factory's docstring
        (project-scoped branch)."""
        check_pat_scope_for_project(request, db, project_id)
        organization_id = _project_organization_id(db, project_id)
        if organization_id is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
        _require_org_active(db, organization_id)
        _require_org_2fa(db, organization_id, current_user)
        if not is_module_enabled(db, organization_id, module_key):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
        if current_user.is_server_admin:
            return current_user
        if ProjectRole.PROJECT_MANAGER in get_effective_project_roles(db, current_user.id, project_id):
            return current_user
        if _has_module_role_grant(db, current_user.id, module_key, role_key, project_id=project_id):
            return current_user
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions.")

    return _project_dependency
