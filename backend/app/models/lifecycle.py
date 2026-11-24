"""
Module: models.lifecycle

Lifecycle configuration: which optional states of a record type a project uses, which states an organisation
requires, and which projects an organisation exempts from that requirement.

Design decisions:
- `artefact_type` and each state are plain registered strings, validated against `ModuleDefinition.lifecycles` in
  `services.lifecycles`, never a closed enum a module would have to hand-edit.
- A project row exists per type once the project chose for it (an empty list is an explicit "all states on"); no row
  means "follow the nearest ancestor project, else every state on" (`services.lifecycles.resolve_project_lifecycles`).
- A state turned off is never deleted from the data: records already in it stay valid.
- An organisation requirement is one row per `(type, state)`; an exemption is one row per `(type, project)` and may
  cover the project's nested children.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, UUIDPKMixin


class ProjectLifecycleSetting(UUIDPKMixin, TimestampMixin, Base):
    """The optional states a project turned off for one record type.

    Attributes:
        project_id: The owning project.
        artefact_type: The registered record type.
        disabled_states: State keys the project does not use (a subset of the type's optional states).
    """

    __tablename__ = "project_lifecycle_settings"
    __table_args__ = (UniqueConstraint("project_id", "artefact_type", name="uq_project_lifecycle_settings"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    artefact_type: Mapped[str] = mapped_column(String(64))
    disabled_states: Mapped[list[str]] = mapped_column(JSONB, default=list)


class OrganizationLifecycleRequirement(UUIDPKMixin, TimestampMixin, Base):
    """A state an organisation requires every project to keep on.

    Attributes:
        organization_id: The organisation that requires it.
        artefact_type: The registered record type.
        state: The required state key (an optional state of the type).
    """

    __tablename__ = "organization_lifecycle_requirements"
    __table_args__ = (UniqueConstraint("organization_id", "artefact_type", "state", name="uq_org_lifecycle_requirements"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    artefact_type: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(64))


class OrganizationLifecycleExemption(UUIDPKMixin, TimestampMixin, Base):
    """A project the organisation's required states of one type do not bind.

    Attributes:
        organization_id: The organisation that granted the exemption.
        artefact_type: The registered record type the exemption covers.
        project_id: The exempt project.
        include_children: Whether the project's nested child projects are exempt too.
    """

    __tablename__ = "organization_lifecycle_exemptions"
    __table_args__ = (UniqueConstraint("organization_id", "artefact_type", "project_id", name="uq_org_lifecycle_exemptions"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    artefact_type: Mapped[str] = mapped_column(String(64))
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    include_children: Mapped[bool] = mapped_column(Boolean, default=False)
