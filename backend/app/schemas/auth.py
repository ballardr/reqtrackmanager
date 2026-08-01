"""
Module: schemas.auth

Request/response models for authentication and the current user's own
profile/preferences (C-U-17, U-U-01, U-U-03), two-factor auth (C-U-14),
and self-service profile fields (C-U-16, C-U-18).
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.models.notification import DigestMode


class LoginRequest(BaseModel):
    """Credentials submitted to the login endpoint."""

    email: EmailStr
    password: str


class UserOut(BaseModel):
    """A user as returned to API clients (never includes password_hash/totp_secret)."""

    model_config = {"from_attributes": True}

    id: UUID
    email: str
    display_name: str
    is_server_admin: bool
    is_active: bool
    landing_preference: str
    theme_preference: str
    pronouns: str | None = None
    avatar_file_id: UUID | None = None
    display_name_locked: bool
    is_2fa_enabled: bool
    email_digest_mode: DigestMode


class TokenResponse(BaseModel):
    """Successful (fully authenticated) login response."""

    access_token: str
    token_type: str = "bearer"
    user: UserOut


class TwoFactorChallengeResponse(BaseModel):
    """Returned instead of `TokenResponse` when the account has 2FA enabled."""

    requires_2fa: bool = True
    challenge_token: str


class TwoFactorVerifyRequest(BaseModel):
    """Second step of a two-factor login: exchange the challenge + code for a real token."""

    challenge_token: str
    code: str


class TwoFactorEnrollResponse(BaseModel):
    """Returned when starting 2FA enrollment; scan the QR code in an authenticator app."""

    secret: str
    otpauth_uri: str
    qr_code_png_base64: str


class TwoFactorConfirmRequest(BaseModel):
    """Confirms enrollment by proving the authenticator app produces valid codes."""

    code: str


class TwoFactorDisableRequest(BaseModel):
    """Disables 2FA; requires a currently-valid code to prove the caller still controls it."""

    code: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)


class UserPreferencesUpdate(BaseModel):
    """User-editable preferences and profile fields (U-U-01, U-U-03, C-U-18).

    `display_name` is rejected with 403 if the user's org admin has locked
    it (C-U-16).
    """

    landing_preference: str | None = Field(default=None, description="'auto', 'overview', or a project id")
    theme_preference: str | None = Field(default=None, pattern="^(light|dark|system)$")
    display_name: str | None = Field(default=None, max_length=255)
    pronouns: str | None = Field(default=None, max_length=50)
    email_digest_mode: DigestMode | None = None
