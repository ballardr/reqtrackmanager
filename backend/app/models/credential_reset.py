"""
Module: models.credential_reset

Defines `CredentialResetToken`: a single-use, expiring secret that lets its holder choose a new
password for one native account without knowing the old one.

Responsibilities:
- Store only a SHA-256 hash of the secret (as `PersonalAccessToken` does), so a database read, a
  backup or a log line never yields a usable link.
- Record who or what issued it (`issued_via`) and when it was spent, so redemption is atomic
  (single use) and the audit trail can name the path without ever holding the secret.

Design decisions:
- Rows are transient credentials, not business data: they are not part of a project or organisation
  bundle, and `dr_stats` counts them like any other table from the catalogue.
- `user_id` cascades on delete: a removed account leaves no live reset link behind.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import UUIDPKMixin, utcnow


class CredentialResetToken(UUIDPKMixin, Base):
    """A hashed, single-use password-reset secret.

    Attributes:
        user_id: The account whose password the token resets.
        token_hash: SHA-256 hex digest of the raw secret (`security.hash_pat`); the secret itself is never
            stored, logged or audited.
        issued_via: How it was issued: `forgot` (the person asked), `admin` (an organisation or server
            administrator sent it), `cli` (the command line, including `--force-reset`).
        issued_by: The administrator who issued it, or `None` for `forgot` and `cli` (the command-line
            actor is recorded in the audit event).
        created_at: When it was issued (UTC).
        expires_at: When it stops working (UTC).
        used_at: When it was redeemed (UTC); a token with this set is dead.
    """

    __tablename__ = "credential_reset_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    issued_via: Mapped[str] = mapped_column(String(20))
    issued_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
