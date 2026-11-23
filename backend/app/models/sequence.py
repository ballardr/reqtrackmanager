"""
Module: models.sequence

The generic per-artefact-type sequence counters (per project and, for organisation-owned records, per
organisation) that every identified artefact type generates its unique code from, instead of a
`next_<type>_seq` column on `Project` (as `Requirement.next_requirement_seq` and
`RequirementAction.next_action_seq` in `models.project.Project`).

A single `ProjectSequenceCounter` table (`project_id`, `artefact_type`, `next_seq`) holds one row per
artefact type a project has generated a code for (**Decided by: User**, docs/decisions.md's Platform
Foundations entry). `Project.next_requirement_seq`/`next_action_seq` are unchanged.

`artefact_type` is a plain, module-registrable string validated at the service layer against
`app.modules.registry.get_all_registered_artefact_types()`, not the fixed `models.enums.ArtefactType` enum,
so a module declares its type once on `ModuleDefinition.artefact_types` and both this table and
`ArtefactLink` accept it with no core edit (docs/decisions.md, "Decision Management -
ProjectSequenceCounter made module-registrable").
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, UUIDPKMixin


class ProjectSequenceCounter(UUIDPKMixin, TimestampMixin, Base):
    """Tracks the next never-reused sequence number for one `(project, artefact_type)` pair, backing
    `services.sequences.generate_unique_code`.

    Attributes:
        project_id: The project this counter belongs to.
        artefact_type: The artefact type, a plain string (for example `"requirement"`, `"decision"`)
            validated by `generate_unique_code` against `get_all_registered_artefact_types()`. A project has
            at most one row per value, created the first time that type's code is generated.
        next_seq: The next number to hand out; advanced under a row lock
            (`services.sequences._next_sequence`) so it is never reused.
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


class OrganizationSequenceCounter(UUIDPKMixin, TimestampMixin, Base):
    """Tracks the next never-reused sequence number for one `(organization, artefact_type)` pair: the counter
    behind the codes of organisation-owned records (`PER-001`, shown qualified as `ACME-PER-001`). The
    organisation-level twin of `ProjectSequenceCounter`; a type at both scopes keeps a counter per project
    and one per organisation, so the two never collide.

    Attributes:
        organization_id: The organisation this counter belongs to.
        artefact_type: Which registered artefact type it numbers.
        next_seq: The next number to hand out; advanced under a lock on the
            organisation row (`services.sequences._next_sequence`) so it is
            never reused.
    """

    __tablename__ = "organization_sequence_counters"
    __table_args__ = (
        UniqueConstraint("organization_id", "artefact_type", name="uq_organization_sequence_counters_org_type"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE")
    )
    artefact_type: Mapped[str] = mapped_column(String(40))
    next_seq: Mapped[int] = mapped_column(Integer, default=1)
