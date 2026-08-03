"""
Module: models.change_request

Defines change requests: the formal mechanism for proposing a new
requirement or modifying an approved one (introduction, C-G-03, C-G-12).
Mirrors the requirement versioning pattern so every edit to a change
request's proposed content is itself logged (C-A-04).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, UUIDPKMixin, str_enum
from app.models.enums import (
    ChangeRequestKind,
    ChangeRequestStatus,
    ChangeRequestVoteChoice,
    RequirementLevel,
    ReviewTargetType,
)


class ChangeRequest(UUIDPKMixin, TimestampMixin, Base):
    """A proposal to add or modify a requirement, subject to review/approval.

    Attributes:
        requirement_id: The requirement being modified; null when kind is
            NEW_REQUIREMENT (the requirement does not exist yet).
        creator_id: The user who authored the change request (C-G-13).
        decided_by / decided_at: Set when a project manager approves or
            rejects the change request.
    """

    __tablename__ = "change_requests"

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"))
    requirement_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("requirements.id", ondelete="SET NULL"), nullable=True
    )
    kind: Mapped[ChangeRequestKind] = mapped_column(str_enum(ChangeRequestKind))
    status: Mapped[ChangeRequestStatus] = mapped_column(str_enum(ChangeRequestStatus, 20), default=ChangeRequestStatus.DRAFT)

    creator_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    decision_note: Mapped[str] = mapped_column(Text, default="")

    versions: Mapped[list[ChangeRequestVersion]] = relationship(
        back_populates="change_request", order_by="ChangeRequestVersion.version_number"
    )


class ChangeRequestVersion(UUIDPKMixin, Base):
    """A snapshot of a change request's proposed content and justification.

    Attributes:
        reason: Why the change is being requested and wasn't identified
            during original scoping (introduction requirement for CR
            submissions).
        proposed_component_id / proposed_category_id: Only meaningful for
            NEW_REQUIREMENT change requests.
    """

    __tablename__ = "change_request_versions"
    __table_args__ = (UniqueConstraint("change_request_id", "version_number"),)

    change_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("change_requests.id", ondelete="CASCADE")
    )
    version_number: Mapped[int] = mapped_column(Integer)

    proposed_name: Mapped[str] = mapped_column(String(500))
    proposed_reasoning: Mapped[str] = mapped_column(Text, default="")
    proposed_clarification: Mapped[str] = mapped_column(Text, default="")
    proposed_component_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_components.id", ondelete="SET NULL"), nullable=True
    )
    proposed_category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_categories.id", ondelete="SET NULL"), nullable=True
    )
    # Mirrors Requirement/RequirementVersion's target_stage_id/level (mock's
    # "Target"/"Level" fields) so a change request can propose changing them,
    # same as it can propose changing name/reasoning/clarification.
    proposed_target_stage_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_stages.id", ondelete="SET NULL"), nullable=True
    )
    proposed_level: Mapped[RequirementLevel] = mapped_column(
        str_enum(RequirementLevel, 20), default=RequirementLevel.REQUIREMENT
    )
    # Mirrors RequirementVersion's review-scheduling fields (C-R-06/08/10) so
    # a change request can propose setting/changing them, same as any other
    # requirement content — review_date can only change via this path once a
    # requirement is approved.
    proposed_review_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    proposed_review_lead_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    proposed_reviewer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    reason: Mapped[str] = mapped_column(Text)
    # Values for this project's custom change-request attribute definitions
    # (C-C-01, C-C-02), keyed by CustomFieldDefinition id.
    custom_fields: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    change_request: Mapped[ChangeRequest] = relationship(back_populates="versions")


class ReviewComment(UUIDPKMixin, TimestampMixin, Base):
    """A discussion thread comment on a requirement or change request (C-R-01).

    Kept separate from RequirementVersion/ChangeRequestVersion history so the
    UI change log can exclude discussion comments as required (C-A-09
    clarification).
    """

    __tablename__ = "review_comments"

    target_type: Mapped[ReviewTargetType] = mapped_column(str_enum(ReviewTargetType, 20))
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    author_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)


class ChangeRequestTask(UUIDPKMixin, TimestampMixin, Base):
    """A task assigned during a change request's review (C-R-02, C-R-04)."""

    __tablename__ = "change_request_tasks"

    change_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("change_requests.id", ondelete="CASCADE")
    )
    description: Mapped[str] = mapped_column(Text)
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_done: Mapped[bool] = mapped_column(Boolean, default=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))


class ChangeRequestVote(UUIDPKMixin, Base):
    """A stakeholder's advisory vote on a change request's approval (C-R-03).

    Advisory only — does not change `ChangeRequest.status` or bypass the
    project manager's own approve/reject decision; it's a visible tally the
    decision-maker can see alongside the change request.
    """

    __tablename__ = "change_request_votes"
    __table_args__ = (UniqueConstraint("change_request_id", "user_id"),)

    change_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("change_requests.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    vote: Mapped[ChangeRequestVoteChoice] = mapped_column(str_enum(ChangeRequestVoteChoice, 20))
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    voted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
