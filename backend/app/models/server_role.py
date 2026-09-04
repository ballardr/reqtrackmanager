"""
Module: models.server_role

Server-tier (cross-tenant) role grants, additive to `User.is_server_admin`
(compliance-module-plan.md Phase 0 — the module system's foundational RBAC
extension). Kept as its own module rather than folded into
`models.organization` (where `UserOrgRole` lives) since this is genuinely
server-wide, not organisation-scoped, infrastructure.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, UUIDPKMixin, str_enum
from app.models.enums import ServerRole


class UserServerRole(UUIDPKMixin, TimestampMixin, Base):
    """Grants a user a server-tier role, mirroring `UserOrgRole`'s shape.

    Only `ServerRole.MODULE_ADMINISTRATOR` is ever actually written here in
    V1 — `ServerRole.SERVER_ADMIN`-equivalent power stays exclusively on
    `User.is_server_admin`, never duplicated into a row here, so there is
    never a second, independently-driftable source of truth for it (see
    `ServerRole`'s own docstring).

    Attributes:
        user_id: The user being granted the role.
        role: The server role granted (in practice, always
            `MODULE_ADMINISTRATOR` — see class docstring).
        granted_at: When the grant was made (`TimestampMixin.created_at`
            serves this; no separate column).
        granted_by: The server admin who made the grant, for audit
            attribution independent of `AuditEvent.actor_id` (which is also
            logged at the call site) — mirrors the same "who granted this"
            need `PersonalAccessToken`/`invites` track locally on the row.
    """

    __tablename__ = "server_roles"
    __table_args__ = (UniqueConstraint("user_id", "role"),)

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    role: Mapped[ServerRole] = mapped_column(str_enum(ServerRole))
    granted_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
