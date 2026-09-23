"""
Module: routers.orgs.membership

Organisation membership: creating/listing organisation users (I-M-05,
server-admin-only bootstrap carve-out for the first case), org-only pending
invites, per-user access summaries and directory search, org-role and
org-scoped module-role grant/revoke, self-service leave, admin-initiated
removal, and deactivation/archival (C-U-04, C-U-05).

Split out of the former flat `routers/orgs.py` as a pure code-organization
refactor — see `routers/orgs/__init__.py`'s module docstring for the
package layout.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models.enums import ExternalUserPolicy, OrgRole
from app.models.module_role import UserModuleRole
from app.models.notification import NotificationType
from app.models.organization import Organization, OrgGroup, OrgGroupMember, PendingInvite, UserOrgRole
from app.models.project import Project, ProjectGroup, ProjectGroupMember, UserProjectRole
from app.models.user import User
from app.modules.registry import list_enabled_module_roles
from app.routers.orgs.core import _now
from app.schemas.org import (
    DisplayNameLockUpdate,
    ExternalUserMatch,
    ModuleRoleAssign,
    ModuleRoleDefinitionOut,
    ModuleRoleGrantOut,
    OrgPendingInviteCreate,
    OrgPendingInviteOut,
    OrgRoleAssign,
    OrgUserCreate,
    OrgUserOut,
    OrgUserSearchResult,
    OutsideDomainUserOut,
    UserAccessGroupRef,
    UserAccessOut,
    UserAccessProject,
)
from app.security import hash_password
from app.services import engagement, invites
from app.services.audit import log_event
from app.services.notifications import notify
from app.services.rbac import (
    can_manage_project_settings,
    get_effective_org_roles,
    get_effective_project_managers,
    get_effective_project_roles,
    require_org_admin_or_server_admin,
    require_org_role,
)

router = APIRouter(tags=["organizations-membership"])


@router.post("/{organization_id}/users", response_model=OrgUserOut, status_code=status.HTTP_201_CREATED)
def create_org_user(
    organization_id: UUID,
    payload: OrgUserCreate,
    current_user: User = Depends(require_org_admin_or_server_admin),
    db: Session = Depends(get_db),
):
    """Creates a new user directly within an organisation (I-M-05 clarification).

    Server admins may call this even with no role of their own in the target
    organisation — this is the one documented carve-out (creating the
    initial user of a newly created org). Every other org-scoped endpoint
    requires a genuine org role.
    """
    if db.scalar(select(User).where(User.email == payload.email.lower())) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "A user with this email already exists.")
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    if org.sso_only:
        # A brand-new native-credentialed account whose only org membership
        # is sso_only could never log in (NativeAuthBackend rejects native
        # login when every one of a user's orgs requires SSO) — same guard
        # as self-signup's allow_self_signup/sso_only mutual exclusion.
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "This organisation is SSO-only; native accounts cannot be created for it directly.",
        )
    user = User(
        email=payload.email.lower(),
        display_name=payload.display_name,
        password_hash=hash_password(payload.password),
        auth_backend="native",
    )
    db.add(user)
    db.flush()
    db.add(UserOrgRole(user_id=user.id, organization_id=organization_id, role=payload.role))
    log_event(
        db,
        entity_type="user",
        entity_id=user.id,
        action="created",
        actor_id=current_user.id,
        organization_id=organization_id,
    )
    db.commit()
    return OrgUserOut(
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        is_active=user.is_active,
        is_archived=user.is_archived,
        roles=[payload.role],
    )


@router.get("/{organization_id}/users", response_model=list[OrgUserOut])
def list_org_users(
    organization_id: UUID,
    response: Response,
    stale_since_days: int | None = Query(None, ge=0),
    never_logged_in: bool | None = None,
    has_2fa: bool | None = None,
    org_role: OrgRole | None = None,
    has_project_access: bool | None = None,
    is_active: bool | None = None,
    search: str | None = None,
    sort: str | None = Query(None, pattern="^(display_name|email|last_login_at)$"),
    order: str = Query("asc", pattern="^(asc|desc)$"),
    limit: int | None = Query(None, ge=1),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN, OrgRole.PROJECT_CREATOR, OrgRole.MEMBER)),
    db: Session = Depends(get_db),
):
    """Lists users belonging to an organisation with their org roles.

    Archived users are excluded (C-U-05: an archived user "no longer
    show[s] as users", though their past contributions stay attributed to
    them elsewhere via the unaffected `creator_id`/`actor_id` foreign keys).

    The access-review filters (C-A-13) — `stale_since_days`,
    `never_logged_in`, `has_2fa`, `org_role`, `has_project_access`,
    `is_active` — are org-admin only; a plain member/project-creator can
    still call this endpoint unfiltered for the general member directory
    (existing behavior), but supplying any filter requires org-admin,
    scoped to *this* organisation via `organization_id` (not "an org admin
    somewhere else" — same pattern as every other org-scoped admin check).

    `search` (name/email substring, case-insensitive) and `limit`/`offset`
    (U-P-06, 2026-08 UX audit "Directories at scale") are open to any
    caller who can already reach this endpoint at all — they narrow the
    same directory a plain member can browse, not an access-review signal,
    so they don't require org-admin the way the filters above do. As with
    `list_requirements`, omitting `limit` returns every match unpaginated
    (unchanged from before pagination existed); when given, the total
    match count before slicing is returned via `X-Total-Count`.

    `sort` (2026-08 UX audit roadmap, "Column-header sorting on data
    tables") optionally overrides the default `display_name` sort with
    `email` or `last_login_at`; `order` picks `asc` (default) or `desc`.
    `last_login_at` is nullable (a user who's never logged in) — those
    rows sort last regardless of `order`, so "sort by last login,
    descending" surfaces the most-recently-active users first without
    "never logged in" accounts jumping to the top.
    """
    filters_requested = any(
        v is not None for v in (stale_since_days, never_logged_in, has_2fa, org_role, has_project_access, is_active)
    )
    is_admin = OrgRole.ORG_ADMIN in get_effective_org_roles(db, current_user.id, organization_id)
    if filters_requested and not is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only an organisation admin may use access-review filters.")

    rows = db.execute(
        select(User, UserOrgRole.role).join(UserOrgRole, UserOrgRole.user_id == User.id).where(
            UserOrgRole.organization_id == organization_id, User.is_archived.is_(False)
        )
    ).all()
    by_user: dict[UUID, OrgUserOut] = {}
    for user, role in rows:
        if user.id not in by_user:
            by_user[user.id] = OrgUserOut(
                user_id=user.id,
                email=user.email,
                display_name=user.display_name,
                is_active=user.is_active,
                is_archived=user.is_archived,
                roles=[],
                display_name_locked=user.display_name_locked,
                # C-A-13 access-review data: real values only for org admins
                # (matching the filter gate above) — a plain member calling
                # this same endpoint for the general directory must not
                # receive other members' account-security posture.
                last_login_at=user.last_login_at if is_admin else None,
                is_2fa_enabled=user.is_2fa_enabled if is_admin else False,
            )
        by_user[user.id].roles.append(role)

    # Module system Phase 2: attach each returned user's org-scoped
    # module-contributed role grants, filtered to currently-*enabled*
    # modules only (`list_enabled_module_roles`) — a grant for a
    # since-disabled module is simply omitted here, never deleted from
    # `user_module_roles` (see `ModuleRoleGrantOut`'s own docstring for the
    # full "filter, don't delete" rationale). Computed once per request,
    # not once per user, since it only depends on `organization_id`.
    enabled_org_role_keys = {
        (module_key, role.role_key) for module_key, role in list_enabled_module_roles(db, organization_id, "org")
    }
    if by_user and enabled_org_role_keys:
        module_role_rows = db.execute(
            select(UserModuleRole.user_id, UserModuleRole.module_key, UserModuleRole.role_key).where(
                UserModuleRole.organization_id == organization_id,
                UserModuleRole.project_id.is_(None),
                UserModuleRole.user_id.in_(by_user.keys()),
            )
        ).all()
        for user_id, module_key, role_key in module_role_rows:
            if (module_key, role_key) in enabled_org_role_keys:
                by_user[user_id].module_roles.append(ModuleRoleGrantOut(module_key=module_key, role_key=role_key))

    results = list(by_user.values())
    if is_active is not None:
        results = [r for r in results if r.is_active == is_active]
    if has_2fa is not None:
        results = [r for r in results if r.is_2fa_enabled == has_2fa]
    if org_role is not None:
        results = [r for r in results if org_role in r.roles]
    if never_logged_in:
        results = [r for r in results if r.last_login_at is None]
    if stale_since_days is not None:
        cutoff = datetime.now(UTC) - timedelta(days=stale_since_days)
        results = [r for r in results if r.last_login_at is None or r.last_login_at < cutoff]
    if has_project_access is not None:
        access_ids = _org_users_with_project_access(db, organization_id)
        results = [r for r in results if (r.user_id in access_ids) == has_project_access]
    if search:
        needle = search.lower()
        results = [r for r in results if needle in r.display_name.lower() or needle in r.email.lower()]

    if sort and sort != "display_name":
        def _sort_value(item: OrgUserOut):
            value = getattr(item, sort)
            if sort == "last_login_at":
                # Nulls (never logged in) always sort last, in either
                # direction — see docstring.
                return (value is None, value)
            return value.lower()
        results.sort(key=_sort_value, reverse=(order == "desc"))
    else:
        results.sort(key=lambda r: r.display_name.lower(), reverse=(sort == "display_name" and order == "desc"))

    response.headers["X-Total-Count"] = str(len(results))
    if limit is not None:
        results = results[offset:offset + limit]
    return results


def _org_pending_invite_out(invite: PendingInvite, db: Session) -> OrgPendingInviteOut:
    """Shared status computation for the two endpoints below — mirrors
    `routers/projects.py::_pending_invite_out` (status derived from
    `expires_at` at read time, not stored), plus resolving `invited_by` to
    a display name: the org-level Users table shows who sent each invite,
    unlike the project-level table which doesn't surface that column
    today."""
    inviter = db.get(User, invite.invited_by)
    return OrgPendingInviteOut(
        id=invite.id,
        email=invite.email,
        status="pending" if invite.expires_at > datetime.now(UTC) else "expired",
        created_at=invite.created_at,
        expires_at=invite.expires_at,
        invited_by_display_name=inviter.display_name if inviter is not None else "?",
    )


def _get_org_only_pending_invite(db: Session, organization_id: UUID, invite_id: UUID) -> PendingInvite:
    """Loads a `PendingInvite` and 404s unless it's an org-only invite
    (`project_id IS NULL`) belonging to `organization_id` — mirrors
    `routers/projects.py::_get_pending_invite_in_project`'s cross-boundary
    guard. Without this, an org admin could pass a *project-scoped*
    invite's id (or one belonging to a different organisation) and resend
    it via this org-level endpoint, rotating its token and re-sending its
    email outside the project-level gate that actually owns it."""
    invite = db.get(PendingInvite, invite_id)
    if invite is None or invite.organization_id != organization_id or invite.project_id is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invite not found.")
    return invite


@router.get("/{organization_id}/pending-invites", response_model=list[OrgPendingInviteOut])
def list_org_pending_invites(
    organization_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """Lists this organisation's outstanding (unaccepted) org-only
    `PendingInvite`s, most recent first — `project_id IS NULL` only.
    Project-scoped invites (created via a project's by-email add-user flow)
    stay owned by `routers/projects.py::list_pending_project_invites` and
    are never double-listed here (Phase A, follow-up UX batch;
    docs/decisions.md).

    `require_org_role(ORG_ADMIN)` — deliberately **no** server-admin
    bypass. This previously reused `require_org_admin_or_server_admin`
    (`create_org_user`'s dependency), which is documented in that
    dependency's own docstring and in I-M-05's hardening-pass entry
    (docs/decisions.md) as a single, narrow carve-out for bootstrapping the
    *first* user of a brand-new org. Listing/creating/resending invites has
    no such bootstrap need — the org already has an admin by the time
    these are reachable — so letting an org-uninvolved server admin read
    invitee PII and seed new members into an arbitrary organisation was a
    real regression against I-M-05's "does not give access to data within
    organisations" invariant, not a legitimate extension of it. Fixed as
    part of a hardening pass (see decisions.md's I-M-05 entry addendum).
    """
    invites_list = db.scalars(
        select(PendingInvite)
        .where(
            PendingInvite.organization_id == organization_id,
            PendingInvite.project_id.is_(None),
            PendingInvite.accepted_at.is_(None),
        )
        .order_by(PendingInvite.created_at.desc())
    ).all()
    return [_org_pending_invite_out(invite, db) for invite in invites_list]


@router.post(
    "/{organization_id}/pending-invites", response_model=OrgPendingInviteOut, status_code=status.HTTP_201_CREATED
)
def create_org_pending_invite(
    organization_id: UUID,
    payload: OrgPendingInviteCreate,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """Invites a new user into the organisation by email — the org-level
    "Invite user" action (Phase A, follow-up UX batch), distinct from
    `create_org_user`'s "New user" (an immediate password-based account).
    The invitee sets their own display name/password at signup via the
    emailed link and is granted `OrgRole.MEMBER` on redemption
    (`services.invites.consume_pending_invites`); an admin can promote them
    afterward via the existing role-grant control, same as any other user.

    Thin wrapper over `services.invites.create_pending_invite` with
    `project=None`/`project_role=None` (an org-only invite).

    `org.sso_only` is rejected with 400, mirroring `create_org_user`'s own
    guard for the same reason: there is no working native-signup path to
    redeem a token against for an `sso_only` org (native login is blocked
    outright once every one of a user's orgs requires SSO). Unlike
    `assign_project_role_by_email`'s sso_only branch — which provisions a
    project role immediately via `provision_sso_invite` because it already
    knows which project/role to grant — a bare org-only "invite" has no
    such target to provision ahead of a real SSO login, so a straight
    reject (matching `create_org_user`'s existing message shape) is the
    correct scope here rather than introducing a second, invite-shaped
    response type for an immediate-provision outcome. An org admin who
    needs to pre-add a specific person to an `sso_only` org can still do so
    once that person's IdP group/role claim is configured to match on
    first SSO login.
    """
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    if org.sso_only:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "This organisation is SSO-only; email invites are not used — access is provisioned at SSO login.",
        )
    email = payload.email.lower()
    if db.scalar(select(User).where(User.email == email)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "A user with this email already exists.")
    invite = invites.create_pending_invite(
        db, email=email, organization=org, project=None, project_role=None, invited_by=current_user.id,
    )
    log_event(
        db, entity_type="pending_invite", entity_id=invite.id, action="invited",
        actor_id=current_user.id, organization_id=organization_id, detail={"email": email},
    )
    db.commit()
    return _org_pending_invite_out(invite, db)


@router.post("/{organization_id}/pending-invites/{invite_id}/resend", response_model=OrgPendingInviteOut)
def resend_org_pending_invite(
    organization_id: UUID, invite_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """Rotates the invite's token/`expires_at` and re-sends the signup-link
    email — the org-level counterpart to
    `routers/projects.py::resend_pending_project_invite`, same behavior
    (works whether the invite is still pending or already expired; only an
    already-*accepted* invite is rejected, since there's nothing left to
    resend once someone's redeemed it).
    """
    invite = _get_org_only_pending_invite(db, organization_id, invite_id)
    if invite.accepted_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This invite has already been accepted.")
    org = db.get(Organization, organization_id)
    invites.resend_pending_invite(db, invite, organization=org, project=None)
    log_event(
        db, entity_type="pending_invite", entity_id=invite.id, action="invite_resent",
        actor_id=current_user.id, organization_id=organization_id, detail={"email": invite.email},
    )
    db.commit()
    return _org_pending_invite_out(invite, db)


@router.get("/{organization_id}/users/{user_id}/access", response_model=UserAccessOut)
def get_user_access(
    organization_id: UUID,
    user_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """One user's access within this organisation (2026-08 UX audit, sixth
    pass: "No way to view a user's access") — every project in the org
    where the user holds at least one effective role, that role set, which
    of the project's own groups they're a direct member of, and which org
    groups they directly belong to.

    Computed server-side via the existing `get_effective_project_roles`
    (direct assignment, direct/nested project-group membership, or
    org-wide project visibility — the same resolution every permission
    check in the app already relies on) rather than re-derived per project
    on the frontend, both for correctness (one algorithm, not two) and to
    avoid an N-project fan-out of round trips from the client.
    """
    if db.get(User, user_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")

    org_group_rows = db.execute(
        select(OrgGroup.id, OrgGroup.name)
        .join(OrgGroupMember, OrgGroupMember.org_group_id == OrgGroup.id)
        .where(OrgGroup.organization_id == organization_id, OrgGroupMember.user_id == user_id)
        .order_by(OrgGroup.name)
    ).all()
    org_groups = [UserAccessGroupRef(id=row.id, name=row.name) for row in org_group_rows]

    projects: list[UserAccessProject] = []
    for project in db.scalars(
        select(Project).where(Project.organization_id == organization_id).order_by(Project.name)
    ).all():
        roles = get_effective_project_roles(db, user_id, project.id)
        if not roles:
            continue
        project_group_rows = db.execute(
            select(ProjectGroup.id, ProjectGroup.name)
            .join(ProjectGroupMember, ProjectGroupMember.project_group_id == ProjectGroup.id)
            .where(ProjectGroup.project_id == project.id, ProjectGroupMember.user_id == user_id)
            .order_by(ProjectGroup.name)
        ).all()
        projects.append(UserAccessProject(
            project_id=project.id, project_name=project.name,
            roles=sorted(roles, key=lambda r: r.value),
            project_groups=[UserAccessGroupRef(id=row.id, name=row.name) for row in project_group_rows],
        ))

    return UserAccessOut(org_groups=org_groups, projects=projects)


def _looks_like_email(value: str) -> bool:
    """Cheap "looks like an email" heuristic for the external-user-match
    check below — not full RFC 5322 validation (see `email-validator`,
    used for real signup/invite validation elsewhere).

    Deliberately plain string operations rather than a single
    `^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$`-style regex: that shape is
    polynomial-time on crafted input (many `.`s after the `@`), and `value`
    here is `q` — an unauthenticated-adjacent, attacker-controlled search
    query (CodeQL py/polynomial-redos). This reproduces the same
    match/no-match semantics — nonempty local part, exactly one `@`, no
    whitespace, and a domain `.` with at least one character on each
    side — in linear time.
    """
    if not value or len(value) > 320 or any(ch.isspace() for ch in value):
        return False
    local, sep, domain = value.partition("@")
    if not sep or not local or "@" in domain:
        return False
    return any(0 < i < len(domain) - 1 for i, ch in enumerate(domain) if ch == ".")


@router.get("/{organization_id}/users/search", response_model=OrgUserSearchResult)
def search_org_users(
    organization_id: UUID,
    q: str = Query(..., min_length=1),
    project_id: UUID | None = Query(None),
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN, OrgRole.PROJECT_CREATOR, OrgRole.MEMBER)),
    db: Session = Depends(get_db),
):
    """Server-backed search for the project user picker: org members
    matching `q` by name/email, plus — only when `q` is a full email
    address not already among the org's members and
    `Organization.external_user_policy` allows it — a synthetic "external"
    result the caller can then add via
    `routers/projects.py::assign_project_role_by_email`.

    Whether `q` matches an *existing* account elsewhere in the system is
    itself a cross-tenant fact (a one-bit "this exact email has an account
    somewhere" signal) — unlike "no account, would need an invite," which
    reveals nothing about any real account and is always safe to return.
    This endpoint is open to any org member (matching `list_org_users`'
    existing directory precedent), but that's a materially lower bar than
    `assign_project_role_by_email`'s own `require_project_manage` gate, so
    the `exists=True` case is withheld from a caller who couldn't actually
    act on it: an org admin, or a member who passes `project_id` for a
    project in this org they have manage rights on. Below that bar, a
    match that would resolve to `exists=True` is omitted entirely rather
    than downgraded to a misleading `exists=False`.
    """
    needle = q.strip().lower()
    rows = db.execute(
        select(User, UserOrgRole.role).join(UserOrgRole, UserOrgRole.user_id == User.id).where(
            UserOrgRole.organization_id == organization_id, User.is_archived.is_(False)
        )
    ).all()
    by_user: dict[UUID, OrgUserOut] = {}
    for user, role in rows:
        if needle not in user.display_name.lower() and needle not in user.email.lower():
            continue
        if user.id not in by_user:
            by_user[user.id] = OrgUserOut(
                user_id=user.id, email=user.email, display_name=user.display_name,
                is_active=user.is_active, is_archived=user.is_archived, roles=[],
                display_name_locked=user.display_name_locked,
            )
        by_user[user.id].roles.append(role)
    members = list(by_user.values())[:8]

    external: ExternalUserMatch | None = None
    if _looks_like_email(needle) and not any(m.email.lower() == needle for m in members):
        org = db.get(Organization, organization_id)
        policy = org.external_user_policy if org else ExternalUserPolicy.DISABLED
        if policy != ExternalUserPolicy.DISABLED:
            existing = db.scalar(select(User).where(User.email == needle))
            if existing is not None:
                may_see_existing = OrgRole.ORG_ADMIN in get_effective_org_roles(db, current_user.id, organization_id)
                if not may_see_existing and project_id is not None:
                    project = db.get(Project, project_id)
                    if project is not None and project.organization_id == organization_id:
                        may_see_existing = can_manage_project_settings(db, current_user, project)
                if may_see_existing:
                    external = ExternalUserMatch(email=needle, exists=True)
            else:
                domain = needle.rsplit("@", 1)[-1]
                domain_ok = policy == ExternalUserPolicy.ANYONE or (
                    policy == ExternalUserPolicy.ORG_DOMAIN_ONLY
                    and org is not None
                    and org.auto_accept_email_domain
                    and org.auto_accept_email_domain.lower() == domain
                )
                if domain_ok:
                    external = ExternalUserMatch(email=needle, exists=False)
    return OrgUserSearchResult(members=members, external=external)


@router.get("/{organization_id}/users/outside-domain", response_model=list[OutsideDomainUserOut])
def list_outside_domain_users(
    organization_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """Lists existing users (system-wide, not archived) whose email domain
    matches this org's configured `auto_accept_email_domain` but who are
    not currently members — lets an org admin see who's eligible to be
    invited once a domain has been configured (bullet 5 of the
    self-signup/external-user feature set)."""
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    if not org.auto_accept_email_domain:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This organisation has no email domain configured.")
    member_ids = set(
        db.scalars(select(UserOrgRole.user_id).where(UserOrgRole.organization_id == organization_id)).all()
    )
    domain_suffix = f"@{org.auto_accept_email_domain.lower()}"
    candidates = db.scalars(select(User).where(User.is_archived.is_(False))).all()
    return [
        OutsideDomainUserOut(user_id=u.id, email=u.email, display_name=u.display_name)
        for u in candidates
        if u.id not in member_ids and u.email.lower().endswith(domain_suffix)
    ]


def _org_users_with_project_access(db: Session, organization_id: UUID) -> set[UUID]:
    """User ids with at least one direct project role or direct project-group
    membership on any project in this organisation (used by the
    `has_project_access` access-review filter, C-A-13). Direct resolution
    only, not nested org groups — matches the same scope already used by
    `get_effective_project_managers` for similar bulk/administrative queries."""
    direct_role_ids = set(
        db.scalars(
            select(UserProjectRole.user_id)
            .join(Project, Project.id == UserProjectRole.project_id)
            .where(Project.organization_id == organization_id)
        ).all()
    )
    direct_group_ids = set(
        db.scalars(
            select(ProjectGroupMember.user_id)
            .join(ProjectGroup, ProjectGroup.id == ProjectGroupMember.project_group_id)
            .join(Project, Project.id == ProjectGroup.project_id)
            .where(Project.organization_id == organization_id, ProjectGroupMember.user_id.is_not(None))
        ).all()
    )
    return direct_role_ids | direct_group_ids


@router.put("/{organization_id}/users/{user_id}/display-name-lock", status_code=status.HTTP_204_NO_CONTENT)
def set_display_name_lock(
    organization_id: UUID,
    user_id: UUID,
    payload: DisplayNameLockUpdate,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """Locks or unlocks a user's ability to change their own display name (C-U-16)."""
    user = db.get(User, user_id)
    if user is None or not get_effective_org_roles(db, user_id, organization_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found in this organisation.")
    user.display_name_locked = payload.display_name_locked
    log_event(
        db,
        entity_type="user",
        entity_id=user_id,
        action="display_name_lock_changed",
        actor_id=current_user.id,
        organization_id=organization_id,
        detail={"display_name_locked": payload.display_name_locked},
    )
    db.commit()


@router.post("/{organization_id}/users/{user_id}/roles", status_code=status.HTTP_204_NO_CONTENT)
def assign_org_role(
    organization_id: UUID,
    user_id: UUID,
    payload: OrgRoleAssign,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """Grants an organisation role to a user (C-U-01).

    The affected user is always the `{user_id}` path parameter, not
    `payload.user_id` — the request body's `role` field is the only part of
    the payload actually used; a mismatched body `user_id` is ignored rather
    than trusted, so the URL a caller is authorized against (and what ends
    up in the audit trail) can never diverge from who is actually affected.
    """
    target = db.get(User, user_id)
    if target is not None and target.is_banned:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "This user has been banned by a server admin and cannot be granted a role."
        )
    existing = db.scalar(
        select(UserOrgRole).where(
            UserOrgRole.user_id == user_id,
            UserOrgRole.organization_id == organization_id,
            UserOrgRole.role == payload.role,
        )
    )
    if existing is None:
        db.add(UserOrgRole(user_id=user_id, organization_id=organization_id, role=payload.role))
        log_event(
            db,
            entity_type="user_org_role",
            entity_id=user_id,
            action="granted",
            actor_id=current_user.id,
            organization_id=organization_id,
            detail={"role": payload.role.value},
        )
        granted_user = db.get(User, user_id)
        if granted_user is not None:
            notify(
                db, granted_user, notification_type=NotificationType.PERMISSION_GRANTED,
                title="Organisation permission granted",
                body=f"You were granted the '{payload.role.value}' role in an organisation.",
                actor_id=current_user.id,
            )
        db.commit()


@router.delete("/{organization_id}/users/{user_id}/roles/{role}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_org_role(
    organization_id: UUID,
    user_id: UUID,
    role: OrgRole,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """Revokes an organisation role from a user — `assign_org_role`'s
    counterpart, which had none until now (hierarchical projects surfaced
    this as a real, pre-existing gap: see docs/decisions.md's "Hierarchical
    projects" entry). No-op if the user doesn't currently hold `role`.

    Blocks the caller from targeting their own account, the same guard
    `deactivate_org_user` already uses for the same reason: since this
    endpoint requires the caller to already hold `ORG_ADMIN` (never derived
    indirectly, unlike project roles) and self-targeting is blocked, the
    calling admin's own admin-ness is untouched by any revoke they perform
    on someone else — so an organisation can never reach zero admins
    through this endpoint, by construction, with no separate "last admin"
    count check needed.
    """
    if user_id == current_user.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot revoke your own organisation role.")
    existing = db.scalar(
        select(UserOrgRole).where(
            UserOrgRole.user_id == user_id, UserOrgRole.organization_id == organization_id, UserOrgRole.role == role
        )
    )
    if existing is not None:
        db.delete(existing)
        log_event(
            db, entity_type="user_org_role", entity_id=user_id, action="revoked", actor_id=current_user.id,
            organization_id=organization_id, detail={"role": role.value},
        )
        db.commit()


@router.get("/{organization_id}/module-roles", response_model=list[ModuleRoleDefinitionOut])
def list_org_module_roles(
    organization_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN, OrgRole.PROJECT_CREATOR, OrgRole.MEMBER)),
    db: Session = Depends(get_db),
):
    """Lists the org-scoped module-contributed roles currently available to
    grant in this organisation — i.e. declared by a module that is
    currently effectively enabled here (module system Phase 2). Same
    "any org member can see what role options exist" gate as `list_org_
    users` (C-A-13's own filters are the only part of that endpoint
    actually restricted to admins; the option list itself isn't
    sensitive), since this is exactly what the frontend's Roles dropdown
    needs to render its option list alongside the fixed `OrgRole` values.
    """
    return [
        ModuleRoleDefinitionOut(module_key=module_key, role_key=role.role_key, name=role.name, description=role.description)
        for module_key, role in list_enabled_module_roles(db, organization_id, "org")
    ]


@router.post("/{organization_id}/users/{user_id}/module-roles", status_code=status.HTTP_204_NO_CONTENT)
def assign_org_module_role(
    organization_id: UUID,
    user_id: UUID,
    payload: ModuleRoleAssign,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """Grants an org-scoped module-contributed role to a user (module
    system Phase 2) — the module-role counterpart to `assign_org_role`,
    same `ORG_ADMIN`-only gate (an org admin already implicitly holds
    every org-scoped module role via `require_module_role`'s own override,
    so it's consistent that org admin is also who explicitly grants/
    revokes the row).

    400s if `(payload.module_key, payload.role_key)` doesn't name a real
    `scope="org"` role of a *currently-enabled* module for this
    organisation — this is what naturally makes a disabled module's roles
    ungrantable, and also catches a typo'd role key, using the same
    `list_enabled_module_roles` lookup `list_org_module_roles` above
    exposes as the frontend's own option list.
    """
    target = db.get(User, user_id)
    if target is not None and target.is_banned:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "This user has been banned by a server admin and cannot be granted a role."
        )
    valid = any(
        module_key == payload.module_key and role.role_key == payload.role_key
        for module_key, role in list_enabled_module_roles(db, organization_id, "org")
    )
    if not valid:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "This module role does not exist, is not org-scoped, or its module is not currently enabled for this organisation.",
        )
    existing = db.scalar(
        select(UserModuleRole).where(
            UserModuleRole.user_id == user_id,
            UserModuleRole.module_key == payload.module_key,
            UserModuleRole.role_key == payload.role_key,
            UserModuleRole.organization_id == organization_id,
            UserModuleRole.project_id.is_(None),
        )
    )
    if existing is None:
        db.add(
            UserModuleRole(
                user_id=user_id, module_key=payload.module_key, role_key=payload.role_key,
                organization_id=organization_id, granted_by=current_user.id,
            )
        )
        log_event(
            db, entity_type="user_module_role", entity_id=user_id, action="granted",
            actor_id=current_user.id, organization_id=organization_id,
            detail={"module_key": payload.module_key, "role_key": payload.role_key},
        )
        granted_user = db.get(User, user_id)
        if granted_user is not None:
            notify(
                db, granted_user, notification_type=NotificationType.PERMISSION_GRANTED,
                title="Organisation permission granted",
                body=f"You were granted the '{payload.role_key}' role in an organisation.",
                actor_id=current_user.id,
            )
        db.commit()


@router.delete(
    "/{organization_id}/users/{user_id}/module-roles/{module_key}/{role_key}", status_code=status.HTTP_204_NO_CONTENT
)
def revoke_org_module_role(
    organization_id: UUID,
    user_id: UUID,
    module_key: str,
    role_key: str,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """Revokes an org-scoped module-contributed role grant — `assign_org_
    module_role`'s counterpart, same no-op-if-absent shape as `revoke_org_
    role`. Unlike `revoke_org_role`, no self-targeting guard is needed: an
    org can never reach "zero admins" through a module-role revoke, since
    module roles carry no admin-tier significance of their own (an
    `ORG_ADMIN` retains full access to every org-scoped module role
    regardless of this table's contents — see `require_module_role`)."""
    existing = db.scalar(
        select(UserModuleRole).where(
            UserModuleRole.user_id == user_id,
            UserModuleRole.module_key == module_key,
            UserModuleRole.role_key == role_key,
            UserModuleRole.organization_id == organization_id,
            UserModuleRole.project_id.is_(None),
        )
    )
    if existing is not None:
        db.delete(existing)
        log_event(
            db, entity_type="user_module_role", entity_id=user_id, action="revoked", actor_id=current_user.id,
            organization_id=organization_id, detail={"module_key": module_key, "role_key": role_key},
        )
        db.commit()


@router.delete("/{organization_id}/membership", status_code=status.HTTP_204_NO_CONTENT)
def leave_organization(
    organization_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Self-service: the caller removes their own membership in an organisation.

    Previously there was no way for a user to leave an org at all — see
    docs/e2e-workflows.md's "product gaps found" section, which this closes.

    Refuses (409) rather than silently reassigning anyone else's roles if
    leaving would strip the organisation of its last org_admin, or leave any
    of its projects with zero managers. Unlike `deactivate_org_user`'s C-U-09
    fallback (which reassigns the *acting admin* as a project's new manager
    when removing someone else), there is no natural recipient for that
    reassignment here — the caller is the one leaving — so this endpoint
    asks the caller to reassign those roles first instead of guessing who
    should inherit them.

    Also removes the caller's `OrgGroupMember` rows for this organisation's
    groups, not just their direct project roles/memberships — project access
    can be granted through an org group nested into a project group (C-U-12),
    and `get_effective_project_managers` (used for the sole-manager guard below)
    deliberately only resolves *direct* managers, not nested-group-derived
    ones (see its own docstring). Leaving that cleanup out would let a user
    "leave" an org while silently retaining full project access through a
    still-active session — this endpoint checks both direct and
    nested-group-derived manager status precisely because of that gap.

    Locks the organisation row for the duration of this transaction
    (`lock_organization_for_update`) before doing anything else, and each
    project row in turn before checking its manager count
    (`lock_project_for_update`) — without this, two concurrent leavers (e.g.
    an org's last two admins, or a project's last two managers, each leaving
    at once) could each see the other as still-present backup and both
    proceed, since neither transaction's check would see the other's
    not-yet-committed removal.
    """
    from app.services.rbac import lock_organization_for_update, lock_project_for_update

    lock_organization_for_update(db, organization_id)

    roles = get_effective_org_roles(db, current_user.id, organization_id)
    if not roles:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "You are not a member of this organisation.")

    if OrgRole.ORG_ADMIN in roles:
        other_admins = db.scalars(
            select(UserOrgRole.user_id).where(
                UserOrgRole.organization_id == organization_id,
                UserOrgRole.role == OrgRole.ORG_ADMIN,
                UserOrgRole.user_id != current_user.id,
            )
        ).all()
        if not other_admins:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "You are this organisation's only admin. Assign another admin before leaving.",
            )

    from app.models.enums import ProjectRole  # local import matching this module's existing convention
    from app.models.project import Project, ProjectGroup  # local import to avoid cycle at module load
    from app.services.rbac import get_effective_project_roles

    projects = db.scalars(select(Project).where(Project.organization_id == organization_id)).all()
    blocking_projects = []
    for p in projects:
        lock_project_for_update(db, p.id)
        concrete_managers = get_effective_project_managers(db, p.id)
        # Fold in nested-org-group-derived PM status too: get_effective_project_managers
        # only resolves direct assignments/direct group membership, so a
        # manager role held solely via a nested org group would otherwise be
        # invisible here, letting this guard miss a soon-to-be-orphaned
        # project (its only "manager" isn't a *concrete* manager per
        # get_effective_project_managers' own definition, but removing this user's
        # nested-group access below would still leave nobody with the role).
        i_am_manager = current_user.id in concrete_managers or ProjectRole.PROJECT_MANAGER in get_effective_project_roles(
            db, current_user.id, p.id
        )
        if i_am_manager and not (concrete_managers - {current_user.id}):
            blocking_projects.append(p.name)
    if blocking_projects:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "You are the sole manager of: " + ", ".join(blocking_projects) + ". Assign another manager first.",
        )

    project_ids = [p.id for p in projects]
    if project_ids:
        db.execute(
            UserProjectRole.__table__.delete().where(
                UserProjectRole.user_id == current_user.id, UserProjectRole.project_id.in_(project_ids)
            )
        )
        db.execute(
            ProjectGroupMember.__table__.delete().where(
                ProjectGroupMember.user_id == current_user.id,
                ProjectGroupMember.project_group_id.in_(
                    select(ProjectGroup.id).where(ProjectGroup.project_id.in_(project_ids))
                ),
            )
        )
    db.execute(
        OrgGroupMember.__table__.delete().where(
            OrgGroupMember.user_id == current_user.id,
            OrgGroupMember.org_group_id.in_(
                select(OrgGroup.id).where(OrgGroup.organization_id == organization_id)
            ),
        )
    )
    engagement.remove_subscriptions_and_favorites_for_projects(db, current_user.id, project_ids)

    db.execute(
        UserOrgRole.__table__.delete().where(
            UserOrgRole.user_id == current_user.id, UserOrgRole.organization_id == organization_id
        )
    )
    log_event(
        db, entity_type="user_org_role", entity_id=current_user.id, action="left_organization",
        actor_id=current_user.id, organization_id=organization_id,
    )
    db.commit()


@router.delete("/{organization_id}/users/{user_id}/membership", status_code=status.HTTP_204_NO_CONTENT)
def remove_org_user(
    organization_id: UUID,
    user_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """Admin-initiated counterpart to `leave_organization` above (PR6 of the
    members/groups directory rework plan, docs/decisions.md — `OrgAdminPage
    .tsx`'s Users table Actions column, "Remove from {org}"): an org admin
    removes *another* user's membership in `organization_id`, rather than
    the user removing their own. No prior admin-initiated removal endpoint
    existed (`deactivate_org_user` below sets `is_active=False` on the
    whole account, a cross-org lockout, not a per-org membership removal;
    `archive_org_user` only hides an already-deactivated user from lists) —
    this fills that specific gap: removing this org's `UserOrgRole` row(s)
    without touching the account's standing in any other organisation.

    Treated as access-mutating (identify -> verify -> remediate review,
    docs/decisions.md), so it is deliberately built as a close mirror of
    `leave_organization`'s own already-reviewed cleanup and guards, not a
    bare `UserOrgRole` delete:

    - **Self-targeting is blocked** (400) — same reasoning as
      `deactivate_org_user`/`revoke_org_role`: an admin removing *their
      own* org membership has its own, already-correct path
      (`leave_organization`, which additionally lets a departing admin
      reassign responsibilities before leaving) — this endpoint isn't a
      second, less-guarded way to reach that same end state.
    - **No separate last-admin count check** — same "by construction"
      reasoning `revoke_org_role` already documents for itself, not
      `leave_organization`'s reachable one: this endpoint requires the
      *caller* to already hold `ORG_ADMIN` on `organization_id`
      (`require_org_role` below), and self-targeting is blocked above, so
      the caller is necessarily a *second*, distinct `ORG_ADMIN` still
      present after `user_id`'s membership is removed — an organisation
      can never reach zero admins through this endpoint, for any `user_id`
      it's ever legal to call it with. (`leave_organization`'s own count
      check is reachable precisely because there caller and target are the
      *same* person — the case blocked here.)
    - **Sole-project-manager guard**: refuses (409) if `user_id` is the
      sole real manager of any project in this org — same check
      `leave_organization` already applies to the leaving user, applied
      here to the user being removed, so an admin can't accidentally
      orphan a project of managers by removing someone through this
      endpoint that `leave_organization` would have refused to let them
      remove themselves as.
    - **Cleanup**: every direct `UserProjectRole` and `ProjectGroupMember`
      row for `user_id` across this org's projects, every `OrgGroupMember`
      row for this org's groups, and subscriptions/favorites for this org's
      projects — same shape `leave_organization` already performs for the
      caller, applied here to `user_id`. This org's own `UserOrgRole` rows
      are deleted last, after every dependent cleanup succeeds.
    - Row-locks the organisation before the last-admin guard, and each
      project in turn before that project's own sole-manager check
      (`lock_organization_for_update`/`lock_project_for_update`) — same
      ordering, and the same concurrent-removal race, `leave_organization`'s
      own docstring describes.

    A no-op (still 204) if `user_id` is not currently a member of
    `organization_id` at all — removing a non-member has nothing to do,
    matching `leave_organization`'s own "not a member" 404 being the only
    case that actually errors instead (kept as a 404 here too, for the same
    "you can't remove someone who isn't there" reason).
    """
    from app.models.enums import ProjectRole  # local import matching leave_organization's own convention
    from app.services.rbac import lock_organization_for_update, lock_project_for_update

    if user_id == current_user.id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Use the leave-organisation action to remove your own membership."
        )

    lock_organization_for_update(db, organization_id)

    roles = get_effective_org_roles(db, user_id, organization_id)
    if not roles:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found in this organisation.")

    projects = db.scalars(select(Project).where(Project.organization_id == organization_id)).all()
    blocking_projects = []
    for p in projects:
        lock_project_for_update(db, p.id)
        concrete_managers = get_effective_project_managers(db, p.id)
        i_am_manager = user_id in concrete_managers or ProjectRole.PROJECT_MANAGER in get_effective_project_roles(
            db, user_id, p.id
        )
        if i_am_manager and not (concrete_managers - {user_id}):
            blocking_projects.append(p.name)
    if blocking_projects:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This user is the sole manager of: " + ", ".join(blocking_projects) + ". Assign another manager first.",
        )

    project_ids = [p.id for p in projects]
    if project_ids:
        db.execute(
            UserProjectRole.__table__.delete().where(
                UserProjectRole.user_id == user_id, UserProjectRole.project_id.in_(project_ids)
            )
        )
        db.execute(
            ProjectGroupMember.__table__.delete().where(
                ProjectGroupMember.user_id == user_id,
                ProjectGroupMember.project_group_id.in_(
                    select(ProjectGroup.id).where(ProjectGroup.project_id.in_(project_ids))
                ),
            )
        )
    db.execute(
        OrgGroupMember.__table__.delete().where(
            OrgGroupMember.user_id == user_id,
            OrgGroupMember.org_group_id.in_(
                select(OrgGroup.id).where(OrgGroup.organization_id == organization_id)
            ),
        )
    )
    engagement.remove_subscriptions_and_favorites_for_projects(db, user_id, project_ids)

    db.execute(
        UserOrgRole.__table__.delete().where(
            UserOrgRole.user_id == user_id, UserOrgRole.organization_id == organization_id
        )
    )
    log_event(
        db, entity_type="user_org_role", entity_id=user_id, action="removed_from_organization",
        actor_id=current_user.id, organization_id=organization_id,
    )
    db.commit()


@router.post("/{organization_id}/users/{user_id}/deactivate", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_org_user(
    organization_id: UUID,
    user_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """Deactivates a user (C-U-04).

    Applies the C-U-09 fallback: for any project where this removal leaves
    no remaining project manager, the acting admin is assigned as manager so
    the project is never left without one (C-U-08). Each project is row-
    locked (`lock_project_for_update`) before its manager count is checked,
    so this can't race a concurrent removal (another deactivation, a role
    revocation, or someone leaving the org) on the same project — see
    `lock_project_for_update`'s docstring for the exact race this closes.

    The target user must actually be a member of `organization_id` — an org
    admin's authority to deactivate accounts is scoped to their own
    organisation's members, same as every other org-scoped action, not to
    every account in the deployment (SOC 2 access-control hardening pass).

    Guard added by a later hardening review: refuses to let a caller
    target their own account. This endpoint had no protection at all
    against ending an organisation's last active admin, unlike the
    conceptually similar `leave_organization` — but the actual fix is
    simpler than mirroring that endpoint's own "are there other admins"
    check would suggest: since this endpoint requires the *caller* to
    already hold `org_admin` on this exact organisation (`require_org_role`
    above) and org_admin is never derived indirectly (unlike project
    roles, which can come from a group), the calling admin's own role
    necessarily survives any deactivation they perform on someone *else* —
    so once self-targeting is blocked, an organisation can never reach zero
    active admins through this endpoint at all, by construction, with
    nothing further to check. Unlike `leave_organization` (which only ends
    *this org's* membership), deactivation here sets `is_active=False` on
    the whole account, locking the caller out of every organisation, not
    just this one — an org-scoped admin action is not the place for that
    scale of self-inflicted, cross-org lockout to happen with no
    confirmation step, which is the concrete harm this guard closes.
    """
    from app.services.rbac import lock_project_for_update

    if user_id == current_user.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Use the leave-organisation action to remove your own membership.")

    user = db.get(User, user_id)
    if user is None or not get_effective_org_roles(db, user_id, organization_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found in this organisation.")
    user.is_active = False
    user.deactivated_at = _now()

    from app.models.project import Project  # local import to avoid cycle at module load

    projects = db.scalars(select(Project).where(Project.organization_id == organization_id)).all()
    for project in projects:
        lock_project_for_update(db, project.id)

    # Hierarchical projects (docs/decisions.md): a project's effective
    # manager set can now be pulled from a *different* project (forward
    # inheritance) in this same org, so this loop's own per-project deletes
    # can no longer be interleaved with its own C-U-08 checks — a project
    # whose only manager was actually inherited from a not-yet-processed
    # sibling in this same loop would look fine at check time and only lose
    # its manager once THAT project's turn came, with the fallback never
    # triggered for it. Every one of this user's direct/group roles across
    # every project in this org is deleted first, in one upfront pass, so
    # every later fallback check runs against fully up-to-date state.
    managers_before_by_project = {
        project.id: user_id in get_effective_project_managers(db, project.id) for project in projects
    }
    for project in projects:
        db.execute(
            UserProjectRole.__table__.delete().where(
                UserProjectRole.user_id == user_id, UserProjectRole.project_id == project.id
            )
        )
    db.execute(ProjectGroupMember.__table__.delete().where(ProjectGroupMember.user_id == user_id))

    for project in projects:
        if not managers_before_by_project[project.id]:
            continue
        remaining = get_effective_project_managers(db, project.id) - {user_id}
        if not remaining:
            from app.models.enums import ProjectRole

            db.add(UserProjectRole(user_id=current_user.id, project_id=project.id, role=ProjectRole.PROJECT_MANAGER))
            log_event(
                db,
                entity_type="project",
                entity_id=project.id,
                action="manager_fallback_assigned",
                actor_id=current_user.id,
                project_id=project.id,
                detail={"assigned_to": str(current_user.id), "reason": "last_manager_deactivated"},
            )

    log_event(
        db,
        entity_type="user",
        entity_id=user_id,
        action="deactivated",
        actor_id=current_user.id,
        organization_id=organization_id,
    )
    db.commit()


@router.post("/{organization_id}/users/{user_id}/archive", status_code=status.HTTP_204_NO_CONTENT)
def archive_org_user(
    organization_id: UUID,
    user_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """Archives a deactivated user, hiding them from user lists while
    preserving attribution of their past contributions (C-U-05).

    Scoped to members of `organization_id`, same as `deactivate_org_user`."""
    user = db.get(User, user_id)
    if user is None or not get_effective_org_roles(db, user_id, organization_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found in this organisation.")
    if user.is_active:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "User must be deactivated before archiving.")
    user.is_archived = True
    log_event(
        db, entity_type="user", entity_id=user_id, action="archived", actor_id=current_user.id,
        organization_id=organization_id,
    )
    db.commit()

