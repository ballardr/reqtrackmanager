"""
Module: models.requirement

Defines requirements and their supporting structures: versioned content
(temporal history, C-A-02), traceability links (C-G-09), keywords (C-M-01),
and per-stage approval baselines (C-G-10).

Design decision: rather than a single mutable row with valid_from/valid_to
columns, the `Requirement` row holds only stable identity fields
(project/component/category, generated unique code, creator, archival flag)
and `RequirementVersion` rows hold every mutable attribute plus
valid_from/valid_to/version_number. The current version is the row with
valid_to IS NULL. This keeps identity stable while giving a complete,
queryable history for audit and baselining.
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
from app.models.enums import RequirementLevel, RequirementReviewOutcome, RequirementStatus


class Requirement(UUIDPKMixin, TimestampMixin, Base):
    """A requirement's stable identity within a project.

    Attributes:
        unique_code: Human-readable identifier combining the component and
            category prefixes with a per-project sequence number, e.g.
            "SW-PERF-014" (C-G-06, C-G-07). Never reused, even for archived
            requirements.
        is_archived: Soft-delete flag; archived requirements are hidden from
            default views but their full version history is preserved
            (C-A-06).
        is_completed: Overlay marker (C-G-11) — "independently of lifecycle
            state, a requirement may be marked completed... subject to the
            potential of periodic review where it may later be reversed to
            non-compliant." Deliberately not a `RequirementStatus` value:
            completion sits on top of the `approved` lifecycle status rather
            than replacing it, so a completed requirement's `status` stays
            `approved` throughout (see `services.requirements.LOCKED_STATUSES`
            and `routers.requirements.complete_requirement`/
            `uncomplete_requirement`, which set/clear these three fields
            directly rather than writing a new `RequirementVersion` — marking
            something complete doesn't change its content). `completed_at`/
            `completed_by` mirror `archived_at`/`archived_by`'s own shape.
            Cleared automatically when a `FAILED` review outcome is recorded
            against a completed requirement (`record_review_outcome`) — the
            concrete mechanism behind C-G-11's "reversed to non-compliant...
            when a review/audit occurs" — or explicitly by a project manager
            approving a change request with `clear_completion=True`
            (`decide_change_request`).
    """

    __tablename__ = "requirements"
    __table_args__ = (UniqueConstraint("project_id", "unique_code"),)

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"))
    component_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_components.id", ondelete="CASCADE")
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_categories.id", ondelete="CASCADE")
    )
    unique_code: Mapped[str] = mapped_column(String(64), index=True)
    creator_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))

    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    is_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    versions: Mapped[list[RequirementVersion]] = relationship(
        back_populates="requirement", order_by="RequirementVersion.version_number"
    )


class RequirementVersion(UUIDPKMixin, Base):
    """A single point-in-time snapshot of a requirement's content.

    Attributes:
        valid_from / valid_to: Effective time interval; valid_to is null for
            the current version (temporal model per solution-architecture.md).
        owner_id: The user responsible for the requirement content
            (C-G-13).
        approval_authority_id: The user who approved this version, set when
            status transitions to approved (C-G-13).
        change_request_id: If this version resulted from an approved change
            request rather than a direct scoping-stage edit, points to it
            (enforces C-G-12).
        change_note: Free-text reason for the change, shown in the change
            log (C-A-09).
    """

    __tablename__ = "requirement_versions"
    __table_args__ = (UniqueConstraint("requirement_id", "version_number"),)

    requirement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("requirements.id", ondelete="CASCADE")
    )
    version_number: Mapped[int] = mapped_column(Integer)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    name: Mapped[str] = mapped_column(String(500))
    reasoning: Mapped[str] = mapped_column(Text, default="")
    clarification: Mapped[str] = mapped_column(Text, default="")
    # Free-text elaboration, distinct from reasoning (why the requirement
    # exists) and clarification (scope/edge-case notes) — optional, blank by
    # default. Governed by the same creation-or-change-request-only rule as
    # every other content field once a requirement is locked (C-G-12).
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[RequirementStatus] = mapped_column(str_enum(RequirementStatus, 20), default=RequirementStatus.DRAFT)
    # Which project stage/release this content is targeted at, and whether it's
    # mandatory or advisory (mock's "Target"/"Level" fields) — display/planning
    # metadata on the version, not gating logic. target_stage_id is mandatory
    # (a requirement must always be targeted at some stage), so its FK can no
    # longer be ON DELETE SET NULL (that would itself violate the NOT NULL
    # constraint). CASCADE instead: there is no API path that ever deletes a
    # single ProjectStage row on its own (no DELETE /stages/{id} endpoint
    # exists) — the only way one is ever removed is as part of its whole
    # project/organisation being deleted, at which point every
    # RequirementVersion referencing it is being deleted in that same
    # cascade anyway (see services/org_deletion.py's module docstring for
    # why this codebase leans on DB-level cascades for exactly this kind of
    # bulk teardown).
    target_stage_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_stages.id", ondelete="CASCADE"), nullable=False
    )
    level: Mapped[RequirementLevel] = mapped_column(str_enum(RequirementLevel, 20), default=RequirementLevel.REQUIREMENT)
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    approval_authority_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    # Values for this project's custom attribute definitions (C-C-01, C-C-02),
    # keyed by CustomFieldDefinition id. Stored here rather than in a separate
    # versioned table so custom-field changes are captured by the same
    # version-history/change-log mechanism as the standard fields.
    custom_fields: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    change_request_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("change_requests.id", ondelete="SET NULL"), nullable=True
    )
    change_note: Mapped[str] = mapped_column(Text, default="")

    # Massif (v3) review scheduling (C-R-06/08/10). These live on the
    # versioned table, not the Requirement identity row, because C-R-06's
    # clarification requires them to only change on creation or via a change
    # request — the same CR-gated path already used by name/reasoning/etc.
    review_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    review_lead_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    review_reminder_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    requirement: Mapped[Requirement] = relationship(back_populates="versions")


class RequirementKeyword(UUIDPKMixin, Base):
    """A search keyword/tag attached to a requirement (C-M-01)."""

    __tablename__ = "requirement_keywords"
    __table_args__ = (UniqueConstraint("requirement_id", "keyword"),)

    requirement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("requirements.id", ondelete="CASCADE")
    )
    keyword: Mapped[str] = mapped_column(String(100), index=True)


class RequirementLink(UUIDPKMixin, TimestampMixin, Base):
    """A traceability link between two requirements (C-G-09).

    `link_type_id` replaces the previous fixed `RequirementLinkType` enum
    (migration 0012) — see `RequirementLinkTypeDefinition`'s docstring for
    why link types became an org-definable table. Links are **not** gated
    by a requirement's lock state (`services.requirements.is_locked`):
    traceability metadata isn't "requirement content" under C-G-12 any more
    than a `ReviewComment` is (this codebase already treats discussion
    threads as outside the change-log/lock boundary; links get the same
    treatment).
    """

    __tablename__ = "requirement_links"
    # Explicit short name: the default-generated name for this 3-column
    # constraint is 78 bytes, over Postgres's 63-byte NAMEDATALEN limit and
    # thus silently truncated/unpredictable — see
    # `RequirementLinkTypeDefinition`'s __table_args__ comment for the same
    # issue and this codebase's established fix (migration 0009).
    __table_args__ = (
        UniqueConstraint(
            "source_requirement_id", "target_requirement_id", "link_type_id",
            name="uq_requirement_links_source_target_type",
        ),
    )

    source_requirement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("requirements.id", ondelete="CASCADE")
    )
    target_requirement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("requirements.id", ondelete="CASCADE")
    )
    link_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("requirement_link_type_definitions.id")
    )
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))


class Baseline(UUIDPKMixin, TimestampMixin, Base):
    """An immutable snapshot of a project stage's approved requirements (C-G-10)."""

    __tablename__ = "baselines"

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"))
    stage_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_stages.id", ondelete="CASCADE")
    )
    label: Mapped[str] = mapped_column(String(255))
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))

    items: Mapped[list[BaselineItem]] = relationship(back_populates="baseline")


class BaselineItem(UUIDPKMixin, Base):
    """One requirement's snapshot version captured within a baseline."""

    __tablename__ = "baseline_items"
    __table_args__ = (UniqueConstraint("baseline_id", "requirement_id"),)

    baseline_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("baselines.id", ondelete="CASCADE"))
    requirement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("requirements.id", ondelete="CASCADE")
    )
    requirement_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("requirement_versions.id", ondelete="CASCADE")
    )

    baseline: Mapped[Baseline] = relationship(back_populates="items")


class RequirementReview(UUIDPKMixin, Base):
    """A recorded outcome of a requirement's scheduled review (C-R-07).

    Recording an outcome does not change `RequirementVersion.review_date`
    itself (that field only changes on creation or via a change request,
    per C-R-06) — instead, a requirement drops off the "due for review" list
    once a `RequirementReview` exists with `reviewed_at >= review_date`,
    until a future change request sets a new review date.
    """

    __tablename__ = "requirement_reviews"

    requirement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("requirements.id", ondelete="CASCADE")
    )
    requirement_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("requirement_versions.id", ondelete="CASCADE")
    )
    reviewed_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[RequirementReviewOutcome] = mapped_column(str_enum(RequirementReviewOutcome, 20))
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
