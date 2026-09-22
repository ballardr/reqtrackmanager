"""
Module: modules.decisions.models

Decision Management's data model (docs/plans/module-04-decision-
management-plan.md Phase 1):

- `DecisionTypeDefinition` — project-scoped, extensible vocabulary (e.g.
  Architecture, Design, Engineering, Strategy, Operational), exact shape of
  `app.models.action_type.ActionTypeDefinition` (id, project_id, name,
  sort_order — no `is_enabled` flag; see this module's own docstring in
  docs/plans/module-04-decision-management-plan.md's Phase 0 addendum for
  why). Seeded per-project by `service.seed_decision_types`.
- `DecisionTemplateDefinition` — org-scoped, per-field guidance-text
  preset (e.g. the seeded Nygard/MADR/Y-Statement ADR packs, or an org's
  own custom ones). Deliberately *not* associated with a `DecisionTypeDefinition`
  (org-scoped templates vs. project-scoped types would make a cross-scope
  FK ambiguous) and *not* referenced by `Decision` after creation — a
  template is a creation-time convenience that pre-fills fields, not a
  persistent relationship, so deleting one is always a plain delete with
  no reassignment machinery.
- `Decision` — the record itself (source overview §13/10.3's field list).
  `unique_code` uses Module 0's generic `services.sequences.
  generate_unique_code` with this module's own `"decision"` artefact-type
  string (`ModuleDefinition.artefact_types`, `module.py`), not a
  hand-edited core enum member — see `app.models.sequence.
  ProjectSequenceCounter`'s own docstring for why that mechanism is
  module-registrable rather than requiring one.
- `DecisionComment` / `DecisionCommentFile` / `DecisionFile` — this
  module's own comment-thread and attachment tables. Deliberately
  module-local rather than reusing the core `ReviewComment`/`CommentFile`/
  `ReviewTargetType` machinery: that machinery has never been extended by
  any module before (Compliance has its own separate mechanism), and a
  Decision comment/attachment only ever targets a `Decision` — no
  polymorphic `target_type` is needed, so the module-local tables are
  actually simpler than reusing the polymorphic core ones would be, not
  just more boundary-correct.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, UUIDPKMixin, str_enum
from app.modules.decisions.enums import DecisionStatus


class DecisionTypeDefinition(UUIDPKMixin, TimestampMixin, Base):
    """A project-defined decision type (e.g. "Architecture", "Strategy").
    Exact shape of `ActionTypeDefinition` — see module docstring.

    Attributes:
        project_id: The owning project.
        name: Display name, unique within the project.
        sort_order: Display/picker order among the project's decision types.
    """

    __tablename__ = "decision_type_definitions"
    __table_args__ = (UniqueConstraint("project_id", "name"),)

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(100))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class DecisionTemplateDefinition(UUIDPKMixin, TimestampMixin, Base):
    """An org-managed Decision Template — per-field guidance/placeholder
    text applied to a new Decision's free-text fields at creation time
    (Phase 5), not a persistent relationship (see module docstring).

    Attributes:
        organization_id: The owning organisation.
        name: Display name, unique within the organisation (e.g. "MADR
            (Markdown Architectural Decision Records)", or a custom name).
        description: One-line explanation shown in the template picker.
        context_prompt / options_considered_prompt / chosen_option_prompt /
            rationale_prompt / consequences_prompt / assumptions_prompt /
            constraints_prompt: Placeholder/example guidance text for the
            matching `Decision` field, applied verbatim (then edited by the
            user) when this template is picked at creation time. Any may be
            `NULL` — a format like Nygard's original ADR template has no
            "Options Considered" or "Rationale" section, and its own seeded
            prompt text says so explicitly (see `service.
            DECISION_TEMPLATE_PACKS`) rather than the field being silently
            blank with no explanation.
        sort_order: Display/picker order among the organisation's templates.
    """

    __tablename__ = "decision_template_definitions"
    __table_args__ = (UniqueConstraint("organization_id", "name"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    context_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    options_considered_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    chosen_option_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    rationale_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    consequences_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    assumptions_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    constraints_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class Decision(UUIDPKMixin, TimestampMixin, Base):
    """A formally recorded decision (source overview §13/10.3).

    Attributes:
        project_id: The owning project.
        unique_code: Project-scoped identifier (e.g. `"DEC-003"`), from
            `services.sequences.generate_unique_code`.
        title: Short display title.
        decision_statement: The decision itself, in one sentence/paragraph.
        decision_type_id: FK to `DecisionTypeDefinition`.
        status: Lifecycle state — see `DecisionStatus`.
        decision_date: Date the decision was actually made, which may
            precede formal approval (e.g. a decision made in a meeting,
            formally approved days later).
        decision_maker_id: Nullable FK to `users` — who actually made (or
            is expected to make) this specific decision. Distinct from the
            `decision_approver` module role (`module.py`), which controls
            *who may* approve any decision in the project — this column
            records who *did* (or will), the placeholder-role resolution
            from Phase 0 addendum Q2/2a doesn't remove the value of
            recording an actual named decision-maker per Decision.
        owner_id: FK to `users` — maintains the record; distinct from
            `decision_maker_id`.
        context / options_considered / chosen_option / rationale /
            consequences / assumptions / constraints: Free-text fields
            (source overview §13/10.3; rationale and consequences are
            explicitly separate fields per that section, not folded into
            a single description).
        creator_id: Who created this record.
        is_archived / archived_at / archived_by: Soft-delete, matching
            `Requirement`/`RequirementAction`'s own convention.
    """

    __tablename__ = "decisions"
    __table_args__ = (UniqueConstraint("project_id", "unique_code"),)

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"))
    unique_code: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(300))
    decision_statement: Mapped[str] = mapped_column(Text)
    decision_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("decision_type_definitions.id")
    )
    status: Mapped[DecisionStatus] = mapped_column(str_enum(DecisionStatus, 20), default=DecisionStatus.DRAFT)
    decision_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    decision_maker_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    context: Mapped[str | None] = mapped_column(Text, nullable=True)
    options_considered: Mapped[str | None] = mapped_column(Text, nullable=True)
    chosen_option: Mapped[str | None] = mapped_column(Text, nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    consequences: Mapped[str | None] = mapped_column(Text, nullable=True)
    assumptions: Mapped[str | None] = mapped_column(Text, nullable=True)
    constraints: Mapped[str | None] = mapped_column(Text, nullable=True)
    creator_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)


class DecisionComment(UUIDPKMixin, TimestampMixin, Base):
    """A discussion-thread comment on a `Decision` — module-local analogue
    of `ReviewComment`, with a direct `decision_id` FK instead of a
    polymorphic `target_type`/`target_id` pair (see module docstring for
    why).

    Attributes:
        decision_id: The commented-on Decision.
        author_id: Who wrote the comment.
        body: Comment text.
        edited_at: Set only when the body is actually changed after
            creation; `None` for a never-edited comment — mirrors
            `ReviewComment.edited_at`'s own reasoning (avoids the two
            independent `TimestampMixin` defaults intermittently reading a
            fresh comment as "edited").
    """

    __tablename__ = "decision_comments"

    decision_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("decisions.id", ondelete="CASCADE"))
    author_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DecisionCommentFile(UUIDPKMixin, TimestampMixin, Base):
    """A file attached to a `DecisionComment` — module-local analogue of
    `CommentFile`."""

    __tablename__ = "decision_comment_files"

    comment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("decision_comments.id", ondelete="CASCADE"), index=True
    )
    file_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("file_assets.id", ondelete="CASCADE"))
    uploaded_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))


class DecisionFile(UUIDPKMixin, Base):
    """Links a directly-uploaded file to a `Decision` — module-local
    analogue of `RequirementFile` (direct attachment, as opposed to a
    `DecisionCommentFile` attached to one discussion comment)."""

    __tablename__ = "decision_files"
    __table_args__ = (UniqueConstraint("decision_id", "file_id"),)

    decision_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("decisions.id", ondelete="CASCADE"))
    file_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("file_assets.id", ondelete="CASCADE"))
    linked_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
