"""
Module: routers.system

System management endpoints that are not scoped to any single organisation
(I-M-06): granting or revoking the server admin role itself on another
user, the system-wide user access-review directory (C-A-13), platform-wide
UI branding defaults, and the server-wide public self-signup mode. Most of
this router is server-admin only; the branding GET is one exception
(readable by any authenticated user, since it drives shared app-shell
rendering for everyone), and `GET /signup-config` is a further exception —
entirely unauthenticated, since the signup form itself needs it before any
session exists.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import exists, func, select, true
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.deps import get_current_user
from app.models.enums import SignupMode
from app.models.organization import Organization, UserOrgRole
from app.models.user import User
from app.schemas.branding import ServerSettingsOut, ServerSettingsUpdate
from app.schemas.email import TestEmailRequest
from app.schemas.pat import BulkRevokeResult
from app.schemas.signup import SelfSignupOrgOut, SignupConfigOut, SignupConfigUpdate
from app.services.audit import log_event
from app.services.branding import get_server_settings
from app.services.email import send_email
from app.services.email_branding import resolve_email_branding
from app.services.email_templates import render_email
from app.services.files import upload_file
from app.services.pats import revoke_matching
from app.services.rbac import require_server_admin

router = APIRouter(prefix="/api/v1/system", tags=["system"])
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
    falls back to `organization_count`."""

    user_id: UUID
    email: str
    display_name: str
    is_active: bool
    is_banned: bool
    last_login_at: datetime | None = None
    is_2fa_enabled: bool
    created_at: datetime
    is_server_admin: bool
    has_org_membership: bool
    organization_count: int
    organization_names: list[str]


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


