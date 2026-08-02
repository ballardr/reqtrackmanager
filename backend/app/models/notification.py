"""
Module: models.notification

In-app and email notification models (Pelion v2, C-N-01..05). `Notification`
rows back the in-UI notification centre (C-N-02); `NotificationPreference`
lets a user opt in/out of each notification type per channel (C-N-04);
`User.email_digest_mode` (added in models.user) controls whether email
notifications go out instantly, as a daily digest, or not at all (C-N-05).
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import UUIDPKMixin, str_enum


class NotificationType(str, enum.Enum):
    """Notification event types (C-N-01)."""

    PROJECT_JOINED = "project_joined"
    STAGE_SCOPING = "stage_scoping"
    STAGE_REVIEW = "stage_review"
    STAGE_APPROVED = "stage_approved"
    STAGE_COMPLETED = "stage_completed"
    CHANGE_REQUEST_SUBMITTED = "change_request_submitted"
    STAKEHOLDER_INPUT_REQUESTED = "stakeholder_input_requested"
    CHANGE_REQUEST_APPROVED = "change_request_approved"
    CHANGE_REQUEST_REJECTED = "change_request_rejected"
    REQUIREMENTS_UPDATED = "requirements_updated"
    PASSWORD_CHANGED = "password_changed"
    PERMISSION_GRANTED = "permission_granted"
    PERMISSION_REVOKED = "permission_revoked"
    COMMENT_ADDED = "comment_added"


class DigestMode(str, enum.Enum):
    """How often email notifications are sent (C-N-05)."""

    INSTANT = "instant"
    DAILY = "daily"
    NONE = "none"


class Notification(UUIDPKMixin, Base):
    """A single notification event for a user (C-N-01, C-N-02).

    Attributes:
        emailed_at: When the email channel actually sent this notification
            (instantly, or as part of a daily digest batch); null if the
            user has email disabled for this type or digest mode is "none".
    """

    __tablename__ = "notifications"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    type: Mapped[NotificationType] = mapped_column(str_enum(NotificationType, 50))
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text, default="")
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True)
    entity_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    emailed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class NotificationPreference(UUIDPKMixin, Base):
    """Per-user, per-type, per-channel notification opt-in (C-N-04)."""

    __tablename__ = "notification_preferences"
    __table_args__ = (UniqueConstraint("user_id", "type"),)

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    type: Mapped[NotificationType] = mapped_column(str_enum(NotificationType, 50))
    ui_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    email_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
