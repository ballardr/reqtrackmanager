"""
Module: models.placement

Placements: where a record sits in the project's component/category tree.

Responsibilities:
- `ArtefactPlacement`: one (component, optional category) pair held by one record of any registered
  artefact type other than a requirement or change request, which keep their own single
  `component_id`/`category_id` columns because the component prefix forms the requirement code.

Design decisions:
- `artefact_type` is a plain string validated against the module registry, as `ArtefactTag` and
  `ArtefactLink` do: a closed enum would need a per-module edit to this core file. `artefact_id`
  has no foreign key (the id points into a different table per type).
- A record may hold any number of placements with no primary one. Uniqueness per record is two
  partial indexes (with and without a category), because Postgres treats NULLs in a unique
  constraint as distinct.
- `project_id` is the project owning the record (a component belongs to exactly one project, so
  a placement never crosses projects) and cascades with it. Component and category foreign keys
  cascade as a backstop; the taxonomy endpoints reassign or refuse first so no placement is lost
  silently (`services.placements`).
- Placements are not Restricted-classified data (docs/soc2/policies data classification).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import UUIDPKMixin, utcnow


class ArtefactPlacement(UUIDPKMixin, Base):
    """A record's place in the component/category tree.

    Attributes:
        project_id: The project owning the record and the component.
        artefact_type / artefact_id: The placed record; the type is a registered artefact type.
        component_id: The component (required).
        category_id: The category under that component, or NULL for the component alone.
        created_by: The user who made the placement (kept NULL if the user is later removed).
        created_at: When it was made (UTC).
    """

    __tablename__ = "artefact_placements"
    __table_args__ = (
        Index("ix_artefact_placements_record", "artefact_type", "artefact_id"),
        Index("ix_artefact_placements_project_type", "project_id", "artefact_type"),
        Index("ix_artefact_placements_component", "component_id"),
        Index("ix_artefact_placements_category", "category_id"),
        Index(
            "ux_artefact_placements_category", "artefact_type", "artefact_id", "component_id", "category_id",
            unique=True, postgresql_where=sa_text("category_id IS NOT NULL"),
        ),
        Index(
            "ux_artefact_placements_component", "artefact_type", "artefact_id", "component_id",
            unique=True, postgresql_where=sa_text("category_id IS NULL"),
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"))
    artefact_type: Mapped[str] = mapped_column(String(40))
    artefact_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    component_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_components.id", ondelete="CASCADE")
    )
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_categories.id", ondelete="CASCADE"), nullable=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