@router.get("/users", response_model=list[SystemUserOut])
def list_system_users(
    no_org_membership: bool | None = None,
    stale_since_days: int | None = Query(None, ge=0),
    is_active: bool | None = None,
    has_2fa: bool | None = None,
    is_server_admin: bool | None = None,
    current_user: User = Depends(require_server_admin),
    db: Session = Depends(get_db),
):
    """System-wide user directory for the server-admin access review (C-A-13).

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

    users = db.scalars(query).all()
    user_ids = [u.id for u in users]
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
    return [
        SystemUserOut(
            user_id=u.id, email=u.email, display_name=u.display_name, is_active=u.is_active,
            is_banned=u.is_banned,
            last_login_at=u.last_login_at, is_2fa_enabled=u.is_2fa_enabled, created_at=u.created_at,
            is_server_admin=u.is_server_admin, has_org_membership=u.id in org_ids_by_user,
            organization_count=len(org_ids_by_user.get(u.id, ())),
            organization_names=sorted(org_names_by_id[oid] for oid in org_ids_by_user.get(u.id, ()) if oid in org_names_by_id),
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


@router.post("/users/{user_id}/deactivate", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_orphaned_user(
    user_id: UUID,
    current_user: User = Depends(require_server_admin),
    db: Session = Depends(get_db),
):
    """Deactivates an orphaned account (C-U-04; C-A-13's "should be
    deactivated" clarification) — the one category of user no organisation
    admin can ever reach, since `deactivate_org_user` requires the target to
    already belong to that org. See `_require_orphaned_user` for the scoping
    rule this shares with `reactivate_orphaned_user`.
    """
    if user_id == current_user.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot deactivate your own account.")
    user = _require_orphaned_user(db, user_id)
    user.is_active = False
    user.deactivated_at = datetime.now(UTC)
    log_event(db, entity_type="user", entity_id=user_id, action="deactivated", actor_id=current_user.id)
    db.commit()


@router.post("/users/{user_id}/reactivate", status_code=status.HTTP_204_NO_CONTENT)
def reactivate_orphaned_user(
    user_id: UUID,
    current_user: User = Depends(require_server_admin),
    db: Session = Depends(get_db),
):
    """Reactivates a previously-deactivated orphaned account. No user-facing
    lifecycle action currently reverses a deactivation at all (org-scoped or
    otherwise) — added alongside `deactivate_orphaned_user` so a server admin
    who deactivates an orphaned account by mistake, or whose owner turns out
    to still need it, isn't left with no way back short of direct database
    access.

    Raises:
        HTTPException: 400 if the account is currently banned — `unban`
            must be called first (a separate, deliberate action, see its
            docstring); otherwise this endpoint would let a banned account
            back in without ever going through that step, contradicting
            `User.is_banned`'s own documented invariant that ban "survives
            even if something else were to flip `is_active` back on."
            Hardening-review finding: this was previously unchecked.
    """
    user = _require_orphaned_user(db, user_id)
    if user.is_banned:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This account is banned. Unban it before reactivating.")
    user.is_active = True
    user.deactivated_at = None
    log_event(db, entity_type="user", entity_id=user_id, action="reactivated", actor_id=current_user.id)
    db.commit()


@router.post("/users/{user_id}/ban", status_code=status.HTTP_204_NO_CONTENT)
def ban_orphaned_user(
    user_id: UUID,
    current_user: User = Depends(require_server_admin),
    db: Session = Depends(get_db),
):
    """Bans an orphaned account: deactivates it (same effect as
    `deactivate_orphaned_user`) and also flags it so `assign_org_role`
    refuses to let any org admin grant it a role again later — closing the
    gap a plain deactivation leaves open, where the same account could
    quietly be re-admitted through a different organisation without a
    server admin ever being asked again. Scoped to orphaned accounts only,
    same rationale as `deactivate_orphaned_user`: a user who already
    belongs to an organisation is that organisation's own admin's call.
    """
    if user_id == current_user.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot ban your own account.")
    user = _require_orphaned_user(db, user_id)
    user.is_active = False
    user.deactivated_at = datetime.now(UTC)
    user.is_banned = True
    user.banned_at = datetime.now(UTC)
    user.banned_by = current_user.id
    log_event(db, entity_type="user", entity_id=user_id, action="banned", actor_id=current_user.id)
    db.commit()


@router.post("/users/{user_id}/unban", status_code=status.HTTP_204_NO_CONTENT)
def unban_orphaned_user(
    user_id: UUID,
    current_user: User = Depends(require_server_admin),
    db: Session = Depends(get_db),
):
    """Reverses a ban. Deliberately does *not* also reactivate the account
    (`is_active` stays False) — unbanning just means "this account may be
    granted org roles again," a separate decision from "this account may
    log in again," which stays a distinct, explicit `reactivate` action.
    """
    user = _require_orphaned_user(db, user_id)
    user.is_banned = False
    user.banned_at = None
    user.banned_by = None
    log_event(db, entity_type="user", entity_id=user_id, action="unbanned", actor_id=current_user.id)
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


@router.post("/test-email", status_code=status.HTTP_204_NO_CONTENT)
def send_system_test_email(
    payload: TestEmailRequest,
    current_user: User = Depends(require_server_admin),
    db: Session = Depends(get_db),
):
    """Sends a test email through the deployment-wide SMTP configuration
    (`Settings.smtp_*`, `config.py`) — lets a server admin confirm outgoing
    mail (C-N-03) actually works without waiting for a real notification to
    trigger one. The organisation-scoped equivalent for an org with its own
    SMTP override is `routers/orgs.py::send_org_test_email`.

    Raises:
        HTTPException: 502 if the send itself fails (bad credentials,
            unreachable host, ...) — surfaced with the underlying error so
            the admin knows what to fix, since confirming deliverability is
            the entire point of this action.
    """
    to_email = payload.to_email or current_user.email
    branding = resolve_email_branding(db, organization_id=None)
    html_body, text_body = render_email(
        "test_email", branding=branding, source_description="ReqTrackManager's deployment-wide SMTP configuration",
        cta_url=settings.frontend_base_url,
    )
    inline_images = {"brand_logo": (branding.logo_bytes, branding.logo_content_type)} if branding.logo_bytes else None
    try:
        send_email(to_email, "ReqTrackManager test email", text_body, html_body=html_body, inline_images=inline_images)
    except Exception as err:  # noqa: BLE001 - surfacing the underlying SMTP failure is the entire point of a test-email action
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Failed to send test email: {err}") from err
    log_event(db, entity_type="system", entity_id="platform", action="test_email_sent",
              actor_id=current_user.id, detail={"to": to_email})
    db.commit()


# --- Platform-wide branding defaults ----------------------------------------


@router.get("/branding", response_model=ServerSettingsOut)
def get_branding(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Readable by any authenticated user (not server-admin-gated): the app
    shell needs these defaults to render its own chrome for every user, not
    just server admins — same reasoning as why org logos are readable by
    anyone regardless of org membership (see `routers/files.py`)."""
    return get_server_settings(db)


@router.put("/branding", response_model=ServerSettingsOut)
def update_branding(
    payload: ServerSettingsUpdate,
    current_user: User = Depends(require_server_admin),
    db: Session = Depends(get_db),
):
    """Sets the platform-wide default accent colour and header title, used
    on any page without a single resolvable organisation context, and as
    the fallback for any org that hasn't set its own override. Also sets the
    deployment-wide organisation label override (`org_label_singular`/
    `org_label_plural`) — unlike the rest of this endpoint's fields, that one
    has no per-org override to fall back from; it's platform-wide only."""
    settings = get_server_settings(db)
    settings.accent_color_hex = payload.accent_color_hex
    settings.default_header_title = payload.default_header_title
    settings.email_footer_company_name = payload.email_footer_company_name
    settings.email_footer_website = payload.email_footer_website
    settings.email_footer_address = payload.email_footer_address
    settings.org_label_singular = payload.org_label_singular
    settings.org_label_plural = payload.org_label_plural
    log_event(db, entity_type="system", entity_id="platform", action="branding_updated", actor_id=current_user.id)
    db.commit()
    db.refresh(settings)
    return settings


@router.post("/branding/logo", response_model=ServerSettingsOut)
async def upload_branding_logo(
    file: UploadFile = File(...),
    current_user: User = Depends(require_server_admin),
    db: Session = Depends(get_db),
):
    """Uploads the platform-wide default logo. `FileAsset.organization_id`
    is a required column (files are normally organisation-scoped for
    storage-key namespacing and access control), but a platform-wide asset
    has no owning organisation — it's stored against whichever organisation
    happens to exist first, purely for that namespacing, and served to any
    authenticated user via the same "avatar or logo" bypass already used for
    org logos and user avatars (`routers/files.py::download_file`), not by
    organisation membership.
    """
    any_org = db.scalar(select(Organization))
    if any_org is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No organisation exists yet to store this file against.")
    data = await file.read()
    asset = upload_file(
        db, organization_id=any_org.id, uploaded_by=current_user.id,
        filename=file.filename or "logo", content_type=file.content_type or "application/octet-stream", data=data,
    )
    db.flush()
    settings = get_server_settings(db)
    settings.default_logo_file_id = asset.id
    log_event(db, entity_type="system", entity_id="platform", action="branding_logo_updated",
              actor_id=current_user.id, detail={"file_id": str(asset.id)})
    db.commit()
    db.refresh(settings)
    return settings


@router.post("/branding/login-background", response_model=ServerSettingsOut)
async def upload_branding_login_background(
    file: UploadFile = File(...),
    current_user: User = Depends(require_server_admin),
    db: Session = Depends(get_db),
):
    """Uploads the platform-wide default login-page background image,
    shown on the plain `/login` page (no single org's branding applies).
    Same "stored against whichever org happens to exist" namespacing
    rationale as `upload_branding_logo` above.
    """
    any_org = db.scalar(select(Organization))
    if any_org is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No organisation exists yet to store this file against.")
    data = await file.read()
    asset = upload_file(
        db, organization_id=any_org.id, uploaded_by=current_user.id,
        filename=file.filename or "login-background",
        content_type=file.content_type or "application/octet-stream", data=data,
    )
    db.flush()
    settings = get_server_settings(db)
    settings.default_login_background_file_id = asset.id
    log_event(db, entity_type="system", entity_id="platform", action="branding_login_background_updated",
              actor_id=current_user.id, detail={"file_id": str(asset.id)})
    db.commit()
    db.refresh(settings)
    return settings


# --- Public self-signup mode -------------------------------------------------


@router.get("/signup-config", response_model=SignupConfigOut)
def get_signup_config(db: Session = Depends(get_db)):
    """Public, unauthenticated (no `current_user` dependency at all — the
    signup form's first call happens before any session exists, same as
    `orgs.py::get_org_login_info`). Only lists organisation *names* open to
    `ORG_SPECIFIED` self-signup, never their configured email domain — see
    `SelfSignupOrgOut`'s docstring."""
    server_settings = get_server_settings(db)
    orgs: list[SelfSignupOrgOut] = []
    if server_settings.signup_mode == SignupMode.ORG_SPECIFIED:
        orgs = [
            SelfSignupOrgOut(id=org.id, name=org.name)
            for org in db.scalars(
                select(Organization).where(
                    Organization.allow_self_signup.is_(True), Organization.is_active.is_(True)
                )
            ).all()
        ]
    return SignupConfigOut(signup_mode=server_settings.signup_mode, self_signup_organizations=orgs)


@router.put("/signup-config", response_model=SignupConfigOut)
def update_signup_config(
    payload: SignupConfigUpdate,
    current_user: User = Depends(require_server_admin),
    db: Session = Depends(get_db),
):
    """Sets the server-wide public self-signup mode (server-admin only)."""
    server_settings = get_server_settings(db)
    server_settings.signup_mode = payload.signup_mode
    log_event(db, entity_type="system", entity_id="platform", action="signup_mode_updated",
              actor_id=current_user.id, detail={"signup_mode": payload.signup_mode.value})
    db.commit()
    db.refresh(server_settings)
    return get_signup_config(db)
