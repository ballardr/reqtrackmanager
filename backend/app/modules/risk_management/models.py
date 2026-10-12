"""
Module: modules.risk_management.models

Data model for the Risk Management module (docs/plans/module-03-risk-
management-plan.md Phase 1):

- `Risk` / `RiskVersion` — identity row plus temporal content snapshots, the
  same split `StakeholderNeed`/`StakeholderNeedVersion` use (Phase 0
  resolution 5: full history). A risk is always project-scoped. Status, the
  inherent/residual scoring levels and the owner are versioned content, so a
  reassessment is a content change like any other.
- `RiskTypeDefinition` / `ProjectRiskType` — the two-tier type vocabulary
  (resolution 2): an org base list plus per-project rename/reorder/disable/add,
  the same shape as Persona/Stakeholder types. `RiskVersion` references a
  project type row (a passthrough row is created the first time an org type is
  chosen), so it carries one type column, not two.
- `RiskTreatmentAssessment` — the verdict on one treatment link (Phase 3,
  resolution 3), kept here so `ArtefactLink` needs no risk-only column.
- `RiskComment` / `RiskCommentFile` / `RiskFile` — module-local comment and
  attachment tables (resolution 8), since extending the core
  `ReviewTargetType` enum would be a per-module edit to a core file.
- `RiskReview` — an immutable record of one periodic review with a snapshot of
  the ratings it was made against (Phase 4), so history survives later changes
  to the matrix.

The inherent and residual ratings are never stored: they are derived on read
from the level columns by core's scoring service, so re-weighting a level or
editing a band or cell rating re-rates every risk with no data migration.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, UUIDPKMixin, str_enum
from app.modules.risk_management.enums import (
    RiskReviewOutcome,
    RiskStatus,
    TreatmentAssessmentStatus,
    TreatmentStrategy,
)


class RiskTypeDefinition(UUIDPKMixin, TimestampMixin, Base):
    """Organisation-scoped base Risk type vocabulary (Safety, Technical, ...
    by default). `sort_order` keeps the name `services.ordering.move_ordered`
    expects.

    Attributes:
        organization_id: The owning organisation.
        name: Display name, unique per organisation.
        sort_order: Display/picker order.
        is_active: Soft-disable — an inactive type drops out of every
            project's effective list without being deleted.
    """

    __tablename__ = "risk_type_definitions"
    __table_args__ = (UniqueConstraint("organization_id", "name", name="uq_risk_type_definitions_org_name"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(100))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class ProjectRiskType(UUIDPKMixin, TimestampMixin, Base):
    """A project's own view onto the Risk type vocabulary: a local override of
    one org type, or a fully project-local type.

    Attributes:
        project_id: The owning project.
        org_type_id: The org type overridden, or `NULL` for a project-local type.
        name_override: Replaces the org type's name here; the type's only name
            when `org_type_id` is `NULL` (enforced by a CHECK).
        display_order_override: Replaces the org type's `sort_order` here.
        is_enabled: Whether the type is offered when creating a risk here.
    """

    __tablename__ = "project_risk_types"
    __table_args__ = (
        UniqueConstraint("project_id", "org_type_id", name="uq_project_risk_types_project_org_type"),
        CheckConstraint(
            "org_type_id IS NOT NULL OR name_override IS NOT NULL", name="ck_project_risk_types_local_has_name"
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"))
    org_type_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("risk_type_definitions.id", ondelete="SET NULL"), nullable=True
    )
    name_override: Mapped[str | None] = mapped_column(String(100), nullable=True)
    display_order_override: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Risk(UUIDPKMixin, TimestampMixin, Base):
    """A Risk's stable identity (always project-scoped).

    Attributes:
        project_id: The owning project.
        unique_code: Project-scoped identifier (e.g. `"RSK-003"`), from
            `services.sequences.generate_unique_code`.
        creator_id: Who created the record.
        is_archived / archived_at / archived_by: Soft-delete.
        review_due_notified_for / review_overdue_notified_for: The `review_date`
            value for which the "review due soon" / "review overdue" notification
            was last sent. Bookkeeping so each sweep notifies once per date; a
            rescheduled review (a new date) re-arms both with no reset step.
    """

    __tablename__ = "risks"
    __table_args__ = (UniqueConstraint("project_id", "unique_code", name="uq_risks_project_unique_code"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    unique_code: Mapped[str] = mapped_column(String(64))
    creator_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    review_due_notified_for: Mapped[date | None] = mapped_column(Date, nullable=True)
    review_overdue_notified_for: Mapped[date | None] = mapped_column(Date, nullable=True)

    versions: Mapped[list[RiskVersion]] = relationship(back_populates="risk", order_by="RiskVersion.version_number")


class RiskVersion(UUIDPKMixin, Base):
    """One point-in-time snapshot of a Risk's content (temporal shape copied
    from `StakeholderNeedVersion`).

    Attributes:
        valid_from / valid_to: Effective interval; `valid_to` is null for the
            current version.
        title: Short display name for lists and links.
        statement: The risk statement (overview §11.2).
        cause / risk_event / consequence: Cause, the event that may occur, and
            what follows from it, as free text. `consequence` is the text;
            the scored Consequence axis is `*_consequence_level_id`.
        project_type_id: The risk's type (a project type row); null when
            untyped. `SET NULL` on delete so the type tables can cascade with
            their project; in-use types are protected at the service layer.
        treatment_strategy: The intended response; null until decided.
        acceptance_criteria: What would make the residual risk acceptable.
        inherent_*_level_id / residual_*_level_id: Levels of the `risk` scoring
            scheme's Likelihood, Consequence and Detectability axes, before and
            after treatment. Null means "not scored on that axis". `SET NULL`
            on delete: deleting an in-use level is blocked by the scheme's
            `count_level_usage` hook (current versions), so only history
            ever loses a reference.
        status: Lifecycle state.
        owner_id: The user responsible for the risk.
        review_date: When the risk is next due for review.
        change_note: Free-text reason for the change.
        created_by / created_at: Who made this snapshot, and when.
    """

    __tablename__ = "risk_versions"
    __table_args__ = (
        UniqueConstraint("risk_id", "version_number"),
        Index("ix_risk_versions_current", "risk_id", unique=False, postgresql_where=sa_text("valid_to IS NULL")),
    )

    risk_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("risks.id", ondelete="CASCADE"))
    version_number: Mapped[int] = mapped_column(Integer)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    title: Mapped[str] = mapped_column(String(300))
    statement: Mapped[str] = mapped_column(Text, default="")
    cause: Mapped[str] = mapped_column(Text, default="")
    risk_event: Mapped[str] = mapped_column(Text, default="")
    consequence: Mapped[str] = mapped_column(Text, default="")
    project_type_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_risk_types.id", ondelete="SET NULL"), nullable=True
    )
    treatment_strategy: Mapped[TreatmentStrategy | None] = mapped_column(str_enum(TreatmentStrategy, 20), nullable=True)
    acceptance_criteria: Mapped[str] = mapped_column(Text, default="")
    inherent_likelihood_level_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scoring_levels.id", ondelete="SET NULL"), nullable=True
    )
    inherent_consequence_level_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scoring_levels.id", ondelete="SET NULL"), nullable=True
    )
    inherent_detectability_level_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scoring_levels.id", ondelete="SET NULL"), nullable=True
    )
    residual_likelihood_level_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scoring_levels.id", ondelete="SET NULL"), nullable=True
    )
    residual_consequence_level_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scoring_levels.id", ondelete="SET NULL"), nullable=True
    )
    residual_detectability_level_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scoring_levels.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[RiskStatus] = mapped_column(str_enum(RiskStatus, 30), default=RiskStatus.IDENTIFIED)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    review_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    change_note: Mapped[str] = mapped_column(Text, default="")

    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    risk: Mapped[Risk] = relationship(back_populates="versions")


class RiskComment(UUIDPKMixin, TimestampMixin, Base):
    """A discussion-thread comment on a `Risk`.

    Attributes:
        risk_id: The commented-on risk.
        author_id: Who wrote it.
        body: Comment text.
        edited_at: Set only when the body changed after creation.
    """

    __tablename__ = "risk_comments"

    risk_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("risks.id", ondelete="CASCADE"))
    author_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RiskCommentFile(UUIDPKMixin, TimestampMixin, Base):
    """A file attached to a `RiskComment`."""

    __tablename__ = "risk_comment_files"

    comment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("risk_comments.id", ondelete="CASCADE"), index=True
    )
    file_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("file_assets.id", ondelete="CASCADE"))
    uploaded_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))


class RiskFile(UUIDPKMixin, Base):
    """Links a directly uploaded file (evidence) to a `Risk`. Its project is
    resolved by `service.resolve_risk_file_project_id`."""

    __tablename__ = "risk_files"
    __table_args__ = (UniqueConstraint("risk_id", "file_id"),)

    risk_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("risks.id", ondelete="CASCADE"))
    file_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("file_assets.id", ondelete="CASCADE"))
    linked_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RiskTreatmentAssessment(UUIDPKMixin, TimestampMixin, Base):
    """Whether one treatment link (a requirement, design or action that
    mitigates or treats the risk) is judged to actually reduce it, as opposed to
    merely being linked. A link with no row is implicitly `PROPOSED`.

    Attributes:
        link_id: The `ArtefactLink` assessed; deleting the link deletes this row.
        risk_id: The risk the link treats (denormalised from the link so the
            "is this risk effectively treated" query needs no link join).
        status: The verdict; see `TreatmentAssessmentStatus`.
        assessed_by / assessed_at: Who gave the verdict, and when.
        rationale: Why (required for an effective or ineffective verdict).
        reassessment_reason: Why the verdict was moved to `NEEDS_REASSESSMENT`
            (which linked artefact changed, and how); empty otherwise and cleared
            by the next verdict.
    """

    __tablename__ = "risk_treatment_assessments"

    link_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("artefact_links.id", ondelete="CASCADE"), unique=True
    )
    risk_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("risks.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[TreatmentAssessmentStatus] = mapped_column(
        str_enum(TreatmentAssessmentStatus, 30), default=TreatmentAssessmentStatus.PROPOSED
    )
    assessed_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    assessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    rationale: Mapped[str] = mapped_column(Text, default="")
    reassessment_reason: Mapped[str] = mapped_column(Text, default="")


class RiskReview(UUIDPKMixin, Base):
    """One periodic review of a risk. Immutable once recorded: a correction is a
    new review, so the history is a faithful record.

    Attributes:
        risk_id: The reviewed risk.
        risk_version_number: The risk version the review assessed.
        reviewed_by / reviewed_at: Who reviewed it, and when.
        outcome: What the review concluded.
        notes: The reviewer's findings (required).
        risk_status: The risk's lifecycle status at the time.
        inherent_rating_label / inherent_rating_score / residual_rating_label /
            residual_rating_score: The derived ratings at the time (label and
            0-1 normalised score; null when the risk was not scored). A snapshot,
            because ratings are derived and change when the matrix is edited.
        effective_treatment_count: How many treatment links were assessed
            effective at the time.
        scheduled_for: The `review_date` this review answered (null for an
            unscheduled review).
        next_review_date: The date the review set for the next one (null: none).
    """

    __tablename__ = "risk_reviews"

    risk_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("risks.id", ondelete="CASCADE"), index=True
    )
    risk_version_number: Mapped[int] = mapped_column(Integer)
    reviewed_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[RiskReviewOutcome] = mapped_column(str_enum(RiskReviewOutcome, 20))
    notes: Mapped[str] = mapped_column(Text)
    risk_status: Mapped[RiskStatus] = mapped_column(str_enum(RiskStatus, 30))
    inherent_rating_label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    inherent_rating_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    residual_rating_label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    residual_rating_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    effective_treatment_count: Mapped[int] = mapped_column(Integer, default=0)
    scheduled_for: Mapped[date | None] = mapped_column(Date, nullable=True)
    next_review_date: Mapped[date | None] = mapped_column(Date, nullable=True)
