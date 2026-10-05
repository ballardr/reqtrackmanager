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

Phase 2 (Future State, docs/plans/module-01-context-and-strategy-plan.md
Phase 2) adds `FutureState`/`FutureStateVersion`/`FutureStateComment`/
`FutureStateCommentFile`/`FutureStateFile` — an exact structural mirror of
the five classes above, for the standalone Future State artefact (Phase 0
Q1: a separate, first-class artefact, not fields folded onto `Strategy`).
`FutureStateVersion`'s own field set differs from `StrategyVersion`'s (no
`priority`/`time_horizon`; adds `target_date`, `outcomes`,
`success_measures`, `constraints`, `assumptions` per source overview §7),
but every structural decision — identity/version split, module-local
comments/files, the CHECK-constraint scope pattern — repeats identically,
so see the `Strategy`/`StrategyVersion` docstrings above rather than
duplicating the reasoning here.

Phase 3 (Pain Points, docs/plans/module-01-context-and-strategy-plan.md
Phase 3) adds six classes with a genuinely different shape from Strategy/
Future State's identity+version split, not a further structural mirror:

- `PainPointTypeDefinition` — org-scoped base type vocabulary (Phase 0 Q3's
  two-tier design), same shape as `RequirementLinkTypeDefinition`/
  `models.action_type.ActionTypeDefinition` (name, `sort_order`-equivalent
  `display_order`, org admin managed).
