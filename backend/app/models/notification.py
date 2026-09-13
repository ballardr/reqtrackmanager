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
    REQUIREMENT_REVIEW_DUE = "requirement_review_due"
    STAGE_REVIEW_AUTO_APPROVED = "stage_review_auto_approved"

    # Compliance Module (docs/compliance-module-plan.md Phase 10; docs/
    # Compliance_Module_Requirements.md §18) — every event §18 lists.
    # `app.modules.compliance` sends these; kept in this shared core enum
    # (not a module-owned one) since `Notification.type`/`NotificationPreference.
    # type` are core, module-agnostic tables every notification (core or
    # module-contributed) shares — the same reason `NotificationType` itself
    # was never made per-module.
    COMPLIANCE_REQUIRED_ACTION_DUE_SOON = "compliance_required_action_due_soon"
    COMPLIANCE_REQUIRED_ACTION_OVERDUE = "compliance_required_action_overdue"
    COMPLIANCE_TARGET_DATE_APPROACHING = "compliance_target_date_approaching"
    COMPLIANCE_TARGET_DATE_EXCEEDED = "compliance_target_date_exceeded"
    COMPLIANCE_APPROVAL_REQUESTED = "compliance_approval_requested"
    COMPLIANCE_ASSESSMENT_REJECTED = "compliance_assessment_rejected"
    COMPLIANCE_APPROVAL_INVALIDATED = "compliance_approval_invalidated"
    COMPLIANCE_REVIEW_DUE = "compliance_review_due"
    COMPLIANCE_REVIEW_OVERDUE = "compliance_review_overdue"
    COMPLIANCE_EVIDENCE_EXPIRING_SOON = "compliance_evidence_expiring_soon"
    COMPLIANCE_EVIDENCE_EXPIRED = "compliance_evidence_expired"
    COMPLIANCE_REQUIREMENT_NON_COMPLIANT = "compliance_requirement_non_compliant"
    COMPLIANCE_STANDARD_UPDATE_REVIEW_NEEDED = "compliance_standard_update_review_needed"
    COMPLIANCE_ASSIGNMENT_CREATED = "compliance_assignment_created"


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
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )
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
