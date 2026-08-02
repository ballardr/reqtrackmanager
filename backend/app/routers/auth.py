"""
Module: routers.auth

Login (including the optional two-factor second step, C-U-14), current-user
profile/preferences (C-U-16, C-U-18, C-N-05), password change, and TOTP
enrollment/disable endpoints. Login attempts are always logged (C-A-07) and
counted (metrics) regardless of outcome.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth_backends.native import NativeAuthBackend
from app.database import get_db
from app.deps import get_client_ip, get_current_user
from app.metrics import login_attempts_total
from app.models.notification import NotificationType
from app.models.organization import UserOrgRole
from app.models.user import User
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
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
from app.services.audit import log_login
from app.services.files import upload_file
from app.services.geoip import resolve_and_store_login_location

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
_native_backend = NativeAuthBackend()


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

    token = create_access_token(str(result.user.id), token_version=result.user.token_version)
    return TokenResponse(access_token=token, user=UserOut.model_validate(result.user))


@router.post("/2fa/verify", response_model=TokenResponse)
def verify_2fa(payload: TwoFactorVerifyRequest, db: Session = Depends(get_db)):
    """Completes a two-factor login: exchanges a challenge token + TOTP code for an access token."""
    claims = decode_access_token(payload.challenge_token)
    if not claims or claims.get("purpose") != "2fa_challenge" or "sub" not in claims:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired challenge.")
    user = db.get(User, UUID(claims["sub"]))
    if user is None or not user.is_active or user.is_archived or not user.is_2fa_enabled or not user.totp_secret:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired challenge.")
    if not totp.verify_code(user.totp_secret, payload.code):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid code.")
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
    (rejected if an org admin has locked it, C-U-16), and email digest mode
    (C-N-05).
    """
    if payload.landing_preference is not None:
        current_user.landing_preference = payload.landing_preference
    if payload.theme_preference is not None:
        current_user.theme_preference = payload.theme_preference
    if payload.pronouns is not None:
        current_user.pronouns = payload.pronouns
    if payload.email_digest_mode is not None:
        current_user.email_digest_mode = payload.email_digest_mode
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
