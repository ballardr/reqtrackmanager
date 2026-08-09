"""
Module: models.pat

Defines the PersonalAccessToken model — a long-lived, user-created bearer
credential (an alternative to the 12-hour session JWT), primarily intended
for non-interactive integrations like mcp-server that shouldn't need
re-authenticating every 12 hours. See docs/decisions.md's "Personal Access
Tokens" section for the full design writeup and docs/soc2/policies/
access-control-policy.md for how this fits the authentication model.

Responsibilities:
- Stores only a SHA-256 hash of the token secret, never the secret itself
  (mirrors how User.password_hash is handled) — the raw token is shown to
  its creator exactly once, at creation, and is unrecoverable afterward.
- Records which organisations the token may be used against
  (`allowed_organization_ids`), chosen by the creating user at creation
  time from among the orgs they belong to. This is a *restriction* layered
  on top of the user's own real RBAC roles, never a grant beyond them —
  services/rbac.py enforces it.
- `expires_at_ceiling` is the expiry computed from org/system lifetime caps
  in effect at creation time. The *effective* expiry actually enforced at
  auth time is `min(expires_at_ceiling, live caps of currently-scoped
  orgs)` — see deps.py — so an org admin tightening their cap later
  retroactively shortens matching tokens' effective lifetime without this
  stored column ever needing to change.
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
        user_id: The owning (and only ever creating) user.
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
            `User.token_version` (a PAT is deliberately not killed by a
            password change/2FA-disable).
        last_used_at: Stamped on successful authentication, throttled to
            at most once per hour to avoid a DB write on every single
            request a busy integration makes.
    """

    __tablename__ = "personal_access_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(255))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    token_prefix: Mapped[str] = mapped_column(String(20))
    allowed_organization_ids: Mapped[list[str]] = mapped_column(JSONB)
    allowed_project_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    expires_at_ceiling: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
