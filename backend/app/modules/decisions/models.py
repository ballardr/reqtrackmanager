"""
Module: modules.decisions.models

Decision Management's data model: `DecisionTypeDefinition` (project-scoped,
seeded), `DecisionTemplateDefinition` (org-scoped creation-time guidance
preset), `Decision` (`unique_code` uses the registered `"decision"` type) and
the module-local `DecisionComment`/`DecisionCommentFile`/`DecisionFile`, which
only ever target a `Decision`.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, UUIDPKMixin, str_enum
from app.models.principal import principal_check_constraint, principal_id_column, principal_type_column
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
    """An org-managed Decision Template: per-field guidance text applied to a
    new Decision's free-text fields at creation time (not referenced afterwards).

    Attributes:
        organization_id: The owning organisation.
        name: Display name, unique within the organisation.
        description: One-line explanation shown in the template picker.
        context_prompt / options_considered_prompt / chosen_option_prompt /
            rationale_prompt / consequences_prompt / assumptions_prompt /
            constraints_prompt: Guidance text for the matching `Decision`
            field, applied verbatim when the template is picked. Any may be
            `NULL` where the format has no such section.
        sort_order: Picker order among the organisation's templates.
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
    """A formally recorded decision (§13/10.3).

    Attributes:
        project_id: The owning project.
        unique_code: Project-scoped identifier (e.g. `"DEC-003"`), from
            `services.sequences.generate_unique_code`.
        title: Short display title.
        decision_type_id: FK to `DecisionTypeDefinition`.
        status: Lifecycle state (`DecisionStatus`).
        decision_date: Date the decision was made, which may precede approval.
        decision_maker_type / decision_maker_id: Optional principal (user,
            organisation group or project group) who made or is expected to
            make the decision; distinct from the `decision_approver` role,
            which controls who may approve.
        owner_type / owner_id: Mandatory principal that maintains the record.
            The id has no foreign key (see `models.principal`);
            `services.principals.validate_principal` checks it on write and
            `module.py`'s `principal_references` guard group deletion.
        decision_statement / context / options_considered / chosen_option /
            rationale / consequences / assumptions / constraints: Markdown
            free-text fields; rationale and consequences are separate (§13/10.3).
        document: The decision written out in full, in Markdown, beside the
            structured fields; content-locked with them once approved or superseded.
        creator_id: Who created this record.
        is_archived / archived_at / archived_by: Soft-delete.
    """

    __tablename__ = "decisions"
    __table_args__ = (
        UniqueConstraint("project_id", "unique_code"),
        principal_check_constraint("owner"),
        principal_check_constraint("decision_maker", nullable=True),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"))
    unique_code: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(300))
    decision_statement: Mapped[str] = mapped_column(Text)
    decision_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("decision_type_definitions.id")
    )
    status: Mapped[DecisionStatus] = mapped_column(str_enum(DecisionStatus, 20), default=DecisionStatus.DRAFT)
    decision_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    decision_maker_type: Mapped[str | None] = principal_type_column(nullable=True)
    decision_maker_id: Mapped[uuid.UUID | None] = principal_id_column(nullable=True)
    owner_type: Mapped[str] = principal_type_column()
    owner_id: Mapped[uuid.UUID] = principal_id_column()
    context: Mapped[str | None] = mapped_column(Text, nullable=True)
    options_considered: Mapped[str | None] = mapped_column(Text, nullable=True)
    chosen_option: Mapped[str | None] = mapped_column(Text, nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    consequences: Mapped[str | None] = mapped_column(Text, nullable=True)
    assumptions: Mapped[str | None] = mapped_column(Text, nullable=True)
    constraints: Mapped[str | None] = mapped_column(Text, nullable=True)
    document: Mapped[str | None] = mapped_column(Text, nullable=True)
    creator_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)


class DecisionComment(UUIDPKMixin, TimestampMixin, Base):
    """A discussion-thread comment on a `Decision`, with a direct `decision_id`
    FK instead of a polymorphic target.

    Attributes:
        decision_id: The commented-on Decision.
        author_id: Who wrote the comment.
        body: Comment text.
        edited_at: Set only when the body changes after creation; `None` for a
            never-edited comment.
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
