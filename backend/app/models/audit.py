"""
Module: models.audit

Generic audit trail models. `AuditEvent` captures creation/modification of
organisational and project structures (groups, roles, projects, stages,
components/categories) that don't otherwise have their own version history
table (C-A-05). `LoginEvent` captures authentication attempts (C-A-07).

Note on C-A-08 (recording when a notification was read): the notification
feature itself (C-N-01..05) is entirely Pelion (v2) scope, so there is
nothing for a "notification read" event to attach to in Ossa (v1). This is
flagged in docs/decisions.md as a documentation dependency rather than
implemented speculatively ahead of the feature it depends on.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import UUIDPKMixin


class AuditEvent(UUIDPKMixin, Base):
    """A single logged action against an entity.

    Attributes:
        entity_type: Short name of the entity affected, e.g. "project",
            "project_group", "requirement", "change_request".
        entity_id: Primary key of the affected entity.
        action: What happened, e.g. "created", "updated", "archived",
            "approved", "member_added".
        actor_id: The user who performed the action; null for system
            actions.
        detail: Optional structured detail (e.g. changed fields).
    """

    __tablename__ = "audit_events"

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True)
    entity_type: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(50))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LoginEvent(UUIDPKMixin, Base):
    """A record of a login attempt, successful or not (C-A-07).

    Attributes:
        ip_address: Client IP address as seen by the backend.
        location: Reserved for future IP geolocation enrichment; left null
            in v1 (see docs/decisions.md).
    """

    __tablename__ = "login_events"

    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    email_attempted: Mapped[str] = mapped_column(String(255))
    ip_address: Mapped[str] = mapped_column(String(64))
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    success: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