- `ProjectPainPointType` — project-scoped, either an override of one org
  type (`org_type_id` set, `name_override`/`display_order_override`
  nullable — `NULL` means "unchanged from the org default") or a fully
  project-local type (`org_type_id` NULL, in which case `name_override`
  is the type's only name and is therefore required — see the table's own
  CHECK constraint). A project's *effective* type list is every active org
  type (its own row's override, if any, taking precedence) plus every
  project-local row — resolved by `service.resolve_effective_pain_point_types`,
  never a stored/materialized view.
- `PainPoint` — the artefact itself. **No identity+version split** and
  **no `PainPointVersion` table** — Phase 3's own scope explicitly does not
  require one (see `enums.PainPointStatus`'s own docstring for the full
  reasoning), so every mutable field lives directly on this one row,
  updated in place (`service.update_pain_point`), with every change
  recorded only via `services.audit.log_event` (a plain audit trail, not a
  content snapshot). `pain_point_type_id` is a NOT NULL FK to
  `ProjectPainPointType.id`, never directly to `PainPointTypeDefinition`
  — every Pain Point's type is resolved through the project-scoped table
  so a single FK target always resolves the type regardless of whether it
  is org-backed-with-no-override, org-backed-with-an-override, or fully
  project-local (see `service.get_or_create_project_pain_point_type`).
  Pain Point is **project-scoped only** — no `scope`/`organization_id`
  discriminator the way Strategy/Future State have one (source overview
  §6 describes no organisation-level Pain Point; only its *type*
  vocabulary has an org-level component, via `PainPointTypeDefinition`
  above).
- `PainPointComment` / `PainPointCommentFile` / `PainPointFile` — this
  module's own module-local comment-thread and attachment tables, exact
  structural mirror of `StrategyComment`/`StrategyCommentFile`/
  `StrategyFile` (Phase 0 Q6: module-local tables, not a `ReviewTargetType`
  member — see this module's own `__init__.py` docstring for the full
  reasoning, repeated identically for Pain Point).

Phase 4 (Guiding Principles, docs/plans/module-01-context-and-strategy-
plan.md Phase 4) adds `GuidingPrinciple`/`GuidingPrincipleVersion`/
`GuidingPrincipleComment`/`GuidingPrincipleCommentFile`/
`GuidingPrincipleFile` — a structural mirror of `Strategy`/`StrategyVersion`
and friends (identity+version split, org/project `scope` discriminator,
module-local comments/files, Phase 0 Q4's full version-history requirement
applied here too), with a smaller field set (source overview §8.3: `name`,
`principle_statement`, `rationale`, `priority`, `owner_id` — no `type`
field, no `time_horizon`/`expected_outcomes`/`constraints`/`measures_of_
success`) and a **shorter** `status` lifecycle (`enums.GuidingPrincipleStatus`
— see that enum's own docstring for the full reconciliation of source
overview §8's scope text against its six actual members). `owner_id` lives
on `GuidingPrincipleVersion`, not the identity row — every mutable field on
this artefact is versioned, per Phase 0 Q4, unlike `PainPoint.owner_id`
(Phase 3, no version table at all).

Phase 5 (Open Questions, docs/plans/module-01-context-and-strategy-plan.md
Phase 5) adds `OpenQuestion`/`OpenQuestionComment`/`OpenQuestionCommentFile`/
`OpenQuestionFile` — back to Pain Point's shape (Phase 3), not Strategy/
Future State/Guiding Principle's identity+version split:

- **No `OpenQuestionVersion` table (Decided by: Agent).** Phase 0 Q4's full
  version-history requirement was scoped explicitly to Strategy, Future
  State, and (by its own follow-on) Guiding Principle; Open Question was
  never named there, the same absence-of-instruction reasoning
  `enums.PainPointStatus`'s own docstring already used to skip a version
  table for Pain Point. An Open Question is an operational, investigatory
  tracking record — closer in kind to a Pain Point moving through triage
  than to a Strategy/Guiding Principle's formally-reviewed governance
  content — so every mutable field lives directly on this one row, updated
  in place (`service.update_open_question`), with every change recorded
  only via `services.audit.log_event`.
- **Project-scoped only, no `scope`/`organization_id` discriminator
  (Decided by: Agent).** Source overview §9 never discusses an
  organisation-level Open Question at all (unlike Strategy/Future State/
  Guiding Principle, whose org/project duality Phase 0 Q2 resolved
  explicitly by name) — the strongest single signal is §9.5's own "Create
  Decision from Open Question" workflow: `Decision` (`app.modules.decisions.
  models.Decision`) is itself project-scoped only, with no organisation-
  level counterpart at all, so an org-scoped Open Question would have no
  valid resolution path into a Decision in the first place. This is
  reinforced by §9.1's own framing ("what's blocking this decision") and by
  Pain Point's precedent as this module's other project-scoped-only
  artefact. See `docs/decisions.md`'s dated entry for this phase for the
  full reasoning.
- `OpenQuestion.question`/`context`/`evidence` are `Text`, not `String`
  (source overview §9.2's own field names — no separate `title` the way
  Strategy/Future State needed one, mirroring `GuidingPrinciple.name`'s own
  precedent that the artefact's natural primary field doubles as its
  display title when the source text already gives one).
- `OpenQuestionComment`/`OpenQuestionCommentFile`/`OpenQuestionFile` — this
  module's own module-local comment-thread and attachment tables, exact
  structural mirror of `PainPointComment`/`PainPointCommentFile`/
  `PainPointFile` (Phase 0 Q6: module-local tables, not a `ReviewTargetType`
  member).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
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
    FutureStateScope,
    FutureStateStatus,
    GuidingPrinciplePriority,
    GuidingPrincipleScope,
    GuidingPrincipleStatus,
    OpenQuestionPriority,
    OpenQuestionStatus,
    PainPointPriority,
    PainPointStatus,
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


# --- Future State (Phase 2) -------------------------------------------------


class FutureState(UUIDPKMixin, TimestampMixin, Base):
    """A Future State's stable identity (organisation- or project-scoped) —
    exact structural mirror of `Strategy` (see module docstring).

    Attributes:
        scope: `FutureStateScope.ORGANIZATION` or `FutureStateScope.PROJECT`
            — which of `organization_id`/`project_id` is populated.
        organization_id: Set (and `project_id` null) for an org-scoped
            Future State.
        project_id: Set (and `organization_id` null) for a project-scoped
            Future State.
        creator_id: Who created this record.
        is_archived / archived_at / archived_by: Soft-delete, matching
            `Strategy`'s own convention.
    """

    __tablename__ = "future_states"
    __table_args__ = (
        CheckConstraint(
            "(scope = 'organization' AND organization_id IS NOT NULL AND project_id IS NULL) OR "
            "(scope = 'project' AND project_id IS NOT NULL AND organization_id IS NULL)",
            name="ck_future_states_scope_matches_owner",
        ),
    )

    scope: Mapped[FutureStateScope] = mapped_column(str_enum(FutureStateScope, 20))
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

    versions: Mapped[list[FutureStateVersion]] = relationship(
        back_populates="future_state", order_by="FutureStateVersion.version_number"
    )


class FutureStateVersion(UUIDPKMixin, Base):
    """A single point-in-time snapshot of a Future State's content — exact
    temporal shape of `StrategyVersion` (see module docstring), with the
    Phase 2 field set from source overview §7 in place of Strategy's own.

    Attributes:
        valid_from / valid_to: Effective time interval; `valid_to` is null
            for the current version.
        title: Short display title — not named in §7's own field list, added
            for list/display purposes, the same judgment call `Strategy`
            made for its own title (Decided by: Agent, following that
            precedent exactly).
        current_state: The present situation this Future State is measured
            from.
        desired_state: The end state being described.
        target_date: When the desired state is targeted to be reached — a
            plain `Date`, not a timestamp; there is no time-of-day
            component to a target date.
        outcomes: What reaching this Future State is expected to achieve.
        success_measures: How reaching it will be measured.
        constraints: Known constraints bounding this Future State.
        assumptions: Assumptions this Future State depends on holding true.
        status: Lifecycle state — see `enums.FutureStateStatus`. Lives
            here, not on `FutureState`, for the same reason `StrategyVersion.
            status` does (see module docstring).
        change_note: Free-text reason for the change.
        created_by / created_at: Who created this version snapshot, and
            when.
    """

    __tablename__ = "future_state_versions"
    __table_args__ = (
        UniqueConstraint("future_state_id", "version_number"),
        Index(
            "ix_future_state_versions_current", "future_state_id", unique=False,
            postgresql_where=sa_text("valid_to IS NULL"),
        ),
    )

    future_state_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("future_states.id", ondelete="CASCADE")
    )
    version_number: Mapped[int] = mapped_column(Integer)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    title: Mapped[str] = mapped_column(String(300))
    current_state: Mapped[str] = mapped_column(Text, default="")
    desired_state: Mapped[str] = mapped_column(Text, default="")
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    outcomes: Mapped[str] = mapped_column(Text, default="")
    success_measures: Mapped[str] = mapped_column(Text, default="")
    constraints: Mapped[str] = mapped_column(Text, default="")
    assumptions: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[FutureStateStatus] = mapped_column(str_enum(FutureStateStatus, 20), default=FutureStateStatus.DRAFT)
    change_note: Mapped[str] = mapped_column(Text, default="")

    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    future_state: Mapped[FutureState] = relationship(back_populates="versions")


class FutureStateComment(UUIDPKMixin, TimestampMixin, Base):
    """A discussion-thread comment on a `FutureState` — module-local
    analogue of `StrategyComment` (see module docstring).

    Attributes:
        future_state_id: The commented-on Future State.
        author_id: Who wrote the comment.
        body: Comment text.
        edited_at: Set only when the body is actually changed after
            creation; `None` for a never-edited comment.
    """

    __tablename__ = "future_state_comments"

    future_state_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("future_states.id", ondelete="CASCADE")
    )
    author_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class FutureStateCommentFile(UUIDPKMixin, TimestampMixin, Base):
    """A file attached to a `FutureStateComment` — module-local analogue of
    `StrategyCommentFile`."""

    __tablename__ = "future_state_comment_files"

    comment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("future_state_comments.id", ondelete="CASCADE"), index=True
    )
    file_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("file_assets.id", ondelete="CASCADE"))
    uploaded_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))


class FutureStateFile(UUIDPKMixin, Base):
    """Links a directly-uploaded file to a `FutureState` — module-local
    analogue of `StrategyFile`. A project-scoped Future State's files are
    ordinary, project-authorized uploads (resolved via `service.
    resolve_future_state_file_project_id`); an org-scoped Future State's
    files are uploaded as organisation shared resources
    (`FileAsset.is_org_resource=True`) instead, authorized by org
    membership alone — see `project_router.files`/`router.files`'s own
    upload endpoints for the split."""

    __tablename__ = "future_state_files"
    __table_args__ = (UniqueConstraint("future_state_id", "file_id"),)

    future_state_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("future_states.id", ondelete="CASCADE")
    )
    file_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("file_assets.id", ondelete="CASCADE"))
    linked_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


# --- Pain Points (Phase 3) ---------------------------------------------------


class PainPointTypeDefinition(UUIDPKMixin, TimestampMixin, Base):
    """Organisation-scoped base Pain Point type vocabulary (Phase 0 Q3) —
    same shape as `RequirementLinkTypeDefinition`/`ActionTypeDefinition`.
    Seeded with Market/User/Operator defaults for every organisation
    (source overview §6.2) at organisation-creation time, mirroring
    `services.definitions.seed_link_types`'s own seeding convention (see
    `service.seed_default_pain_point_types`).

    Attributes:
        organization_id: The owning organisation.
        name: Display name (e.g. "Market", "User", "Operator", or an
            org-added type).
        sort_order: Display/picker order among the organisation's types —
            named `sort_order`, not `display_order`, specifically so this
            table can reuse `services.ordering.move_ordered` verbatim
            (that helper reads `model.sort_order` by that exact attribute
            name, the same convention `ProjectStatusDefinition`/
            `RequirementLinkTypeDefinition`/`ActionTypeDefinition` already
            follow) rather than needing a bespoke reorder implementation.
        is_active: Soft-disable — an inactive org type is excluded from
            every project's effective type list (`service.
            resolve_effective_pain_point_types`) without deleting it
            outright (org history/audit references remain intact).
    """

    __tablename__ = "pain_point_type_definitions"
    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_pain_point_type_definitions_org_name"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(100))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class ProjectPainPointType(UUIDPKMixin, TimestampMixin, Base):
    """A project's own view onto the Pain Point type vocabulary (Phase 0
    Q3) — either a local override of one org type, or a fully project-local
    type not backed by any org row.

    Attributes:
        project_id: The owning project.
        org_type_id: The org type this row overrides, or `NULL` for a
            fully project-local type. `ON DELETE SET NULL` — if the
            underlying org type is ever deleted, an *unreferenced* override
            row (checked by `service.delete_org_pain_point_type` before
            allowing the delete) would never reach this state; kept as a
            defensive default rather than the stricter `RESTRICT` a fresh
            Postgres FK already applies with no explicit `ondelete`, since
            application logic — not the database — is this design's
            primary enforcement point (see that function's own docstring).
        name_override: Overrides the org type's `name` for this project
            alone when `org_type_id` is set; the type's own (only) name
            when `org_type_id` is `NULL` (enforced NOT NULL in that case
            by this table's own CHECK constraint — a project-local type has
            no org row to fall back on for a name).
        display_order_override: Overrides the org type's `sort_order`
            for this project alone when set and `org_type_id` is not
            `NULL`; the type's own display order when `org_type_id` is
            `NULL` (falls back to `0` if left `NULL` in that case too —
            see `service.resolve_effective_pain_point_types`).
        is_enabled: Whether this type is offered when creating a Pain
            Point in this project. Defaults `True` — an org type is
            included in a project's effective list until a project admin
            explicitly disables it (§6.2's "Disable types").
    """

    __tablename__ = "project_pain_point_types"
    __table_args__ = (
        UniqueConstraint("project_id", "org_type_id", name="uq_project_pain_point_types_project_org_type"),
        CheckConstraint(
            "org_type_id IS NOT NULL OR name_override IS NOT NULL",
            name="ck_project_pain_point_types_local_has_name",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"))
    org_type_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pain_point_type_definitions.id", ondelete="SET NULL"), nullable=True
    )
    name_override: Mapped[str | None] = mapped_column(String(100), nullable=True)
    display_order_override: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class PainPoint(UUIDPKMixin, TimestampMixin, Base):
    """A Pain Point (source overview §6) — project-scoped only, no
    identity+version split (see this module's own docstring for why),
    every mutable field on this one row.

    Attributes:
        project_id: The owning project.
        pain_point_type_id: FK to `ProjectPainPointType.id` — never
            directly to `PainPointTypeDefinition` (see module docstring).
        title / description: Core identifying content.
        source: Free-text provenance (e.g. "Support ticket #481",
            "Customer interview", "Ops incident report") — distinct from
            `pain_point_type_id`'s fixed Market/User/Operator-style
            vocabulary.
        impact: Free-text description of the problem's effect.
        evidence: Free-text supporting evidence (in addition to any
            `PainPointFile`/`PainPointCommentFile` attachments).
        priority: `enums.PainPointPriority`.
        status: `enums.PainPointStatus` — the branching lifecycle.
        owner_id: The user responsible for resolving this Pain Point,
            assigned by a `pain_point_manager` during/after triage
            (§6.5) — `NULL` until assigned.
        date_identified: When the problem was first identified — defaults
            to the creation date if not supplied (`service.create_pain_point`).
        creator_id: Who submitted this Pain Point (§6.5's broad-creation
            model — any project member).
        is_archived / archived_at / archived_by: Soft-delete, matching
            `Strategy`/`FutureState`'s own convention.
    """

    __tablename__ = "pain_points"

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"))
    pain_point_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_pain_point_types.id")
    )

    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(Text, default="")
    impact: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[str] = mapped_column(Text, default="")
    priority: Mapped[PainPointPriority] = mapped_column(
        str_enum(PainPointPriority, 20), default=PainPointPriority.MEDIUM
    )
    status: Mapped[PainPointStatus] = mapped_column(str_enum(PainPointStatus, 20), default=PainPointStatus.SUBMITTED)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    date_identified: Mapped[date] = mapped_column(Date)
    creator_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)


class PainPointComment(UUIDPKMixin, TimestampMixin, Base):
    """A discussion-thread comment on a `PainPoint` — module-local
    analogue of `StrategyComment` (see module docstring).

    Attributes:
        pain_point_id: The commented-on Pain Point.
        author_id: Who wrote the comment.
        body: Comment text.
        edited_at: Set only when the body is actually changed after
            creation; `None` for a never-edited comment.
    """

    __tablename__ = "pain_point_comments"

    pain_point_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pain_points.id", ondelete="CASCADE")
    )
    author_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PainPointCommentFile(UUIDPKMixin, TimestampMixin, Base):
    """A file attached to a `PainPointComment` — module-local analogue of
    `StrategyCommentFile`."""

    __tablename__ = "pain_point_comment_files"

    comment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pain_point_comments.id", ondelete="CASCADE"), index=True
    )
    file_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("file_assets.id", ondelete="CASCADE"))
    uploaded_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))


class PainPointFile(UUIDPKMixin, Base):
    """Links a directly-uploaded file to a `PainPoint` — module-local
    analogue of `StrategyFile`. Pain Point is project-scoped only, so
    (unlike Strategy/Future State) there is no org-resource upload branch —
    every `PainPointFile` upload is an ordinary project-authorized upload,
    resolved via `service.resolve_pain_point_file_project_id`."""

    __tablename__ = "pain_point_files"
    __table_args__ = (UniqueConstraint("pain_point_id", "file_id"),)

    pain_point_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pain_points.id", ondelete="CASCADE")
    )
    file_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("file_assets.id", ondelete="CASCADE"))
    linked_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


# --- Guiding Principles (Phase 4) --------------------------------------------


class GuidingPrinciple(UUIDPKMixin, TimestampMixin, Base):
    """A Guiding Principle's stable identity (organisation- or project-
    scoped) — exact structural mirror of `Strategy`/`FutureState` (see
    module docstring).

    Attributes:
        scope: `GuidingPrincipleScope.ORGANIZATION` or `.PROJECT` — which of
            `organization_id`/`project_id` is populated.
        organization_id: Set (and `project_id` null) for an org-scoped
            Guiding Principle.
        project_id: Set (and `organization_id` null) for a project-scoped
            Guiding Principle.
        creator_id: Who created this record.
        is_archived / archived_at / archived_by: Soft-delete, matching
            `Strategy`/`FutureState`'s own convention.
    """

    __tablename__ = "guiding_principles"
    __table_args__ = (
        CheckConstraint(
            "(scope = 'organization' AND organization_id IS NOT NULL AND project_id IS NULL) OR "
            "(scope = 'project' AND project_id IS NOT NULL AND organization_id IS NULL)",
            name="ck_guiding_principles_scope_matches_owner",
        ),
    )

    scope: Mapped[GuidingPrincipleScope] = mapped_column(str_enum(GuidingPrincipleScope, 20))
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

    versions: Mapped[list[GuidingPrincipleVersion]] = relationship(
        back_populates="guiding_principle", order_by="GuidingPrincipleVersion.version_number"
    )


class GuidingPrincipleVersion(UUIDPKMixin, Base):
    """A single point-in-time snapshot of a Guiding Principle's content —
    exact temporal shape of `StrategyVersion`/`FutureStateVersion` (see
    module docstring), for the Phase 4 field set (source overview §8.3).

    Attributes:
        valid_from / valid_to: Effective time interval; `valid_to` is null
            for the current version.
        name: Short display name (source overview §8.3's own field, not an
            added-by-convention `title` the way Strategy/Future State
            needed one).
        principle_statement: The principle's own statement text — this
            artefact's core content.
        rationale: Why this principle exists / matters.
        priority: `enums.GuidingPrinciplePriority`.
        status: Lifecycle state — see `enums.GuidingPrincipleStatus`. Lives
            here, not on `GuidingPrinciple`, for the same reason `Strategy
            Version.status` does (see module docstring).
        owner_id: The user responsible for this principle — `NULL` if
            unassigned. Versioned along with every other content field
            (Phase 0 Q4's full version-history model applies to the whole
            row here, unlike `PainPoint.owner_id`, which has no version
            table to live on).
        change_note: Free-text reason for the change.
        created_by / created_at: Who created this version snapshot, and
            when.
    """

    __tablename__ = "guiding_principle_versions"
    __table_args__ = (
        UniqueConstraint("guiding_principle_id", "version_number"),
        Index(
            "ix_guiding_principle_versions_current", "guiding_principle_id", unique=False,
            postgresql_where=sa_text("valid_to IS NULL"),
        ),
    )

    guiding_principle_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("guiding_principles.id", ondelete="CASCADE")
    )
    version_number: Mapped[int] = mapped_column(Integer)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    name: Mapped[str] = mapped_column(String(300))
    principle_statement: Mapped[str] = mapped_column(Text)
    rationale: Mapped[str] = mapped_column(Text, default="")
    priority: Mapped[GuidingPrinciplePriority] = mapped_column(
        str_enum(GuidingPrinciplePriority, 20), default=GuidingPrinciplePriority.MEDIUM
    )
    status: Mapped[GuidingPrincipleStatus] = mapped_column(
        str_enum(GuidingPrincipleStatus, 20), default=GuidingPrincipleStatus.DRAFT
    )
    owner_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    change_note: Mapped[str] = mapped_column(Text, default="")

    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    guiding_principle: Mapped[GuidingPrinciple] = relationship(back_populates="versions")


class GuidingPrincipleComment(UUIDPKMixin, TimestampMixin, Base):
    """A discussion-thread comment on a `GuidingPrinciple` — module-local
    analogue of `StrategyComment` (see module docstring).

    Attributes:
        guiding_principle_id: The commented-on Guiding Principle.
        author_id: Who wrote the comment.
        body: Comment text.
        edited_at: Set only when the body is actually changed after
            creation; `None` for a never-edited comment.
    """

    __tablename__ = "guiding_principle_comments"

    guiding_principle_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("guiding_principles.id", ondelete="CASCADE")
    )
    author_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class GuidingPrincipleCommentFile(UUIDPKMixin, TimestampMixin, Base):
    """A file attached to a `GuidingPrincipleComment` — module-local
    analogue of `StrategyCommentFile`."""

    __tablename__ = "guiding_principle_comment_files"

    comment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("guiding_principle_comments.id", ondelete="CASCADE"), index=True
    )
    file_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("file_assets.id", ondelete="CASCADE"))
    uploaded_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))


class GuidingPrincipleFile(UUIDPKMixin, Base):
    """Links a directly-uploaded file to a `GuidingPrinciple` — module-local
    analogue of `StrategyFile`. A project-scoped Guiding Principle's files
    are ordinary, project-authorized uploads (resolved via `service.
    resolve_guiding_principle_file_project_id`); an org-scoped Guiding
    Principle's files are uploaded as organisation shared resources
    (`FileAsset.is_org_resource=True`) instead, authorized by org
    membership alone — see `project_router.files`/`router.files`'s own
    upload endpoints for the split."""

    __tablename__ = "guiding_principle_files"
    __table_args__ = (UniqueConstraint("guiding_principle_id", "file_id"),)

    guiding_principle_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("guiding_principles.id", ondelete="CASCADE")
    )
    file_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("file_assets.id", ondelete="CASCADE"))
    linked_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


# --- Open Questions (Phase 5) -------------------------------------------------


class OpenQuestion(UUIDPKMixin, TimestampMixin, Base):
    """An Open Question (source overview §9) — project-scoped only, no
    identity+version split (see this module's own docstring for why), every
    mutable field on this one row.

    Attributes:
        project_id: The owning project.
        question: The question itself — this artefact's core content and
            natural display title (source overview §9.2's own field name;
            no separate `title` field, mirroring `GuidingPrinciple.name`'s
            precedent).
        context: Free-text background — why this question matters / what
            prompted it.
        evidence: Free-text supporting evidence (in addition to any
            `OpenQuestionFile`/`OpenQuestionCommentFile` attachments),
            mirroring `PainPoint.evidence`.
        priority: `enums.OpenQuestionPriority`.
        status: `enums.OpenQuestionStatus` — the branching lifecycle.
        owner_id: The user responsible for driving this question to
            resolution, assigned by an `open_question_owner` (§9.4's
            "Question Owner / Project Manager": Assign) — `NULL` until
            assigned.
        due_date: The due/review date (§9.2) — `NULL` if none has been set.
        creator_id: Who raised this Open Question (§9.4's broad-creation
            model — any project member).
        is_archived / archived_at / archived_by: Soft-delete, matching
            `PainPoint`/`Strategy`'s own convention.
    """

    __tablename__ = "open_questions"

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"))

    question: Mapped[str] = mapped_column(Text)
    context: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[str] = mapped_column(Text, default="")
    priority: Mapped[OpenQuestionPriority] = mapped_column(
        str_enum(OpenQuestionPriority, 20), default=OpenQuestionPriority.MEDIUM
    )
    status: Mapped[OpenQuestionStatus] = mapped_column(str_enum(OpenQuestionStatus, 20), default=OpenQuestionStatus.OPEN)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    creator_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)


class OpenQuestionComment(UUIDPKMixin, TimestampMixin, Base):
    """A discussion-thread comment on an `OpenQuestion` — module-local
    analogue of `PainPointComment` (see module docstring). Also this
    artefact's mechanism for §9.4's "Suggest resolution" (any project
    member) — a plain comment, not a separate field.

    Attributes:
        open_question_id: The commented-on Open Question.
        author_id: Who wrote the comment.
        body: Comment text.
        edited_at: Set only when the body is actually changed after
            creation; `None` for a never-edited comment.
    """

    __tablename__ = "open_question_comments"

    open_question_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("open_questions.id", ondelete="CASCADE")
    )
    author_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OpenQuestionCommentFile(UUIDPKMixin, TimestampMixin, Base):
    """A file attached to an `OpenQuestionComment` — module-local analogue
    of `PainPointCommentFile`."""

    __tablename__ = "open_question_comment_files"

    comment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("open_question_comments.id", ondelete="CASCADE"), index=True
    )
    file_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("file_assets.id", ondelete="CASCADE"))
    uploaded_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))


class OpenQuestionFile(UUIDPKMixin, Base):
    """Links a directly-uploaded file to an `OpenQuestion` — module-local
    analogue of `PainPointFile`. Open Question is project-scoped only, so
    (like Pain Point, unlike Strategy/Future State/Guiding Principle) there
    is no org-resource upload branch — every `OpenQuestionFile` upload is an
    ordinary project-authorized upload, resolved via `service.resolve_open_
    question_file_project_id`. This is §9.4's "Add evidence" capability,
    deliberately open to any project member (see `project_router.upload_
    project_open_question_file`'s own docstring)."""

    __tablename__ = "open_question_files"
    __table_args__ = (UniqueConstraint("open_question_id", "file_id"),)

    open_question_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("open_questions.id", ondelete="CASCADE")
    )
    file_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("file_assets.id", ondelete="CASCADE"))
    linked_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
