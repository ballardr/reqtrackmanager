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

`artefact_type` is a plain, module-registrable string, validated at the
service layer against `app.modules.registry.get_all_registered_artefact_
types()` — **corrected 2026-09-21** (Module 4, Decision Management, Phase
1) from this column's original shape, which bound it to the fixed
`models.enums.ArtefactType` Python enum. That original shape required every
new artefact-generating module to hand-edit a core enum, the exact
per-module core-file-edit failure mode `models.relationship.ArtefactLink.
source_type`/`target_type` was deliberately built to avoid one phase
earlier (Module 0 Phase 3, `ModuleDefinition.artefact_types` +
`get_all_registered_artefact_types`) — this table just didn't get the same
treatment at the time. Now it does: a module declares its own artefact-type
string(s) on `ModuleDefinition.artefact_types` once, and both this table and
`ArtefactLink` recognise it with no further core-file changes required for
the next module. See `docs/decisions.md`'s "Module 4 (Decision Management)
Phase 1 — ProjectSequenceCounter made module-registrable" entry.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, UUIDPKMixin


class ProjectSequenceCounter(UUIDPKMixin, TimestampMixin, Base):
    """Tracks the next never-reused sequence number for one
    `(project, artefact_type)` pair, backing `services.sequences.
    generate_unique_code`.

    Attributes:
        project_id: The project this counter belongs to.
        artefact_type: Which artefact type this counter is for — a plain
            string (e.g. `"requirement"`, `"decision"`), validated by
            `services.sequences.generate_unique_code` against
            `app.modules.registry.get_all_registered_artefact_types()`
            rather than typed as a closed Python enum (see module
            docstring for why). A project has at most one row per distinct
            value, created lazily the first time that type's code is
            generated in that project.
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
    artefact_type: Mapped[str] = mapped_column(String(40))
    next_seq: Mapped[int] = mapped_column(Integer, default=1)
