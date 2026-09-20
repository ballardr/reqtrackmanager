"""
Module: models.sequence

Module 0 (Platform Foundations), Phase 2: the generic per-project,
per-artefact-type sequence counter every *new* identified artefact type in
the future-modules roadmap (Decision, Design, Risk, Pain Point, Strategy,
Guiding Principle, Open Question, Stakeholder/Persona) generates its unique
code from, instead of each module adding its own `next_<type>_seq` integer
column to `Project` the way `Requirement.next_requirement_seq` and
`RequirementAction.next_action_seq` (`models.project.Project`) already do.

Design decision (Decided by: User, docs/decisions.md "Module 0 (Platform
Foundations) Phase 0"): a single `ProjectSequenceCounter` table
(`project_id`, `artefact_type`, `next_seq`), one row per artefact type a
project has ever generated a code for, rather than `Project` accumulating
one more near-identical column per module. `Project.next_requirement_seq`/
`next_action_seq` are deliberately left untouched — this table is additive,
for new artefact types only, not a migration of the existing two.

`artefact_type` reuses `models.enums.ArtefactType` — the same shared
vocabulary `models.relationship.ArtefactLink` already extends per new
module — rather than a second, parallel "what kind of artefact is this"
enum; both concerns need the same vocabulary for the same set of future
artefact types.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, UUIDPKMixin, str_enum
from app.models.enums import ArtefactType


class ProjectSequenceCounter(UUIDPKMixin, TimestampMixin, Base):
    """Tracks the next never-reused sequence number for one
    `(project, artefact_type)` pair, backing `services.sequences.
    generate_unique_code`.

    Attributes:
        project_id: The project this counter belongs to.
        artefact_type: Which artefact type this counter is for — a project
            has at most one row per `ArtefactType` value, created lazily
            the first time that type's code is generated in that project.
        next_seq: The next sequence number to hand out; advanced under a
            row lock (see `services.sequences._next_sequence`) so it is
            never reused, mirroring `next_requirement_seq`'s own
            never-reused guarantee.
    """

    __tablename__ = "project_sequence_counters"
    __table_args__ = (
        UniqueConstraint("project_id", "artefact_type", name="uq_project_sequence_counters_project_type"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE")
    )
    artefact_type: Mapped[ArtefactType] = mapped_column(str_enum(ArtefactType, 20))
    next_seq: Mapped[int] = mapped_column(Integer, default=1)
