"""
Module: routers.orgs.membership

Organisation membership: creating/listing organisation users (I-M-05; the server-admin carve-out covers only
the first user), org-only pending invites, per-user access summaries and directory search, org-role and
org-scoped module-role grant/revoke, self-service leave, admin-initiated removal, and deactivation/archival
(C-U-04, C-U-05).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, refuse_personal_access_token
from app.models.custom_role import CustomRoleDefinition, UserCustomRoleGrant
from app.models.enums import ExternalUserPolicy, OrgRole
from app.models.module_role import UserModuleRole
from app.models.notification import NotificationType
from app.models.organization import Organization, OrgGroup, OrgGroupMember, PendingInvite, UserOrgRole
from app.models.project import Project, ProjectGroup, ProjectGroupMember, UserProjectRole
from app.models.service_user import ServiceUserProfile
from app.models.user import User
from app.modules.registry import list_enabled_module_roles
from app.routers.orgs.core import _now
from app.schemas.org import (
    CustomRoleGrantOut,
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
from app.services import credential_reset, engagement, invites, service_users
from app.services.audit import log_event
from app.services.lookups import present
from app.services.notifications import notify
from app.services.org_membership import (
    assert_account_active,
    assert_may_add_account,
    belongs_elsewhere,
    remove_member_from_organization,
)
from app.services.rbac import (
    can_manage_project_settings,
    get_effective_org_roles,
    get_effective_project_managers,
    get_effective_project_roles,
    memoize_user_lookups,
    prefetch_project_roles,
    require_org_admin_or_grant_roles,
    require_org_admin_or_server_admin,
    require_org_role,
)
from app.services.user_provisioning import create_native_user, invite_user

router = APIRouter(tags=["organizations-membership"])


@router.post(
    "/{organization_id}/users", response_model=OrgUserOut, status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(refuse_personal_access_token)],
)
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
    user = create_native_user(
        db,
        email=payload.email,
        display_name=payload.display_name,
        password=payload.password,
        organization_id=organization_id,
        role=payload.role,
        actor_id=current_user.id,
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
    is_service_account: bool | None = None,
    include_archived: bool = False,
    search: str | None = None,
    sort: str | None = Query(None, pattern="^(display_name|email|last_login_at)$"),
    order: str = Query("asc", pattern="^(asc|desc)$"),
    limit: int | None = Query(None, ge=1),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN, OrgRole.PROJECT_CREATOR, OrgRole.MEMBER)),
    db: Session = Depends(get_db),
):
    """Lists users belonging to an organisation with their org roles.

    Archived users are excluded (C-U-05; their past contributions stay attributed via `creator_id`/`actor_id`)
    unless an org admin passes `include_archived` (an archived service user stays findable).

    The access-review filters (C-A-13: `stale_since_days`, `never_logged_in`, `has_2fa`, `org_role`,
    `has_project_access`, `is_active`, `is_service_account`, `include_archived`) are org-admin only, scoped to
    this organisation via `organization_id`; a plain member/project-creator can call the endpoint unfiltered
    for the general directory.

    `search` (case-insensitive name/email substring) and `limit`/`offset` narrow the directory a plain member
    can already browse, so they do not need org-admin. As `list_requirements`, omitting `limit` returns every
    match unpaginated; when given, the total before slicing is returned via `X-Total-Count`.

    `sort` overrides the default `display_name` sort with `email` or `last_login_at`; `order` is `asc`
    (default) or `desc`. `last_login_at` is nullable: never-logged-in rows sort last regardless of `order`, so
    descending surfaces the most recently active users first.
    """
    filters_requested = any(
        v is not None
        for v in (stale_since_days, never_logged_in, has_2fa, org_role, has_project_access, is_active, is_service_account)
    ) or include_archived
    is_admin = OrgRole.ORG_ADMIN in get_effective_org_roles(db, current_user.id, organization_id)
    if filters_requested and not is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only an organisation admin may use access-review filters.")

    listed = select(User, UserOrgRole.role).join(UserOrgRole, UserOrgRole.user_id == User.id).where(
        UserOrgRole.organization_id == organization_id
    )
    if not include_archived:
        listed = listed.where(User.is_archived.is_(False))
    rows = db.execute(listed).all()
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
                # C-A-13 access-review data: real values only for org admins (matching the filter gate
                # above); a plain member using the general directory must not see others' security posture.
                last_login_at=user.last_login_at if is_admin else None,
                is_2fa_enabled=user.is_2fa_enabled if is_admin else False,
                is_service_account=user.is_service_account,
                has_deliverable_email=service_users.can_receive_email(user),
            )
        by_user[user.id].roles.append(role)

    # The access review's flags on each service user, for administrators only (like the sign-in data above).
    service_ids = [uid for uid, out in by_user.items() if out.is_service_account]
    if is_admin and service_ids:
        for profile in db.scalars(select(ServiceUserProfile).where(ServiceUserProfile.user_id.in_(service_ids))):
            out = by_user[profile.user_id]
            out.service_flags = service_users.access_flags(profile, set(out.roles))

    # Attach each returned user's org-scoped module-contributed role grants, filtered to currently-enabled
    # modules (`list_enabled_module_roles`): a grant for a disabled module is omitted, never deleted from
    # `user_module_roles` (see `ModuleRoleGrantOut`). Computed once per request since it depends only on
    # `organization_id`.
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

    # For the Role Management UI: attach each user's org-scoped (`project_id IS NULL`) `CustomRoleDefinition`
    # grants (see `CustomRoleGrantOut` for why project-scoped grants are excluded). `scope_entity_id.is_(None)`
    # excludes entity-scoped grants, which also have `project_id IS NULL`.
    if by_user:
        custom_role_rows = db.execute(
            select(UserCustomRoleGrant.user_id, CustomRoleDefinition.id, CustomRoleDefinition.name)
            .join(CustomRoleDefinition, CustomRoleDefinition.id == UserCustomRoleGrant.custom_role_id)
            .where(
                UserCustomRoleGrant.organization_id == organization_id,
                UserCustomRoleGrant.project_id.is_(None),
                UserCustomRoleGrant.scope_entity_id.is_(None),
                UserCustomRoleGrant.user_id.in_(by_user.keys()),
            )
        ).all()
        for user_id, custom_role_id, name in custom_role_rows:
            by_user[user_id].custom_roles.append(CustomRoleGrantOut(custom_role_id=custom_role_id, name=name))

    results = list(by_user.values())
    if is_active is not None:
        results = [r for r in results if r.is_active == is_active]
    if is_service_account is not None:
        results = [r for r in results if r.is_service_account == is_service_account]
    if has_2fa is not None:
        # A service user has no sign-in to hold a second factor on, so it is never in a "without 2FA" review.
        results = [r for r in results if r.is_2fa_enabled == has_2fa and not (has_2fa is False and r.is_service_account)]
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
    """Lists this organisation's outstanding (unaccepted) org-only `PendingInvite`s, most recent first
    (`project_id IS NULL` only). Project-scoped invites stay owned by
    `routers/projects.py::list_pending_project_invites` and are never double-listed here.

    `require_org_role(ORG_ADMIN)` with no server-admin bypass. `require_org_admin_or_server_admin` is a narrow
    carve-out for bootstrapping the first user of a new org (I-M-05, docs/decisions.md); invite
    listing/creating/resending has no bootstrap need, and an org-uninvolved server admin must not read
    invitee PII or seed members into an arbitrary organisation ("does not give access to data within
    organisations").
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
    """Invites a new user into the organisation by email: the org-level "Invite user" action, distinct from
    `create_org_user`'s "New user" (an immediate password-based account). The invitee sets their own display
    name and password at signup via the emailed link and is granted `OrgRole.MEMBER` on redemption
    (`services.invites.consume_pending_invites`); an admin can promote them afterwards.

    Thin wrapper over `services.invites.create_pending_invite` with `project=None`/`project_role=None`.

    `org.sso_only` is rejected with 400, as `create_org_user` does: no native-signup path exists to redeem a
    token for an `sso_only` org. `assign_project_role_by_email` can provision immediately
    (`provision_sso_invite`) because it knows the project and role; a bare org-only invite has no such target,
    so it is rejected. An admin who needs to pre-add someone can configure the IdP group/role claim to match
    on first SSO login.
    """
    invite = invite_user(db, email=payload.email, organization_id=organization_id, actor_id=current_user.id)
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
    """One user's access within this organisation: every project in the org where the user holds an
    effective role, that role set, which of the project's own groups they directly belong to, and which org
    groups they directly belong to.

    Computed server-side via `get_effective_project_roles` (direct assignment, direct/nested project-group
    membership or org-wide project visibility, the resolution every permission check uses) so there is one
    algorithm and no per-project fan-out of client requests.
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

    org_projects = db.scalars(
        select(Project).where(Project.organization_id == organization_id).order_by(Project.name)
    ).all()
    project_ids = [p.id for p in org_projects]
    # Batched: resolving roles and group memberships per project costs ~10 queries per project and outlasted
    # the UI's wait for an org with ~70 projects. Same resolution, inputs preloaded.
    groups_by_project: dict[UUID, list[UserAccessGroupRef]] = {}
    for project_id, group_id, group_name in db.execute(
        select(ProjectGroup.project_id, ProjectGroup.id, ProjectGroup.name)
        .join(ProjectGroupMember, ProjectGroupMember.project_group_id == ProjectGroup.id)
        .where(ProjectGroup.project_id.in_(project_ids), ProjectGroupMember.user_id == user_id)
        .order_by(ProjectGroup.name)
    ).all():
        groups_by_project.setdefault(project_id, []).append(UserAccessGroupRef(id=group_id, name=group_name))

    projects: list[UserAccessProject] = []
    with memoize_user_lookups():
        prefetch_project_roles(db, user_id, project_ids)
        for project in org_projects:
            roles = get_effective_project_roles(db, user_id, project.id)
            if not roles:
                continue
            projects.append(UserAccessProject(
                project_id=project.id, project_name=project.name,
                roles=sorted(roles, key=lambda r: r.value),
                project_groups=groups_by_project.get(project.id, []),
            ))

    return UserAccessOut(org_groups=org_groups, projects=projects)


def _looks_like_email(value: str) -> bool:
    """Cheap "looks like an email" heuristic for the external-user-match check below; not full RFC 5322
    validation (`email-validator` does that for signup/invite).

    Plain string operations, not a single `^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$`-style regex: that shape is
    polynomial-time on crafted input (many `.`s after the `@`) and `value` is the attacker-controlled search
    query `q` (CodeQL py/polynomial-redos). Same match semantics (nonempty local part, exactly one `@`, no
    whitespace, a domain `.` with a character on each side) in linear time.
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
    """Server-backed search for the project user picker: org members matching `q` by name/email, plus, only
    when `q` is a full email address not already among the org's members and
    `Organization.external_user_policy` allows it, a synthetic "external" result the caller can add via
    `routers/projects.py::assign_project_role_by_email`.

    Whether `q` matches an existing account elsewhere is itself a cross-tenant fact (a one-bit "this exact
    email has an account somewhere" signal), unlike "no account, would need an invite", which reveals nothing.
    The endpoint is open to any org member (as `list_org_users`), a lower bar than
    `assign_project_role_by_email`'s `require_project_manage`, so the `exists=True` case is withheld from a
    caller who could not act on it: only an org admin, or a member passing a `project_id` in this org they
    manage, receives it. Below that bar a match resolving to `exists=True` is omitted rather than downgraded
    to a misleading `exists=False`.
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
                display_name_locked=user.display_name_locked, is_service_account=user.is_service_account,
            )
        by_user[user.id].roles.append(role)
    members = list(by_user.values())[:8]

    external: ExternalUserMatch | None = None
    if _looks_like_email(needle) and not any(m.email.lower() == needle for m in members):
        org = db.get(Organization, organization_id)
        policy = org.external_user_policy if org else ExternalUserPolicy.DISABLED
        if policy != ExternalUserPolicy.DISABLED:
            existing = db.scalar(select(User).where(User.email == needle))
            if existing is not None and existing.is_service_account:
                # An address that belongs to a service user is never offered: it cannot join another organisation.
                pass
            elif existing is not None:
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
    candidates = db.scalars(select(User).where(User.is_archived.is_(False), User.is_service_account.is_(False))).all()
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
        present(
            db.scalars(
                select(ProjectGroupMember.user_id)
                .join(ProjectGroup, ProjectGroup.id == ProjectGroupMember.project_group_id)
                .join(Project, Project.id == ProjectGroup.project_id)
                .where(Project.organization_id == organization_id, ProjectGroupMember.user_id.is_not(None))
            ).all()
        )
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


@router.post("/{organization_id}/users/{user_id}/roles", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(refuse_personal_access_token)])
def assign_org_role(
    organization_id: UUID,
    user_id: UUID,
    payload: OrgRoleAssign,
    current_user: User = Depends(require_org_admin_or_grant_roles),
    db: Session = Depends(get_db),
):
    """Grants an organisation role to a user (C-U-01).

    The affected user is always the `{user_id}` path parameter; only `payload.role` is used and a mismatched
    body `user_id` is ignored, so the URL a caller is authorised against (and the audit trail) cannot diverge
    from who is affected.

    Gated by `require_org_admin_or_grant_roles`: an `ORG_ADMIN`, server admin or `grant_roles` holder may
    reach it, but granting `OrgRole.ORG_ADMIN` itself is carved out: a `grant_roles`-only holder gets 403 when
    `payload.role == OrgRole.ORG_ADMIN`, checked here because it depends on the role value.
    """
    if payload.role == OrgRole.ORG_ADMIN and not (
        current_user.is_server_admin
        or OrgRole.ORG_ADMIN in get_effective_org_roles(db, current_user.id, organization_id)
    ):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only an existing organisation admin (or server admin) may grant the org_admin role.",
        )
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")
    org = db.get(Organization, organization_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    # A user id is not consent: an account another organisation holds joins this one only when this
    # organisation allows external users (`services.org_membership`), and a banned one never does.
    assert_may_add_account(db, org, target)
    assert_account_active(db, user_id)
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
                entity_type="organization", entity_id=str(organization_id), actor_id=current_user.id,
            )
        db.commit()


@router.delete(
    "/{organization_id}/users/{user_id}/roles/{role}", status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(refuse_personal_access_token)],
)
def revoke_org_role(
    organization_id: UUID,
    user_id: UUID,
    role: OrgRole,
    current_user: User = Depends(require_org_admin_or_grant_roles),
    db: Session = Depends(get_db),
):
    """Revokes an organisation role from a user (`assign_org_role`'s counterpart). No-op if the user does not
    hold `role`.

    The caller may not target their own account (as `deactivate_org_user`). The caller must hold `ORG_ADMIN`
    (never derived indirectly, unlike project roles) and self-targeting is blocked, so the acting admin's role
    survives any revoke of someone else and an organisation cannot reach zero admins through this endpoint,
    with no "last admin" count check.

    Gated by `require_org_admin_or_grant_roles` with the `OrgRole.ORG_ADMIN` carve-out of `assign_org_role`: a
    `grant_roles`-only holder gets 403 when `role == OrgRole.ORG_ADMIN`, because the self-targeting argument
    holds only for a genuine `ORG_ADMIN`; otherwise such a holder could leave the organisation with no admins.
    """
    if user_id == current_user.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot revoke your own organisation role.")
    if role == OrgRole.ORG_ADMIN and not (
        current_user.is_server_admin
        or OrgRole.ORG_ADMIN in get_effective_org_roles(db, current_user.id, organization_id)
    ):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only an existing organisation admin (or server admin) may revoke the org_admin role.",
        )
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
    currently effectively enabled here. Same
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


@router.post(
    "/{organization_id}/users/{user_id}/module-roles", status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(refuse_personal_access_token)],
)
def assign_org_module_role(
    organization_id: UUID,
    user_id: UUID,
    payload: ModuleRoleAssign,
    current_user: User = Depends(require_org_admin_or_grant_roles),
    db: Session = Depends(get_db),
):
    """Grants an org-scoped module-contributed role to a user: the module-role counterpart to
    `assign_org_role`, same gate plus a `grant_roles` holder (an org admin already implicitly holds every
    org-scoped module role via `require_module_role`). No `OrgRole.ORG_ADMIN`-style carve-out is needed: a
    module role carries no admin-tier significance.

    400 if `(payload.module_key, payload.role_key)` is not a `scope="org"` role of a currently-enabled module
    for this organisation, which makes a disabled module's roles ungrantable and catches a mistyped key; it
    uses the `list_enabled_module_roles` lookup behind the frontend's option list.
    """
    target = db.get(User, user_id)
    if target is not None and target.is_banned:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "This user has been banned by a server admin and cannot be granted a role."
        )
    assert_account_active(db, user_id)
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
                entity_type="organization", entity_id=str(organization_id), actor_id=current_user.id,
            )
        db.commit()


@router.delete(
    "/{organization_id}/users/{user_id}/module-roles/{module_key}/{role_key}", status_code=status.HTTP_204_NO_CONTENT
, dependencies=[Depends(refuse_personal_access_token)])
def revoke_org_module_role(
    organization_id: UUID,
    user_id: UUID,
    module_key: str,
    role_key: str,
    current_user: User = Depends(require_org_admin_or_grant_roles),
    db: Session = Depends(get_db),
):
    """Revokes an org-scoped module-contributed role grant — `assign_org_
    module_role`'s counterpart, same gate and no-op-if-absent shape as
    `revoke_org_role`. Unlike `revoke_org_role`, no self-targeting guard is needed: an
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


@router.delete("/{organization_id}/membership", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(refuse_personal_access_token)])
def leave_organization(
    organization_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Self-service: the caller removes their own membership in an organisation.

    Refuses (409) rather than reassigning anyone else's roles if leaving would strip the organisation of its
    last org_admin or leave a project with zero managers. `deactivate_org_user`'s C-U-09 fallback reassigns the
    acting admin as manager, but here the caller is the one leaving, so there is no natural recipient and the
    caller must reassign those roles first.

    Also removes the caller's `OrgGroupMember` rows for this organisation's groups, not just direct project
    roles/memberships: project access can come from an org group nested into a project group (C-U-12), and
    `get_effective_project_managers` (used for the sole-manager guard) resolves only direct managers. Both
    direct and nested-group-derived manager status are checked, so a user cannot leave while retaining project
    access through a still-active session.

    Locks the organisation row (`lock_organization_for_update`) first and each project row
    (`lock_project_for_update`) before checking its manager count: otherwise two concurrent leavers (an org's
    last two admins, or a project's last two managers) could each see the other as remaining backup and both
    proceed.
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
        # Include nested-org-group-derived manager status: `get_effective_project_managers` resolves only direct
        # assignments and direct group membership, so a role held solely via a nested org group would be
        # invisible, and removing this user's nested-group access below would leave the project with nobody.
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
            delete(UserProjectRole).where(
                UserProjectRole.user_id == current_user.id, UserProjectRole.project_id.in_(project_ids)
            )
        )
        db.execute(
            delete(ProjectGroupMember).where(
                ProjectGroupMember.user_id == current_user.id,
                ProjectGroupMember.project_group_id.in_(
                    select(ProjectGroup.id).where(ProjectGroup.project_id.in_(project_ids))
                ),
            )
        )
    db.execute(
        delete(OrgGroupMember).where(
            OrgGroupMember.user_id == current_user.id,
            OrgGroupMember.org_group_id.in_(
                select(OrgGroup.id).where(OrgGroup.organization_id == organization_id)
            ),
        )
    )
    engagement.remove_subscriptions_and_favorites_for_projects(db, current_user.id, project_ids)

    db.execute(
        delete(UserOrgRole).where(
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
    """Admin-initiated counterpart to `leave_organization`: an org admin removes another user's membership in
    `organization_id`. `deactivate_org_user` sets `is_active=False` on the whole account (a cross-org lockout)
    and `archive_org_user` only hides a deactivated user, so neither removes one organisation's `UserOrgRole`
    rows without touching the account's standing elsewhere.

    Access-mutating (identify -> verify -> remediate review, docs/decisions.md), so it mirrors
    `leave_organization`'s cleanup and guards rather than being a bare `UserOrgRole` delete:

    - Self-targeting is blocked (400), as `deactivate_org_user`/`revoke_org_role`; an admin removing their own
      membership uses `leave_organization`, which lets a departing admin reassign responsibilities first.
    - No last-admin count check, by construction as `revoke_org_role`: the caller must hold `ORG_ADMIN` on
      `organization_id` (`require_org_role`) and self-targeting is blocked, so a second, distinct `ORG_ADMIN`
      always remains.
    - Sole-project-manager guard: refuses (409) if `user_id` is the sole real manager of any project in this
      org, as `leave_organization` does for the leaving user.
    - Cleanup: every direct `UserProjectRole` and `ProjectGroupMember` row for `user_id` across this org's
      projects, every `OrgGroupMember` row for this org's groups, and subscriptions/favorites for this org's
      projects; this org's `UserOrgRole` rows are deleted last, after every dependent cleanup succeeds.
    - Row-locks the organisation before the last-admin guard and each project before its sole-manager check
      (`lock_organization_for_update`/`lock_project_for_update`), as `leave_organization` documents.

    A user who is not a member of `organization_id` is a 404 (as `leave_organization`).
    """
    if user_id == current_user.id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Use the leave-organisation action to remove your own membership."
        )
    remove_member_from_organization(db, organization_id, user_id, actor_id=current_user.id)


@router.post("/{organization_id}/users/{user_id}/password-reset", status_code=status.HTTP_204_NO_CONTENT)
def send_org_user_password_reset(
    organization_id: UUID,
    user_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """Emails a member a password-reset link, for an organisation admin helping someone who is locked out.

    The link goes to the member's own address; the admin never sees it, so this cannot be used to take over
    the account. Nothing changes until the member uses the link. Scoped like every org-admin account action:
    the target must hold a role in this organisation.

    Raises:
        HTTPException: 404 if the user is not a member of this organisation; 400/409/429/502 as
            `credential_reset.send_link_for_administrator`.
    """
    user = db.get(User, user_id)
    if user is None or not get_effective_org_roles(db, user_id, organization_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found in this organisation.")
    credential_reset.send_link_for_administrator(db, user, admin=current_user, organization_id=organization_id)


@router.post("/{organization_id}/users/{user_id}/deactivate", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_org_user(
    organization_id: UUID,
    user_id: UUID,
    current_user: User = Depends(require_org_role(OrgRole.ORG_ADMIN)),
    db: Session = Depends(get_db),
):
    """Deactivates a user (C-U-04). For an account that belongs to this organisation alone this ends the
    account; for a server administrator or someone another organisation also holds it is scoped to this
    organisation: their roles, project access and group membership here are removed and the account stays
    active elsewhere (see `services.org_membership.remove_member_from_organization`, which can refuse with 409
    while the person is the sole manager of a project).

    Applies the C-U-09 fallback: for any project left with no manager by this removal, the acting admin is
    assigned as manager so it is never left without one (C-U-08). Each project is row-locked
    (`lock_project_for_update`) before its manager count is checked, so this cannot race a concurrent removal
    on the same project.

    The target must be a member of `organization_id`: an org admin's authority is scoped to their own
    organisation's members, not every account in the deployment.

    A caller may not target their own account. The caller must hold `org_admin` on this organisation
    (`require_org_role`), and org_admin is never derived indirectly, so once self-targeting is blocked an
    organisation cannot reach zero active admins through this endpoint, with nothing further to check.
    Deactivation sets `is_active=False` on the whole account, locking the caller out of every organisation;
    an org-scoped admin action must not do that to oneself without a confirmation step.
    """
    from app.services.rbac import lock_project_for_update

    if user_id == current_user.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Use the leave-organisation action to remove your own membership.")

    user = db.get(User, user_id)
    if user is None or not get_effective_org_roles(db, user_id, organization_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found in this organisation.")
    # Deactivation ends the whole account in every organisation, and an organisation administrator's authority
    # stops at their own organisation. For a platform administrator or someone another organisation also
    # holds, "deactivate" means deactivate here: the membership is removed and the account stays active elsewhere.
    if user.is_server_admin or belongs_elsewhere(db, user_id, organization_id):
        remove_member_from_organization(db, organization_id, user_id, actor_id=current_user.id, action="deactivated_in_organization")
        return
    user.is_active = False
    user.deactivated_at = _now()

    from app.models.project import Project  # local import to avoid cycle at module load

    projects = db.scalars(select(Project).where(Project.organization_id == organization_id)).all()
    for project in projects:
        lock_project_for_update(db, project.id)

    # A project's effective manager set can be inherited from a different project in this org (hierarchical
    # projects, docs/decisions.md), so per-project deletes cannot be interleaved with this loop's C-U-08
    # checks: a project whose only manager was inherited from a not-yet-processed sibling would pass its check
    # and lose its manager later without the fallback triggering. All of this user's direct and group roles
    # across the org's projects are therefore deleted first, in one pass, so every fallback check sees final state.
    managers_before_by_project = {
        project.id: user_id in get_effective_project_managers(db, project.id) for project in projects
    }
    for project in projects:
        db.execute(
            delete(UserProjectRole).where(
                UserProjectRole.user_id == user_id, UserProjectRole.project_id == project.id
            )
        )
    db.execute(delete(ProjectGroupMember).where(ProjectGroupMember.user_id == user_id))

    for project in projects:
        if not managers_before_by_project[project.id]:
            continue
        if project.is_archived:
            # An archived project is dormant: making the acting admin its manager would hand them a role
            # on something they never asked for. It is left without a manager (an org admin can still
            # unarchive it and assign one) and the gap is recorded.
            log_event(
                db, entity_type="project", entity_id=project.id, action="manager_fallback_skipped_archived",
                actor_id=current_user.id, project_id=project.id,
                detail={"reason": "last_manager_deactivated", "deactivated_user_id": str(user_id)},
            )
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

