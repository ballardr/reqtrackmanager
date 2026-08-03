"""
Module: models.user

Defines the User model. Users are identity-backend agnostic (C-U-06): the
`auth_backend` and `external_subject` columns allow a user to be sourced from
the native credential store or, in future, an external OAuth/SSO provider
(C-U-07) without changing the shape of the rest of the schema.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, UUIDPKMixin, str_enum
from app.models.encrypted_type import EncryptedString
from app.models.notification import DigestMode


class User(UUIDPKMixin, TimestampMixin, Base):
    """A person who can authenticate into the system.

    Attributes:
        email: Unique login identifier and contact address (C-U-17).
        display_name: Human-readable name shown throughout the UI.
        password_hash: Bcrypt hash of the user's password; null for users
            sourced entirely from an external auth backend.
        auth_backend: Identifies which AuthBackend authenticates this user
            (e.g. "native"), supporting pluggable identity backends (C-U-06).
        external_subject: Opaque subject identifier from an external auth
            backend, when applicable.
        is_active: Whether the user can currently authenticate (C-U-04).
        is_archived: Whether the user has been archived after deactivation,
            hiding them from user lists while preserving attribution on their
            past contributions (C-U-05).
        is_server_admin: Grants the cross-tenant server admin role, which can
            create organisations and organisation users but has no access to
            organisation data (I-M-05).
        landing_preference: Where the user is sent after login ("auto",
            "overview", or a specific project id) (U-U-03).
        theme_preference: UI theme choice ("light", "dark", or "system").
        ui_preferences: General-purpose bag for lightweight UI display
            preferences that don't (yet, or ever) warrant their own typed
            column — e.g. per-list tile/list view mode, keyed
            `view_mode:<page>` (`"view_mode:requirements": "tiles"`).
            Deliberately generic (mirroring `Organization.
            sso_group_mappings`'s precedent for "structured but open-ended,
            rarely queried" per-row data) so a future preference of this
            same low-stakes, display-only shape is just a new key, not a
            schema change — synced across devices/sessions, unlike
            equivalent client-only localStorage.
        pronouns: Optional self-set pronouns (C-U-18).
        avatar_file_id: Optional uploaded avatar image (C-U-18). Uses
            `use_alter` since `file_assets` itself references `users`
            (uploaded_by), which would otherwise form a FK creation cycle.
        display_name_locked: When set by an org admin, the user can no
            longer change their own display name (C-U-16).
        is_2fa_enabled: Whether TOTP two-factor auth is active for this
            user (C-U-14). Only meaningful for the native auth backend.
        totp_secret: The TOTP secret, set on enrollment and only "live"
            once `is_2fa_enabled` is True; never returned via the API.
            Encrypted at rest at the application layer (`EncryptedString`,
            SOC 2 hardening pass) — the column stores Fernet ciphertext, not
            the plaintext secret, so a database compromise alone doesn't
            expose it.
        failed_2fa_attempts: Count of consecutive failed `/2fa/verify`
            codes since the last success (or the last lockout). Hardening
            review finding: a stolen password plus an unthrottled 2FA
            challenge (6-digit TOTP, a bounded keyspace, re-mintable via a
            fresh `/login` call every time the 5-minute challenge token
            expires) let an attacker converge toward a near-certain bypass
            given enough repeated windows. This is a per-*account* counter,
            not per-challenge-token, so restarting the login flow for a
            fresh token does not reset it.
        failed_2fa_locked_until: Set once `failed_2fa_attempts` crosses the
            threshold (see `verify_2fa`); further 2FA verification is
            rejected outright until this time passes, regardless of code
            correctness or how many new challenge tokens are minted.
        email_digest_mode: Whether email notifications are sent instantly,
            batched into a daily digest, or not at all (C-N-05).
        token_version: Access tokens are stateless JWTs with no revocation
            list, so without this, a token issued before a password change
            or 2FA disable would keep working until its own natural expiry
            even after the user "locks out" a compromised session by
            changing credentials. Embedded in every issued token as `tv`;
            incremented on password change and 2FA disable, immediately
            invalidating every token issued before the increment — including
            the very token used to make that change, deterministically,
            with no clock-precision ambiguity (a wall-clock timestamp
            comparison was tried first and rejected: JWT `iat` is only
            second-precision, so a token issued in the same second as its
            own revocation would otherwise compare as still-valid).
    """

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(255))
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    auth_backend: Mapped[str] = mapped_column(String(50), default="native")
    external_subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Per OIDC spec, `sub` is only guaranteed unique *within a single
    # issuer*, not globally — this is matched alongside external_subject so
    # two different, unrelated IdPs (e.g. different orgs' independently
    # configured providers) can never collide on the same subject value and
    # resolve to the same account (E-U-01 hardening).
    oidc_issuer: Mapped[str | None] = mapped_column(String(500), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    is_server_admin: Mapped[bool] = mapped_column(Boolean, default=False)

    landing_preference: Mapped[str] = mapped_column(String(50), default="auto")
    theme_preference: Mapped[str] = mapped_column(String(20), default="system")
    ui_preferences: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    pronouns: Mapped[str | None] = mapped_column(String(50), nullable=True)
    avatar_file_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("file_assets.id", use_alter=True, name="fk_users_avatar_file_id", ondelete="SET NULL"),
        nullable=True,
    )
    display_name_locked: Mapped[bool] = mapped_column(Boolean, default=False)

    is_2fa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    totp_secret: Mapped[str | None] = mapped_column(EncryptedString(255), nullable=True)
    failed_2fa_attempts: Mapped[int] = mapped_column(Integer, default=0)
    failed_2fa_locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    email_digest_mode: Mapped[DigestMode] = mapped_column(str_enum(DigestMode, 20), default=DigestMode.INSTANT)

    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    token_version: Mapped[int] = mapped_column(Integer, default=0)
    # Massif (v3) C-A-13: stamped on every successful login (native or 2FA
    # completion), used by the access-review user-directory filters
    # (stale_since_days / never_logged_in) in routers/orgs.py and system.py.
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    org_roles: Mapped[list[UserOrgRole]] = relationship(back_populates="user")  # noqa: F821
