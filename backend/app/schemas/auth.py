"""
Module: schemas.auth

Request/response models for authentication and the current user's own
profile/preferences (C-U-17, U-U-01, U-U-03), two-factor auth (C-U-14),
and self-service profile fields (C-U-16, C-U-18).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.models.enums import OrgRole, ProjectRole
from app.models.notification import DigestMode


class LoginRequest(BaseModel):
    """Credentials submitted to the login endpoint."""

    email: EmailStr
    password: str


class SignupRequest(BaseModel):
    """Public self-registration request (`routers/auth.py::signup`).

    `invite_token`, when present and valid, bypasses `ServerSettings.
    signup_mode` entirely — an explicit admin invite is authorization
    enough regardless of whether public signup is otherwise open. Without
    it, `signup_mode` and (for `org_specified`) a matching organisation
    domain gate whether the account is created at all.
    """

    email: EmailStr
    password: str = Field(min_length=8)
    display_name: str = Field(min_length=1, max_length=255)
    invite_token: str | None = None


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
    ui_preferences: dict[str, Any] = Field(default_factory=dict)


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
    ui_preferences: dict[str, Any] | None = Field(
        default=None,
        description="Partial update, shallow-merged into the existing bag by top-level key rather than "
        "replacing it wholesale — setting one key (e.g. a single list's tile/list choice) never needs to "
        "know or resend every other key already stored.",
    )


class MyOrgGroupOut(BaseModel):
    """One org group the caller belongs to, per `GET /auth/me/memberships`."""

    id: UUID
    name: str
    direct: bool = Field(description="False if membership is only via a nested (ancestor) group.")


class MyProjectMembershipOut(BaseModel):
    id: UUID
    name: str
    roles: list[ProjectRole]


class MyOrgMembershipOut(BaseModel):
    organization_id: UUID
    organization_name: str
    org_roles: list[OrgRole]
    groups: list[MyOrgGroupOut]
    projects: list[MyProjectMembershipOut]


class MyMembershipsOut(BaseModel):
    """The current user's full cross-org membership picture — org roles,
    org-group membership (direct and inherited via nesting), and per-
    project roles — for the self-service "My groups & roles" view
    (`PreferencesPage.tsx`) and reused by the server-admin access-review
    directory (`GET /system/users`) for the same data about *other* users.
    """

    organizations: list[MyOrgMembershipOut]
