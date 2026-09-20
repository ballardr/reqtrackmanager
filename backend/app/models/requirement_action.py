"""
Module: models.requirement_action

Requirement actions: a required task (e.g. a review, a test) needed to
satisfy one or more requirements. Unlike `RequirementReview` (a single
recorded outcome tied to one requirement's scheduled review date, C-R-07),
a `RequirementAction` has its own first-class, project-scoped identity —
its own `unique_code` (mirroring `Requirement.unique_code`) — so a single
action can be linked from multiple requirements via an untyped
`ArtefactLink` row (`models.relationship`, `source_type=
ArtefactType.REQUIREMENT_ACTION`) instead of being owned by exactly one.
Comments on an action reuse the existing generic `ReviewComment`/
`CommentFile` machinery unchanged (`ReviewTargetType.ACTION`), the same way
requirements and change requests already share one discussion-thread model
instead of each having their own.

An action is never hard-deleted, only archived (`is_archived`, mirroring
`Requirement.is_archived`, C-A-06) — the same "preserve history, hide from
default views" rule this codebase already applies to requirements.

Prior to Module 0 (Platform Foundations), Phase 1, action-to-requirement
membership was its own dedicated `RequirementActionLink` join table; that
phase folded it into the generic polymorphic `ArtefactLink` table instead
(an untyped link, `link_type_id IS NULL`) — see `models.relationship`'s
module docstring for the full design.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, UUIDPKMixin, str_enum
from app.models.enums import RequirementActionOutcome


class RequirementAction(UUIDPKMixin, TimestampMixin, Base):
    """A required action (e.g. review, test) needed to satisfy one or more
    requirements.

    Attributes:
        unique_code: Human-readable identifier, e.g. "ACT-003", generated
            once at creation via `Project.next_action_seq` (see
            `services/actions.py`), never reused — same convention as
            `Requirement.unique_code`.
        action_type_id: Which project-defined `ActionTypeDefinition` this
            action is.
        outcome_status: Lifecycle/outcome state (C-A-06-style soft state,
            not a version history — an action has no versioned content the
            way a requirement does).
        assignee_id: The user accountable for completing the action
            (mirrors the accountability pattern already used by requirement
            reviews, C-R-10).
        due_date: When the action is due.
        completed_at / completed_by: Stamped when `outcome_status`
            transitions away from PENDING (to COMPLETED or FAILED) — "when
            was this action's outcome actually recorded", regardless of
            which of the two terminal outcomes it landed on.
        is_archived / archived_at / archived_by: Soft-delete, mirroring
            `Requirement.is_archived` (C-A-06).
    """

    __tablename__ = "requirement_actions"
    __table_args__ = (UniqueConstraint("project_id", "unique_code"),)

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"))
    unique_code: Mapped[str] = mapped_column(String(64), index=True)
    action_type_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("action_type_definitions.id"))
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text, default="")
    outcome_status: Mapped[RequirementActionOutcome] = mapped_column(
        str_enum(RequirementActionOutcome, 20), default=RequirementActionOutcome.PENDING
    )
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    creator_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
