"""
Module: models.announcement

Announcements: a short plain-text message shown on the login pages and as a banner after sign-in.

Responsibilities:
- `Announcement`: one message, server-wide (`organization_id` NULL, written by a server administrator)
  or for one organisation (written by that organisation's administrators).

Design decisions:
- One table with a nullable owner, the shape `Tag.project_id` and the organisation/server defaults use,
  so the two scopes share one service, one API shape and one screen.
- `starts_at`/`ends_at` are past or future instants stored in UTC (a window the browser chose in local
  time); both are optional, so a message with neither is always active until deleted.
- `notified_at` records the one-time send as a notification; a second send is refused while it is set.
- Severity is a closed vocabulary (information, warning, critical) stored as a plain varchar.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, UUIDPKMixin, str_enum


class AnnouncementSeverity(str, enum.Enum):
    """How prominently a message is shown."""

    INFORMATION = "information"
    WARNING = "warning"
    CRITICAL = "critical"


class Announcement(UUIDPKMixin, TimestampMixin, Base):
    """A scheduled message for the whole platform or for one organisation.

    Attributes:
        organization_id: Owning organisation; NULL for a server-wide message.
        title: Short heading (plain text).
        body: Message text (plain text; rendered without links or markup).
        severity: Presentation level.
        starts_at: First instant the message is active; NULL means already active.
        ends_at: First instant the message is no longer active; NULL means no end.
        show_on_login: Whether the unauthenticated login pages show it.
        notified_at: When it was sent as a notification; NULL until sent.
        notified_count: How many people that send reached.
        created_by: The author, kept for audit; never returned by a public endpoint.
    """

    __tablename__ = "announcements"
    __table_args__ = (Index("ix_announcements_organization_id", "organization_id"),)

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(120))
    body: Mapped[str] = mapped_column(Text, default="")
    severity: Mapped[AnnouncementSeverity] = mapped_column(
        str_enum(AnnouncementSeverity, 20), default=AnnouncementSeverity.INFORMATION
    )
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    show_on_login: Mapped[bool] = mapped_column(Boolean, default=False)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notified_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
