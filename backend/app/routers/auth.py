"""
Module: routers.auth

Login (including the optional two-factor second step, C-U-14), public
self-signup (gated by `ServerSettings.signup_mode`, see `signup` below),
current-user profile/preferences (C-U-16, C-U-18, C-N-05), password change,
and TOTP enrollment/disable endpoints. Login attempts (including a
successful signup, which logs the new user in immediately) are always
logged (C-A-07) and counted (metrics) regardless of outcome.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth_backends.native import NativeAuthBackend
from app.config import get_settings
from app.database import get_db
from app.deps import get_client_ip, get_current_user
from app.metrics import login_attempts_total
from app.models.enums import OrgRole, SignupMode
from app.models.notification import NotificationType
from app.models.organization import Organization, PendingInvite, UserOrgRole
from app.models.user import User
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    SignupRequest,
    TokenResponse,
    TwoFactorChallengeResponse,
    TwoFactorConfirmRequest,
    TwoFactorDisableRequest,
    TwoFactorEnrollResponse,
    TwoFactorVerifyRequest,
    UserOut,
    UserPreferencesUpdate,
)
from app.security import create_2fa_challenge_token, create_access_token, decode_access_token, hash_password, verify_password
from app.services import notifications, totp
from app.services.audit import log_event, log_login
from app.services.branding import get_server_settings
from app.services.files import upload_file
from app.services.geoip import resolve_and_store_login_location
from app.services.invites import consume_pending_invites

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
_native_backend = NativeAuthBackend()
_settings = get_settings()


@router.post("/login", response_model=TokenResponse | TwoFactorChallengeResponse)
def login(
    payload: LoginRequest,
    background_tasks: BackgroundTasks,
    request_ip: str = Depends(get_client_ip),
    db: Session = Depends(get_db),
):
    """Authenticates with native email/password credentials.

    If the account has 2FA enabled (C-U-14), returns a `TwoFactorChallengeResponse`
    instead of a token; the client must then call `/auth/2fa/verify` with the
    challenge token and a current TOTP code to receive the real access token.

    IP geolocation (C-A-07), if enabled, is resolved in a background task
    scheduled *after* this function returns — it never adds latency to the
    login response itself.

    Raises:
        HTTPException: 401 if credentials are invalid or the account is
            deactivated.
    """
    result = _native_backend.authenticate(db, payload.email, payload.password)
    login_event = log_login(
        db,
        user_id=result.user.id if result.user else None,
        email_attempted=payload.email,
        ip_address=request_ip,
        success=result.success,
    )
    login_attempts_total.labels(result="success" if result.success else "failure").inc()
    db.commit()
    background_tasks.add_task(resolve_and_store_login_location, login_event.id, request_ip)
    if not result.success or result.user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, result.error or "Invalid credentials.")

    if result.user.is_2fa_enabled:
        return TwoFactorChallengeResponse(challenge_token=create_2fa_challenge_token(str(result.user.id)))

    # Stamped here, not on the 2FA-challenge branch above (C-A-13): a
    # challenge only proves the password was correct, not a completed login.
    result.user.last_login_at = datetime.now(UTC)
    db.commit()
    token = create_access_token(str(result.user.id), token_version=result.user.token_version)
    return TokenResponse(access_token=token, user=UserOut.model_validate(result.user))


@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def signup(
    payload: SignupRequest,
    background_tasks: BackgroundTasks,
    request_ip: str = Depends(get_client_ip),
    db: Session = Depends(get_db),
):
    """Public self-registration, gated by `ServerSettings.signup_mode`
    unless `invite_token` proves an explicit admin invite (which overrides
    the mode entirely — see `SignupRequest`'s docstring).

    Without a valid invite:
      - `DISABLED`: rejected (403).
      - `ALWAYS_ON`: account created with no organisation membership; an
        admin assigns one afterward, same as any `create_org_user`-style
        provisioning.
      - `ORG_SPECIFIED`: the email's domain must match exactly one
        organisation with `allow_self_signup=True` (which — enforced at
        write time in `update_advanced_settings` — can never also be
        `sso_only`, so this can't hand out a native credential an
        `sso_only` org's login page would reject); that organisation grants
        `member` immediately. No domain match is a 400, not a silent no-op.

    Logs in immediately on success, same response shape as `/login`.

    Raises:
        HTTPException: 409 if the email is already registered; 400 if an
            `invite_token` is supplied but invalid/expired, or (in
            `ORG_SPECIFIED` mode with no invite) the email's domain doesn't
            match exactly one self-signup-enabled organisation; 403 if
            public signup is disabled and no invite was supplied.
    """
    email = payload.email.lower()
    if db.scalar(select(User).where(User.email == email)) is not None:
        # Same "already exists" 409 shape as create_org_user — not a new
        # email-enumeration exposure introduced by adding self-signup.
        raise HTTPException(status.HTTP_409_CONFLICT, "A user with this email already exists.")

    invite: PendingInvite | None = None
    if payload.invite_token:
        invite = db.scalar(
            select(PendingInvite).where(
                PendingInvite.token == payload.invite_token,
                PendingInvite.email == email,
                PendingInvite.accepted_at.is_(None),
                PendingInvite.expires_at > datetime.now(UTC),
            )
        )
        if invite is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired invite.")

    org_to_join: Organization | None = None
    if invite is None:
        server_settings = get_server_settings(db)
        if server_settings.signup_mode == SignupMode.DISABLED:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Public signup is not available.")
        if server_settings.signup_mode == SignupMode.ORG_SPECIFIED:
            domain = email.rsplit("@", 1)[-1]
            candidates = db.scalars(
                select(Organization).where(
                    Organization.allow_self_signup.is_(True),
                    Organization.is_active.is_(True),
                    Organization.auto_accept_email_domain.isnot(None),
                )
            ).all()
            matches = [o for o in candidates if o.auto_accept_email_domain.lower() == domain]
            if len(matches) != 1:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST, "Self-signup is not available for this email address."
                )
            org_to_join = matches[0]
        # ALWAYS_ON: org_to_join stays None — assigned by an admin afterward.

    user = User(
        email=email, display_name=payload.display_name,
        password_hash=hash_password(payload.password), auth_backend="native",
    )
    db.add(user)
    db.flush()
    log_event(db, entity_type="user", entity_id=user.id, action="signed_up", actor_id=user.id)
    if org_to_join is not None:
        db.add(UserOrgRole(user_id=user.id, organization_id=org_to_join.id, role=OrgRole.MEMBER))
        log_event(
            db, entity_type="user", entity_id=user.id, action="self_signup_joined_org",
            actor_id=user.id, organization_id=org_to_join.id,
        )
    if invite is not None:
        consume_pending_invites(db, user)
    login_event = log_login(db, user_id=user.id, email_attempted=email, ip_address=request_ip, success=True)
    user.last_login_at = datetime.now(UTC)
    db.commit()
    background_tasks.add_task(resolve_and_store_login_location, login_event.id, request_ip)
    token = create_access_token(str(user.id), token_version=user.token_version)
    return TokenResponse(access_token=token, user=UserOut.model_validate(user))


@router.post("/2fa/verify", response_model=TokenResponse)
def verify_2fa(
    payload: TwoFactorVerifyRequest,
    background_tasks: BackgroundTasks,
    request_ip: str = Depends(get_client_ip),
    db: Session = Depends(get_db),
):
    """Completes a two-factor login: exchanges a challenge token + TOTP code for an access token.

    Every attempt is recorded via `log_login` (success and failure alike),
    same as `/login` — this is the step an attacker who has already stolen a
    password would be brute-forcing, so it must not be a blind spot in the
    login audit trail (SOC 2 monitoring/logging hardening pass).
    """
    claims = decode_access_token(payload.challenge_token)
    if not claims or claims.get("purpose") != "2fa_challenge" or "sub" not in claims:
        log_login(db, user_id=None, email_attempted="(invalid 2fa challenge)", ip_address=request_ip, success=False)
        login_attempts_total.labels(result="failure").inc()
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired challenge.")
    user = db.get(User, UUID(claims["sub"]))
    if user is None or not user.is_active or user.is_archived or not user.is_2fa_enabled or not user.totp_secret:
        log_login(
            db, user_id=user.id if user else None,
            email_attempted=user.email if user else "(invalid 2fa challenge)",
            ip_address=request_ip, success=False,
        )
        login_attempts_total.labels(result="failure").inc()
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired challenge.")
    # Hardening-review finding: a stolen password plus an unthrottled,
    # reusable 2FA challenge against a bounded 6-digit TOTP keyspace lets an
    # attacker converge toward a near-certain bypass given enough repeated
    # 5-minute windows (freely re-mintable via `/login`). This lockout is
    # keyed to the *account*, not the challenge token, so starting a fresh
    # login doesn't reset it.
    if user.failed_2fa_locked_until is not None and user.failed_2fa_locked_until > datetime.now(UTC):
        log_login(db, user_id=user.id, email_attempted=user.email, ip_address=request_ip, success=False)
        login_attempts_total.labels(result="failure").inc()
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Too many failed attempts. Try again later.")
    if not totp.verify_code(user.totp_secret, payload.code):
        user.failed_2fa_attempts += 1
        if user.failed_2fa_attempts >= _settings.two_factor_max_failed_attempts:
            user.failed_2fa_locked_until = datetime.now(UTC) + timedelta(minutes=_settings.two_factor_lockout_minutes)
            user.failed_2fa_attempts = 0
        log_login(db, user_id=user.id, email_attempted=user.email, ip_address=request_ip, success=False)
        login_attempts_total.labels(result="failure").inc()
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid code.")
    login_event = log_login(db, user_id=user.id, email_attempted=user.email, ip_address=request_ip, success=True)
    login_attempts_total.labels(result="success").inc()
    user.last_login_at = datetime.now(UTC)
    user.failed_2fa_attempts = 0
    user.failed_2fa_locked_until = None
    db.commit()
    background_tasks.add_task(resolve_and_store_login_location, login_event.id, request_ip)
    token = create_access_token(str(user.id), token_version=user.token_version)
    return TokenResponse(access_token=token, user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
def read_me(current_user: User = Depends(get_current_user)):
    """Returns the current authenticated user's profile."""
    return UserOut.model_validate(current_user)


@router.patch("/me/preferences", response_model=UserOut)
def update_preferences(
    payload: UserPreferencesUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Updates the current user's preferences and profile fields.

    Landing page / theme (U-U-01, U-U-03), pronouns (C-U-18), display name
    (rejected if an org admin has locked it, C-U-16), email digest mode
    (C-N-05), and the general-purpose `ui_preferences` bag (e.g. per-list
    tile/list view mode). `ui_preferences` is shallow-merged into the
    existing bag by top-level key (a reassignment, not an in-place
    mutation, so SQLAlchemy's change-tracking picks it up) rather than
    replaced wholesale, so setting one key never clobbers another.
    """
    if payload.landing_preference is not None:
        current_user.landing_preference = payload.landing_preference
    if payload.theme_preference is not None:
        current_user.theme_preference = payload.theme_preference
    if payload.pronouns is not None:
        current_user.pronouns = payload.pronouns
    if payload.email_digest_mode is not None:
        current_user.email_digest_mode = payload.email_digest_mode
    if payload.ui_preferences is not None:
        current_user.ui_preferences = {**current_user.ui_preferences, **payload.ui_preferences}
    if payload.display_name is not None:
        if current_user.display_name_locked:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Your display name has been locked by an organisation admin.")
        current_user.display_name = payload.display_name
    db.commit()
    db.refresh(current_user)
    return UserOut.model_validate(current_user)


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    payload: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Changes the current user's password (native auth only)."""
    if current_user.auth_backend != "native" or not current_user.password_hash:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Password change is only available for native accounts.")
    if not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Current password is incorrect.")
    current_user.password_hash = hash_password(payload.new_password)
    # Invalidates every access token issued before this moment, including
    # the caller's own current one — otherwise a token stolen before the
    # change keeps working for its full remaining lifetime regardless.
    current_user.token_version += 1
    notifications.notify(
        db, current_user, notification_type=NotificationType.PASSWORD_CHANGED,
        title="Your password was changed",
        body="If you did not make this change, contact your organisation admin immediately.",
    )
    # Hardening-review finding: password/2FA changes are security-critical
    # account events with no other audit trail (the in-app notification
    # above is user-facing, not an admin-visible record) — every other
    # sensitive mutation in this codebase calls log_event, this one hadn't.
    log_event(db, entity_type="user", entity_id=current_user.id, action="password_changed", actor_id=current_user.id)
    db.commit()


@router.post("/2fa/enroll", response_model=TwoFactorEnrollResponse)
def enroll_2fa(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Starts 2FA enrollment: generates a secret and a QR code to scan (C-U-14).

    2FA is not yet active — the user must call `/2fa/confirm` with a code
    generated from the scanned secret before `is_2fa_enabled` is set.
    """
    secret = totp.generate_secret()
    current_user.totp_secret = secret
    db.commit()
    return TwoFactorEnrollResponse(
        secret=secret,
        otpauth_uri=totp.provisioning_uri(secret, current_user.email),
        qr_code_png_base64=totp.provisioning_qr_code_png_base64(secret, current_user.email),
    )


@router.post("/2fa/confirm", status_code=status.HTTP_204_NO_CONTENT)
def confirm_2fa(
    payload: TwoFactorConfirmRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Confirms 2FA enrollment by verifying a code from the authenticator app."""
    if not current_user.totp_secret:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Call /2fa/enroll first.")
    if not totp.verify_code(current_user.totp_secret, payload.code):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid code.")
    current_user.is_2fa_enabled = True
    log_event(db, entity_type="user", entity_id=current_user.id, action="2fa_enabled", actor_id=current_user.id)
    db.commit()


@router.post("/2fa/disable", status_code=status.HTTP_204_NO_CONTENT)
def disable_2fa(
    payload: TwoFactorDisableRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Disables 2FA; requires a currently-valid code to prove ongoing control of the authenticator."""
    if not current_user.is_2fa_enabled or not current_user.totp_secret:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "2FA is not enabled.")
    if not totp.verify_code(current_user.totp_secret, payload.code):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid code.")
    current_user.is_2fa_enabled = False
    current_user.totp_secret = None
    # Same rationale as change_password: a token issued while 2FA was still
    # on shouldn't silently keep working past this point.
    current_user.token_version += 1
    log_event(db, entity_type="user", entity_id=current_user.id, action="2fa_disabled", actor_id=current_user.id)
    db.commit()


@router.post("/me/avatar", response_model=UserOut)
async def upload_avatar(
    file: UploadFile = File(...), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """Uploads a profile avatar image (C-U-18)."""
    org_id = db.scalar(select(UserOrgRole.organization_id).where(UserOrgRole.user_id == current_user.id))
    if org_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You must belong to an organisation to upload an avatar.")
    data = await file.read()
    asset = upload_file(
        db, organization_id=org_id, uploaded_by=current_user.id,
        filename=file.filename or "avatar", content_type=file.content_type or "application/octet-stream", data=data,
    )
    db.flush()
    current_user.avatar_file_id = asset.id
    db.commit()
    db.refresh(current_user)
    return UserOut.model_validate(current_user)


@router.delete("/me/avatar", response_model=UserOut)
def clear_avatar(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Removes the current user's avatar."""
    current_user.avatar_file_id = None
    db.commit()
    db.refresh(current_user)
    return UserOut.model_validate(current_user)
