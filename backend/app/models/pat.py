"""
Module: models.pat

Defines the PersonalAccessToken model: a long-lived, user-created bearer credential (an alternative to the
12-hour session JWT) for non-interactive integrations such as mcp-server. See docs/decisions.md's
"Personal Access Tokens" section and docs/soc2/policies/access-control-policy.md.

Responsibilities:
- Stores only a SHA-256 hash of the token secret (as `User.password_hash`); the raw token is shown once at
  creation and is unrecoverable.
- Records the organisations the token may be used against (`allowed_organization_ids`), chosen at creation
  from the creator's organisations. It restricts the user's own RBAC roles and never grants beyond them
  (enforced in services/rbac.py).
- `expires_at_ceiling` is the expiry computed from the org and system lifetime caps at creation. The
  effective expiry enforced at authentication is `min(expires_at_ceiling, live caps of the scoped orgs)`
  (deps.py), so tightening an org cap shortens matching tokens without changing the stored column.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, UUIDPKMixin


class PersonalAccessToken(UUIDPKMixin, TimestampMixin, Base):
    """A long-lived, org-scoped bearer credential a user creates for themselves.

    Attributes:
        user_id: The owning user: the token authenticates as this account.
        created_by_user_id: The issuer (see the column note).
        name: User-chosen label to help distinguish their own tokens.
        token_hash: SHA-256 hex digest of the raw token secret
            (`security.hash_pat`). The raw secret itself is never stored.
        token_prefix: First ~14 characters of the raw token, stored in
            plaintext purely so the UI list can help a user recognise which
            token is which without ever re-displaying the full secret.
        allowed_organization_ids: The organisations this token may be used
            against, as a list of UUID strings — chosen by the creating
            user from their own org memberships at creation time.
        allowed_project_ids: Optional further restriction, as a list of UUID
            strings, to specific projects within the allowed orgs — e.g. an
            integration that should only ever touch one project. Empty
            (the default) means no extra restriction: the token reaches
            every project the user's own RBAC roles grant them within the
            allowed orgs, same as before this field existed.
        expires_at_ceiling: The expiry computed at creation time from the
            org/system lifetime caps then in effect. See module docstring
            for why the *effective* expiry enforced at auth time can be
            earlier than this (never later).
        revoked_at: When set, the token is dead regardless of expiry —
            set by the owner, an org admin (for tokens touching their
            org), or a server admin (platform-wide), independently of
            `User.token_version`. A routine password change leaves PATs alone (an integration is not
            reconfigured by it); a password reset through an emailed link, switching two-factor
            authentication off and an administrator's forced reset revoke every token of the person.
        last_used_at: Stamped on successful authentication, throttled to
            at most once per hour to avoid a DB write on every single
            request a busy integration makes.
    """

    __tablename__ = "personal_access_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    #: Who issued the token: the owner for a self-service token, the organisation administrator for a service user's.
    #: Null on a token created before the column existed (read as the owner).
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(255))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    token_prefix: Mapped[str] = mapped_column(String(20))
    allowed_organization_ids: Mapped[list[str]] = mapped_column(JSONB)
    allowed_project_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    expires_at_ceiling: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
