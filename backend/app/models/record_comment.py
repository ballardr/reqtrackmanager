"""
Module: models.record_comment

Comments on records of any registered artefact type that opts in through `ModuleDefinition.record_comments`, and the
optional pins that place a thread on a drawing.

Responsibilities:
- `RecordComment`: one comment on a record. With no `pin_id` it is an ordinary comment on the record; comments
  sharing a `pin_id` are one pinned thread, in creation order.
- `RecordCommentPin`: a place on the record's drawing (a free spot, a box or a line) that holds one thread, and the
  thread's resolved state. Resolving belongs to the pin.

Design decisions:
- `artefact_type` is a plain string validated against the module registry, as `ArtefactTag` and `ArtefactPlacement`
  do: a closed enum would need a per-module edit to this core file. `record_id` has no foreign key (it points into
  a different table per type), so `services.record_comments.forget_record_comments` clears a deleted record's rows.
- A record is owned by a project or by an organisation (exactly one), so an organisation-owned record's comments are
  isolated by organisation as a project's are by project. Both cascade with their owner.
- A pin keeps its last `x`/`y` even when its anchor is a box or a line, so a marker whose anchor leaves the drawing
  stays where it was last drawn instead of vanishing.
- Comment text is personal-free free text but may quote anything: it is never logged, audited or traced (the audit
  events carry ids and counts), and is searchable only on request (`SearchComments`).

External dependencies: `models.project`, `models.organization`, `models.user`.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, UUIDPKMixin, utcnow

#: How a pin is attached: `none` is a free spot, `node` a box, `edge` a line (a module's provider names which it allows).
PIN_ANCHOR_KINDS = ("none", "node", "edge")


class RecordCommentPin(UUIDPKMixin, Base):
    """One place on a record's drawing that holds a comment thread.

    Attributes:
        project_id / organization_id: The owner of the record (exactly one is set); the pin goes with it.
        artefact_type / record_id: The commented record (the drawing's owner).
        anchor_kind: `none`, `node` or `edge` (`PIN_ANCHOR_KINDS`).
        anchor_key: The module's key for the box or line (empty for `none`); its provider validates it.
        x / y: Canvas position: the spot itself for `none`, the last drawn position otherwise.
        resolved_at / resolved_by: Set while the thread is resolved.
        created_by: The user who placed it (kept NULL if the user is later removed).
        created_at: When it was placed (UTC).
    """

    __tablename__ = "record_comment_pins"
    __table_args__ = (
        CheckConstraint(
            "(project_id IS NOT NULL) <> (organization_id IS NOT NULL)", name="ck_record_comment_pins_one_owner"
        ),
        CheckConstraint("anchor_kind IN ('none', 'node', 'edge')", name="ck_record_comment_pins_anchor_kind"),
        CheckConstraint(
            "(anchor_kind = 'none') = (anchor_key IS NULL)", name="ck_record_comment_pins_anchor_key"
        ),
        Index("ix_record_comment_pins_record", "artefact_type", "record_id"),
        Index("ix_record_comment_pins_anchor", "anchor_kind", "anchor_key"),
    )

    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    artefact_type: Mapped[str] = mapped_column(String(40))
    record_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    anchor_kind: Mapped[str] = mapped_column(String(8), default="none")
    anchor_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    x: Mapped[float] = mapped_column(Float, default=0.0)
    y: Mapped[float] = mapped_column(Float, default=0.0)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RecordComment(UUIDPKMixin, TimestampMixin, Base):
    """One comment on a record.

    Attributes:
        project_id / organization_id: The owner of the record (exactly one is set).
        artefact_type / record_id: The commented record.
        pin_id: The pinned thread it belongs to, or NULL for an ordinary comment on the record.
        author_id: The author (NULL once the user is removed, shown as an unknown user).
        body: Plain text, never markup.
        edited_at: When the author last changed the body (UTC), or NULL.
    """

    __tablename__ = "record_comments"
    __table_args__ = (
        CheckConstraint(
            "(project_id IS NOT NULL) <> (organization_id IS NOT NULL)", name="ck_record_comments_one_owner"
        ),
        Index("ix_record_comments_record", "artefact_type", "record_id", "created_at"),
        Index("ix_record_comments_pin", "pin_id", "created_at"),
    )

    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    artefact_type: Mapped[str] = mapped_column(String(40))
    record_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    pin_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("record_comment_pins.id", ondelete="CASCADE"), nullable=True
    )
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    body: Mapped[str] = mapped_column(Text)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
