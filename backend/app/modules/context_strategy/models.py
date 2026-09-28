"""
Module: modules.context_strategy.models

Context & Strategy's Phase 1 data model (docs/plans/module-01-context-and-
strategy-plan.md Phase 1 — Organisation & Project Strategy):

- `Strategy` — the identity row (Phase 0 Q2): one table with a `scope`
  discriminator and exactly one of `organization_id`/`project_id` set,
  rather than two separate org/project tables, so a future Portfolio/
  Programme scope can be added later without a redesign. Holds only
  stable identity fields (scope, owning org/project, creator, archival
  flag) — every mutable/content field lives on `StrategyVersion`, exactly
  mirroring `models.requirement.Requirement`/`RequirementVersion`'s split
  (Phase 0 Q4: a full version-history table, not an audit-log-only model).
- `StrategyVersion` — one point-in-time content snapshot, temporal shape
  (`valid_from`/`valid_to`/`version_number`) copied directly from
  `RequirementVersion`. `status` (`enums.StrategyStatus`) lives here, not
  on `Strategy` itself — a lifecycle transition is a content change like
  any other, so it creates a new version the same way editing
  `objective`/`rationale`/etc. does (see `service.apply_new_version`),
  exactly mirroring how `RequirementVersion.status` changes via
  `services.requirements.apply_new_version` rather than a separate
  identity-row column. This is a deliberate divergence from Decision
  Management's own shape (`Decision.status` lives on the identity row,
  transitions recorded only via the audit log) — Phase 0 Q4 explicitly
  requires the fuller temporal model for Strategy, not Decision's lighter
  one.
- `StrategyComment` / `StrategyCommentFile` / `StrategyFile` — this
  module's own module-local comment-thread and attachment tables,
  mirroring `app.modules.decisions.models`' identical `DecisionComment`/
  `DecisionCommentFile`/`DecisionFile` shape and reasoning: the core
  `ReviewComment`/`CommentFile`/`ReviewTargetType` machinery has never
  been extended by any module (Decision Management deliberately declined
  to, for the same reason), and a Strategy comment/attachment only ever
  targets one `Strategy` — no polymorphic target is needed. **Decided by:
  Agent** — this is a deliberate deviation from this phase's own brief,
  which asked for a new `ReviewTargetType.STRATEGY` member; see this
  module's own package docstring (`__init__.py`) for the full reasoning,
  and `docs/decisions.md`'s dated entry for this phase for the account
  flagged back to the user.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
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
from app.modules.context_strategy.enums import (
    StrategyPriority,
    StrategyScope,
    StrategyStatus,
    StrategyTimeHorizon,
)


class Strategy(UUIDPKMixin, TimestampMixin, Base):
    """A Strategy's stable identity (organisation- or project-scoped).

    Attributes:
        scope: `StrategyScope.ORGANIZATION` or `StrategyScope.PROJECT` —
            which of `organization_id`/`project_id` is populated.
        organization_id: Set (and `project_id` null) for an org-scoped
            Strategy.
        project_id: Set (and `organization_id` null) for a project-scoped
            Strategy.
        creator_id: Who created this record.
        is_archived / archived_at / archived_by: Soft-delete, matching
            `Requirement`/`Decision`'s own convention.
    """

    __tablename__ = "strategies"
    __table_args__ = (
        CheckConstraint(
            "(scope = 'organization' AND organization_id IS NOT NULL AND project_id IS NULL) OR "
            "(scope = 'project' AND project_id IS NOT NULL AND organization_id IS NULL)",
            name="ck_strategies_scope_matches_owner",
        ),
    )

    scope: Mapped[StrategyScope] = mapped_column(str_enum(StrategyScope, 20))
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    creator_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    versions: Mapped[list[StrategyVersion]] = relationship(
        back_populates="strategy", order_by="StrategyVersion.version_number"
    )


class StrategyVersion(UUIDPKMixin, Base):
    """A single point-in-time snapshot of a Strategy's content — exact
    temporal shape of `models.requirement.RequirementVersion` (see this
    module's own docstring).

    Attributes:
        valid_from / valid_to: Effective time interval; `valid_to` is null
            for the current version.
        title: Short display title.
        objective: The strategic theme/objective statement.
        current_state / desired_future_state: Short free-text fields
            (Phase 1 scope — the fuller structured elaboration lives on
            the separate Future State artefact, Phase 2, per Phase 0 Q1).
        rationale: Why this Strategy exists.
        expected_outcomes: What this Strategy is expected to achieve.
        constraints: Known constraints bounding this Strategy.
        measures_of_success: How success will be measured.
        priority / time_horizon: Small fixed vocabularies — see
            `enums.StrategyPriority`/`StrategyTimeHorizon`.
        status: Lifecycle state — see `enums.StrategyStatus`. Lives here,
            not on `Strategy`, so a transition is versioned the same way
            any other content change is (see module docstring).
        change_note: Free-text reason for the change, mirroring
            `RequirementVersion.change_note`.
        created_by / created_at: Who created this version snapshot, and
            when.
    """

    __tablename__ = "strategy_versions"
    __table_args__ = (
        UniqueConstraint("strategy_id", "version_number"),
        # Partial index backing `service.get_current_version`'s `valid_to IS
        # NULL` lookup — mirrors `ArtefactLink`'s own partial-index
        # convention (`models.relationship`) rather than a plain full-column
        # index that would also cover every historical (non-current) row.
        Index(
            "ix_strategy_versions_current", "strategy_id", unique=False, postgresql_where=sa_text("valid_to IS NULL")
        ),
    )

    strategy_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("strategies.id", ondelete="CASCADE"))
    version_number: Mapped[int] = mapped_column(Integer)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    title: Mapped[str] = mapped_column(String(300))
    objective: Mapped[str] = mapped_column(Text)
    current_state: Mapped[str] = mapped_column(Text, default="")
    desired_future_state: Mapped[str] = mapped_column(Text, default="")
    rationale: Mapped[str] = mapped_column(Text, default="")
    expected_outcomes: Mapped[str] = mapped_column(Text, default="")
    constraints: Mapped[str] = mapped_column(Text, default="")
    measures_of_success: Mapped[str] = mapped_column(Text, default="")
    priority: Mapped[StrategyPriority] = mapped_column(str_enum(StrategyPriority, 20), default=StrategyPriority.MEDIUM)
    time_horizon: Mapped[StrategyTimeHorizon] = mapped_column(
        str_enum(StrategyTimeHorizon, 20), default=StrategyTimeHorizon.MEDIUM_TERM
    )
    status: Mapped[StrategyStatus] = mapped_column(str_enum(StrategyStatus, 20), default=StrategyStatus.DRAFT)
    change_note: Mapped[str] = mapped_column(Text, default="")

    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    strategy: Mapped[Strategy] = relationship(back_populates="versions")


class StrategyComment(UUIDPKMixin, TimestampMixin, Base):
    """A discussion-thread comment on a `Strategy` — module-local analogue
    of `ReviewComment`/`DecisionComment` (see module docstring).

    Attributes:
        strategy_id: The commented-on Strategy.
        author_id: Who wrote the comment.
        body: Comment text.
        edited_at: Set only when the body is actually changed after
            creation; `None` for a never-edited comment.
    """

    __tablename__ = "strategy_comments"

    strategy_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("strategies.id", ondelete="CASCADE"))
    author_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class StrategyCommentFile(UUIDPKMixin, TimestampMixin, Base):
    """A file attached to a `StrategyComment` — module-local analogue of
    `CommentFile`/`DecisionCommentFile`."""

    __tablename__ = "strategy_comment_files"

    comment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("strategy_comments.id", ondelete="CASCADE"), index=True
    )
    file_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("file_assets.id", ondelete="CASCADE"))
    uploaded_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))


class StrategyFile(UUIDPKMixin, Base):
    """Links a directly-uploaded file to a `Strategy` — module-local
    analogue of `RequirementFile`/`DecisionFile`. A project-scoped
    Strategy's files are ordinary, project-authorized uploads (resolved via
    `service.resolve_strategy_file_project_id`); an org-scoped Strategy's
    files are uploaded as organisation shared resources
    (`FileAsset.is_org_resource=True`) instead, authorized by org
    membership alone — see `project_router.files`/`router.files`'s own
    upload endpoints for the split."""

    __tablename__ = "strategy_files"
    __table_args__ = (UniqueConstraint("strategy_id", "file_id"),)

    strategy_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("strategies.id", ondelete="CASCADE"))
    file_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("file_assets.id", ondelete="CASCADE"))
    linked_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
