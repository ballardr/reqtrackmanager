"""
Module: models.definition_suppression

`ProjectDefinitionSuppression`: a project's decision to hide one organisation
default (a Pain Point type, a Persona type, ...) from its own view of that
vocabulary. A "tombstone": it records only *that* the org row is hidden here,
so a later change to the org row still reaches every project that has not hidden
it, and restoring is deleting the tombstone.

Design decisions:
- `definition_kind` is a plain, module-registrable string checked against
  `services.definition_suppression`'s registry (the `ArtefactLink.source_type`
  approach), never a closed enum a module would have to hand-edit.
- `org_definition_id` has no foreign key (it points into a different table per
  kind); the owner of the org row removes its tombstones when it deletes the row
  (`services.definition_suppression.forget_definition`).
- Hiding only stops *new* use. Records that already hold the value keep it.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ProjectDefinitionSuppression(Base):
    """One organisation default hidden in one project.

    Attributes:
        project_id: The project that hid the default.
        definition_kind: Registered vocabulary kind (e.g. `"pain_point_type"`).
        org_definition_id: Id of the hidden organisation-level row.
    """

    __tablename__ = "project_definition_suppressions"
    __table_args__ = (Index("ix_project_definition_suppressions_definition", "definition_kind", "org_definition_id"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    definition_kind: Mapped[str] = mapped_column(String(60), primary_key=True)
    org_definition_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
