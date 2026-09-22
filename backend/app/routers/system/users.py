"""
Module: routers.system.users

Server-tier user administration (I-M-06): granting or revoking the server
admin role itself, server-tier role grants/revokes (`UserServerRole`), the
system-wide user access-review directory (C-A-13), the merged
deactivate/reactivate/ban/unban action for orphaned (org-less) accounts,
and platform-wide PAT bulk revocation. Every endpoint here is
`require_server_admin` only.

Split out of the former flat `routers/system.py` as a pure code-organization
refactor — see `routers/system/__init__.py`'s module docstring for the
package layout.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel
from sqlalchemy import exists, func, select, true
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models.enums import ServerRole
from app.models.organization import Organization, OrgGroup, UserOrgRole
from app.models.server_role import UserServerRole
from app.models.user import User
from app.schemas.pat import BulkRevokeResult
from app.services.audit import log_event
from app.services.pats import revoke_matching
from app.services.rbac import get_user_org_group_ids, require_server_admin

router = APIRouter(tags=["system-users"])
settings = get_settings()


class ServerAdminUpdate(BaseModel):
    """Payload for granting/revoking the server admin role.

    Attributes:
        is_server_admin: The desired server-admin state for the target user.
    """

    is_server_admin: bool


class SystemUserOut(BaseModel):
    """Account-level fields, plus organisation-membership visibility for the
    access review (C-A-13). `organization_count` is always a plain number —
    no more revealing than `has_org_membership` already was — but
    `organization_names` is a deliberate, explicit exception to I-M-05's
    "server admin does not give access to data within organisations": naming
    actual orgs here does leak cross-tenant membership to a role that's
    otherwise kept content-blind by design. Gated by
    `settings.access_review_show_org_names` (default on — a server admin
    already has direct database access regardless) rather than silently
    always on; when off, `organization_names` is always `[]` and the UI
    falls back to `organization_count`. `group_names` (every org group the
    user effectively belongs to across every org, direct or inherited via
    nesting — see `services.rbac.get_user_org_group_ids`) is gated by the
    same setting, for the same reason: naming a specific team/group is at
    least as revealing of org-internal structure as an org name is."""

    user_id: UUID
    email: str
    display_name: str
    is_active: bool
    is_banned: bool
    last_login_at: datetime | None = None
    is_2fa_enabled: bool
    created_at: datetime
    is_server_admin: bool
    is_module_administrator: bool
    has_org_membership: bool
    organization_count: int
    organization_names: list[str]
    group_names: list[str]


class ServerRoleAssign(BaseModel):
    """Payload for granting/revoking a server-tier role (module system
    Phase 0) via `POST /users/{user_id}/server-roles`.

    Attributes:
        role: The server role to grant. `ServerRole.SERVER_ADMIN` is
            rejected here (400) — that tier is granted exclusively via
            `PUT /users/{user_id}/server-admin`'s `is_server_admin` boolean,
            never as a `UserServerRole` row (see `ServerRole`'s docstring).
    """

    role: ServerRole


class OrphanedUserStatusUpdate(BaseModel):
    """Payload for `POST /users/{user_id}/status` — merges the four
    formerly-separate `deactivate`/`reactivate`/`ban`/`unban` orphaned-user
    endpoints (2026-09-22, see docs/decisions.md) into one, following the
    same "action discriminates the transition" shape `ChangeRequestDecision`
    already uses for approve/reject. `deactivate_reactivate_ban_or_unban_
    orphaned_user` dispatches on `action`, applying the exact same per-branch
    guards and field writes the four original endpoints each had — see that
    function's own docstring for each branch's asymmetries (self-targeting,
    the banned/reactivate interaction, which fields `ban`/`unban` touch).

    Attributes:
        action: Which status transition to apply to the target orphaned
            account.
    """

    action: Literal["deactivate", "reactivate", "ban", "unban"]


@router.put("/users/{user_id}/server-admin", status_code=status.HTTP_204_NO_CONTENT)
def set_server_admin(
    user_id: UUID,
    payload: ServerAdminUpdate,
    current_user: User = Depends(require_server_admin),
    db: Session = Depends(get_db),
):
    """Grants or revokes the server admin role on another user (I-M-06).

    Only an existing server admin may call this endpoint, per the
    requirement's own wording: "This user can assign any user on the system,
    the server admin permission role."

    Args:
        user_id: The user whose server-admin flag is being changed.
        payload: The desired `is_server_admin` state.
        current_user: The calling server admin (enforced by the dependency).
        db: Active database session.

    Raises:
        HTTPException: 404 if `user_id` doesn't exist; 400 if this would
            revoke the deployment's last active server admin.
    """
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")
    if not payload.is_server_admin and target.is_server_admin:
        # Revoking, not granting or a no-op — check this wouldn't leave the
        # deployment with zero active server admins, which would be an
        # unrecoverable lockout: nobody left with the authority to grant the
        # role back to anyone, ever, short of direct database access. Only
        # *active* admins count — a deactivated one can't do anything
        # anyway, so doesn't cover for a revocation.
        active_admin_count = db.scalar(
            select(func.count()).select_from(User).where(User.is_server_admin.is_(True), User.is_active.is_(True))
        )
        if target.is_active and active_admin_count <= 1:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cannot revoke the deployment's last active server admin.")
    target.is_server_admin = payload.is_server_admin
    log_event(
        db,
        entity_type="user",
        entity_id=user_id,
        action="server_admin_granted" if payload.is_server_admin else "server_admin_revoked",
        actor_id=current_user.id,
    )
    db.commit()


@router.post("/users/{user_id}/server-roles", status_code=status.HTTP_204_NO_CONTENT)
def grant_server_role(
    user_id: UUID,
    payload: ServerRoleAssign,
    current_user: User = Depends(require_server_admin),
    db: Session = Depends(get_db),
):
    """Grants a server-tier role (module system Phase 0) to a user.

    Server-admin only (`require_server_admin`, no `MODULE_ADMINISTRATOR`
    fallback) — a narrower role can never grant itself or others a role,
    the same privilege-escalation-safe pattern `assign_org_role` follows
    for `ORG_ADMIN`.

    Raises:
        HTTPException: 404 if `user_id` doesn't exist; 400 if `payload.role`
            is `SERVER_ADMIN` (granted exclusively via the `is_server_admin`
            boolean and its own endpoint above, never as a row here).
    """
    if payload.role == ServerRole.SERVER_ADMIN:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Server admin is granted via PUT /users/{user_id}/server-admin, not this endpoint.",
        )
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")
    existing = db.scalar(
        select(UserServerRole).where(UserServerRole.user_id == user_id, UserServerRole.role == payload.role)
    )
    if existing is None:
        db.add(UserServerRole(user_id=user_id, role=payload.role, granted_by=current_user.id))
        log_event(
            db, entity_type="user_server_role", entity_id=user_id, action="granted",
            actor_id=current_user.id, detail={"role": payload.role.value},
        )
        db.commit()


@router.delete("/users/{user_id}/server-roles/{role}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_server_role(
    user_id: UUID,
    role: ServerRole,
    current_user: User = Depends(require_server_admin),
    db: Session = Depends(get_db),
):
    """Revokes a server-tier role (module system Phase 0) from a user.
    No-op if the user doesn't currently hold `role`. Server-admin only —
    see `grant_server_role`."""
    existing = db.scalar(
        select(UserServerRole).where(UserServerRole.user_id == user_id, UserServerRole.role == role)
    )
    if existing is not None:
        db.delete(existing)
        log_event(
            db, entity_type="user_server_role", entity_id=user_id, action="revoked",
            actor_id=current_user.id, detail={"role": role.value},
        )
        db.commit()


@router.get("/users", response_model=list[SystemUserOut])
def list_system_users(
    response: Response,
    no_org_membership: bool | None = None,
    stale_since_days: int | None = Query(None, ge=0),
    is_active: bool | None = None,
    has_2fa: bool | None = None,
    is_server_admin: bool | None = None,
    search: str | None = None,
    sort: str | None = Query(None, pattern="^(display_name|email|last_login_at|created_at)$"),
    order: str = Query("asc", pattern="^(asc|desc)$"),
    limit: int | None = Query(None, ge=1),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_server_admin),
    db: Session = Depends(get_db),
):
    """System-wide user directory for the server-admin access review (C-A-13).

    `limit`/`offset` (U-P-06) are optional, same contract as
    `list_requirements`: omitting both returns every matching user,
    unchanged from before pagination existed. When `limit` is given, the
    total match count (before slicing) is returned in the `X-Total-Count`
    response header. Slicing happens immediately after the filtered query,
    before the per-user organisation/group name lookups below, so a
    deployment with thousands of users doesn't pay for resolving names on
    rows outside the requested page.

    `no_org_membership` is the requirement's literal "orphaned account"
    clarification: an enabled user who belongs to no organisation and
    therefore has no project access either (C-U-02: all project users must
    be organisation users). A server admin is, *by design* (I-M-05), never a
    member of any organisation — that's the intended shape of the role, not
    an oversight — so `no_org_membership=true` always excludes server admins
    regardless of any other filter, closing a false-positive a hardening
    review found: every deployment's own server admin(s) were being flagged
    as "orphaned" alongside genuinely-forgotten accounts. Use the independent
    `is_server_admin` filter to review the server-admin roster itself (which
    intentionally is *not* restricted to org-less accounts — I-M-08 lets a
    bootstrap server admin also hold an organisation of their own).

    `search` (Phase E, follow-up UX batch, 2026-08-31) is name/email
    substring, case-insensitive — the exact same Python-side matching
    approach `list_org_users` (`routers/orgs.py`) already established,
    reused verbatim rather than reinvented as a SQL `ilike`.

    `sort`/`order` (same phase) mirror `list_org_users`'s own `sort`/`order`
    contract: `display_name` (default), `email`, `last_login_at`, or
    `created_at`, ascending unless `order=desc`. This is necessary plumbing
    for `DirectoryTable`'s sortable Email/Name/Last login/Created columns to
    re-sort the *full* filtered result correctly across pages, not just the
    already-loaded rows — the same reasoning that motivated `list_org_users`'
    own `sort`/`order` params originally. `last_login_at` is nullable (never
    logged in); those rows always sort last regardless of `order`, so "sort
    by last login, descending" surfaces the most recently active users first
    without "never logged in" accounts jumping to the top.

    Server-admin only (`require_server_admin`, no org-admin fallback) — this
    spans every organisation's users.
    """
    query = select(User).where(User.is_archived.is_(False))
    has_org_role = exists().where(UserOrgRole.user_id == User.id)
    if no_org_membership:
        query = query.where(~has_org_role, User.is_server_admin.is_(False))
    if is_active is not None:
        query = query.where(User.is_active == is_active)
    if has_2fa is not None:
        query = query.where(User.is_2fa_enabled == has_2fa)
    if is_server_admin is not None:
        query = query.where(User.is_server_admin == is_server_admin)
    if stale_since_days is not None:
        cutoff = datetime.now(UTC) - timedelta(days=stale_since_days)
        query = query.where((User.last_login_at.is_(None)) | (User.last_login_at < cutoff))

    users = list(db.scalars(query).all())
    if search:
        needle = search.lower()
        users = [u for u in users if needle in u.display_name.lower() or needle in u.email.lower()]

    if sort and sort != "display_name":
        def _sort_value(u: User):
            value = getattr(u, sort)
            if sort == "last_login_at":
                # Nulls (never logged in) always sort last, in either
                # direction — see docstring.
                return (value is None, value)
            if sort == "email":
                return value.lower()
            return value
        users.sort(key=_sort_value, reverse=(order == "desc"))
    else:
        users.sort(key=lambda u: u.display_name.lower(), reverse=(sort == "display_name" and order == "desc"))

    response.headers["X-Total-Count"] = str(len(users))
    if limit is not None:
        users = users[offset:offset + limit]
    user_ids = [u.id for u in users]
    module_admin_ids: set[UUID] = set()
    if user_ids:
        module_admin_ids = set(
            db.scalars(
                select(UserServerRole.user_id).where(
                    UserServerRole.user_id.in_(user_ids), UserServerRole.role == ServerRole.MODULE_ADMINISTRATOR
                )
            ).all()
        )
    org_ids_by_user: dict[UUID, set[UUID]] = {}
    if user_ids:
        for user_id, organization_id in db.execute(
            select(UserOrgRole.user_id, UserOrgRole.organization_id)
            .where(UserOrgRole.user_id.in_(user_ids))
            .distinct()
        ).all():
            org_ids_by_user.setdefault(user_id, set()).add(organization_id)
    all_org_ids = {oid for oids in org_ids_by_user.values() for oid in oids}
    org_names_by_id = (
        dict(db.execute(select(Organization.id, Organization.name).where(Organization.id.in_(all_org_ids))).all())
        if all_org_ids and settings.access_review_show_org_names
        else {}
    )
    # Group names are gated by the same setting as org names (see
    # SystemUserOut's docstring) — skip the per-user group lookups
    # entirely when the gate is off, same as the org-names branch above.
    group_names_by_user: dict[UUID, list[str]] = {}
    if settings.access_review_show_org_names:
        for user_id, org_ids in org_ids_by_user.items():
            group_ids: set[UUID] = set()
            for organization_id in org_ids:
                direct, inherited = get_user_org_group_ids(db, user_id, organization_id)
                group_ids |= direct | inherited
            if group_ids:
                group_names_by_user[user_id] = sorted(
                    db.scalars(select(OrgGroup.name).where(OrgGroup.id.in_(group_ids))).all()
                )
    return [
        SystemUserOut(
            user_id=u.id, email=u.email, display_name=u.display_name, is_active=u.is_active,
            is_banned=u.is_banned,
            last_login_at=u.last_login_at, is_2fa_enabled=u.is_2fa_enabled, created_at=u.created_at,
            is_server_admin=u.is_server_admin, is_module_administrator=u.id in module_admin_ids,
            has_org_membership=u.id in org_ids_by_user,
            organization_count=len(org_ids_by_user.get(u.id, ())),
            organization_names=sorted(org_names_by_id[oid] for oid in org_ids_by_user.get(u.id, ()) if oid in org_names_by_id),
            group_names=group_names_by_user.get(u.id, []),
        )
        for u in users
    ]


def _require_orphaned_user(db: Session, user_id: UUID) -> User:
    """Resolves `user_id` for the deactivate/reactivate endpoints below,
    which are deliberately scoped to accounts with no organisation
    membership at all (mirroring `no_org_membership`'s own definition).

    A server admin's authority is tenancy-wide but content-free (I-M-05):
    acting on an org member's account is the *organisation's own* admin's
    call (`deactivate_org_user`/`archive_org_user`), not the server admin's —
    so this deliberately refuses to touch any user who has an org role
    anywhere, directing the caller to the right place instead.

    Raises:
        HTTPException: 404 if `user_id` doesn't exist; 400 if they belong to
            any organisation.
    """
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")
    has_org_role = db.scalar(select(exists().where(UserOrgRole.user_id == user_id)))
    if has_org_role:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "This user belongs to an organisation — use that organisation's own admin console to manage them.",
        )
    return user


@router.post("/users/{user_id}/status", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_reactivate_ban_or_unban_orphaned_user(
    user_id: UUID,
    payload: OrphanedUserStatusUpdate,
    current_user: User = Depends(require_server_admin),
    db: Session = Depends(get_db),
):
    """Applies a status transition to an orphaned account — merges the
    formerly-separate `deactivate`/`reactivate`/`ban`/`unban` endpoints
    (2026-09-22, see docs/decisions.md) into one, dispatching on
    `payload.action`. Each branch below preserves its original endpoint's
    exact guards and field writes; none were weakened by the merge:

    - `deactivate` (C-U-04; C-A-13's "should be deactivated" clarification)
      — the one category of user no organisation admin can ever reach,
      since `deactivate_org_user` requires the target to already belong to
      that org. Refuses to deactivate the caller's own account (400).
    - `reactivate` — reverses a deactivation. No user-facing lifecycle
      action currently reverses a deactivation at all (org-scoped or
      otherwise) — added alongside `deactivate` so a server admin who
      deactivates an orphaned account by mistake, or whose owner turns out
      to still need it, isn't left with no way back short of direct
      database access. Refuses (400) if the account is currently banned —
      `unban` must be applied first; otherwise this would let a banned
      account back in without ever going through that step, contradicting
      `User.is_banned`'s own documented invariant that a ban "survives even
      if something else were to flip `is_active` back on." Hardening-review
      finding: this was previously unchecked. Does *not* forbid
      self-targeting (unlike `deactivate`/`ban`) — reactivating your own
      account is harmless.
    - `ban` — deactivates the account (same effect as `deactivate`) and
      also flags it so `assign_org_role` refuses to let any org admin grant
      it a role again later — closing the gap a plain deactivation leaves
      open, where the same account could quietly be re-admitted through a
      different organisation without a server admin ever being asked
      again. Refuses to ban the caller's own account (400).
    - `unban` — reverses a ban. Deliberately does *not* also reactivate the
      account (`is_active` stays False) — unbanning just means "this
      account may be granted org roles again," a separate decision from
      "this account may log in again," which stays a distinct, explicit
      `reactivate` action. Does *not* forbid self-targeting.

    All four actions are scoped to orphaned/system-level accounts (see
    `_require_orphaned_user`) and log the same audit `action` string
    (`"deactivated"`/`"reactivated"`/`"banned"`/`"unbanned"`) their original,
    separate endpoints did — mirroring how `change_requests.decide_change_
    request` already computes its own audit action string from a merged
    payload (`action="approved" if payload.approve else "rejected"`).

    Raises:
        HTTPException: 404 if `user_id` doesn't exist; 400 if they belong to
            any organisation (`_require_orphaned_user`); 400 for the
            self-targeting/still-banned guards above, per action.
    """
    if payload.action in ("deactivate", "ban") and user_id == current_user.id:
        verb = "deactivate" if payload.action == "deactivate" else "ban"
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"You cannot {verb} your own account.")
    user = _require_orphaned_user(db, user_id)

    if payload.action == "deactivate":
        user.is_active = False
        user.deactivated_at = datetime.now(UTC)
    elif payload.action == "reactivate":
        if user.is_banned:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "This account is banned. Unban it before reactivating.")
        user.is_active = True
        user.deactivated_at = None
    elif payload.action == "ban":
        user.is_active = False
        user.deactivated_at = datetime.now(UTC)
        user.is_banned = True
        user.banned_at = datetime.now(UTC)
        user.banned_by = current_user.id
    else:  # "unban"
        user.is_banned = False
        user.banned_at = None
        user.banned_by = None

    action_past_tense = {"deactivate": "deactivated", "reactivate": "reactivated", "ban": "banned", "unban": "unbanned"}
    log_event(db, entity_type="user", entity_id=user_id, action=action_past_tense[payload.action], actor_id=current_user.id)
    db.commit()


@router.post("/pats/revoke-all", response_model=BulkRevokeResult)
def revoke_all_pats_platform_wide(
    current_user: User = Depends(require_server_admin),
    db: Session = Depends(get_db),
):
    """Revokes every non-revoked Personal Access Token in the deployment,
    regardless of scope — an incident-response action, the PAT-level
    equivalent of the per-user `User.token_version` "kill all my sessions"
    mechanism, at platform scope. Never reads or exposes any organisation's
    content or any token secret (hashes aren't reversible), so this is pure
    security/tenancy administration and doesn't conflict with I-M-05."""
    count = revoke_matching(db, true())
    log_event(db, entity_type="system", entity_id="platform", action="system_pats_bulk_revoked",
              actor_id=current_user.id, detail={"count": count})
    db.commit()
    return BulkRevokeResult(revoked_count=count)
