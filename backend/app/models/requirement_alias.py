"""
Module: models.requirement_alias

Requirement aliases: the further places a requirement sits in, each with a code of its own.

Responsibilities:
- `RequirementAlias`: one further (component, category) pair of a requirement and the code issued for it.

Design decisions:
- A requirement keeps its single `component_id`/`category_id` as the primary pair, and its `unique_code` is the
  record's identity. An alias names the same record: one set of content, versions, approval, comments, links and
  attachments, found under every code. Aliases are not rows of `artefact_placements`, because each carries a code
  numbered from the project's one requirement counter (`services.requirements._next_sequence`), so a code is never
  reused and never collides with a primary code.
- A removed alias is retired, not deleted: its code still resolves to the record (with a notice) so a citation
  does not break. A retired row keeps its pair for display; the pair columns become NULL only when the component
  or category itself is deleted. At most one active alias exists per record and pair.
- `project_id` cascades with the project; `requirement_id` cascades with the requirement.
- Aliases are not Restricted-classified data (docs/soc2/policies data classification).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import UUIDPKMixin, utcnow


class RequirementAlias(UUIDPKMixin, Base):
    """A further component and category a requirement sits in, with its own code.

    Attributes:
        project_id: The project owning the requirement.
        requirement_id: The requirement the alias names.
        component_id / category_id: The pair. NULL only for a retired alias whose component or category was deleted.
        unique_code: The alias code (`HW-IF-017`), unique in the project and never reused.
        is_retired: Set when the requirement was taken out of the pair; the code keeps resolving to the record.
        retired_at: When it was retired (UTC).
        created_by: The user who added it (kept NULL if the user is later removed).
        created_at: When it was added (UTC).
    """

    __tablename__ = "requirement_aliases"
    __table_args__ = (
        UniqueConstraint("project_id", "unique_code", name="uq_requirement_aliases_code"),
        Index("ix_requirement_aliases_requirement", "requirement_id"),
        Index("ix_requirement_aliases_project", "project_id"),
        Index("ix_requirement_aliases_component", "component_id"),
        Index("ix_requirement_aliases_category", "category_id"),
        Index(
            "ux_requirement_aliases_active_pair", "requirement_id", "component_id", "category_id",
            unique=True, postgresql_where=sa_text("is_retired IS FALSE"),
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"))
    requirement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("requirements.id", ondelete="CASCADE")
    )
    component_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_components.id", ondelete="SET NULL"), nullable=True
    )
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_categories.id", ondelete="SET NULL"), nullable=True
    )
    unique_code: Mapped[str] = mapped_column(String(64))
    is_retired: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_text("false"))
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
