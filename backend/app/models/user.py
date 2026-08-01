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

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, UUIDPKMixin, str_enum
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
        email_digest_mode: Whether email notifications are sent instantly,
            batched into a daily digest, or not at all (C-N-05).
    """

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(255))
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    auth_backend: Mapped[str] = mapped_column(String(50), default="native")
    external_subject: Mapped[str | None] = mapped_column(String(255), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    is_server_admin: Mapped[bool] = mapped_column(Boolean, default=False)

    landing_preference: Mapped[str] = mapped_column(String(50), default="auto")
    theme_preference: Mapped[str] = mapped_column(String(20), default="system")

    pronouns: Mapped[str | None] = mapped_column(String(50), nullable=True)
    avatar_file_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("file_assets.id", use_alter=True, name="fk_users_avatar_file_id"),
        nullable=True,
    )
    display_name_locked: Mapped[bool] = mapped_column(Boolean, default=False)

    is_2fa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    totp_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)

    email_digest_mode: Mapped[DigestMode] = mapped_column(str_enum(DigestMode, 20), default=DigestMode.INSTANT)

    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    org_roles: Mapped[list["UserOrgRole"]] = relationship(back_populates="user")
