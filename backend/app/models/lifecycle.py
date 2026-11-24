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
- Approval separation (whether the person who created a record may approve it) has one row per `(project, type)`
  for a project's choice, one per `(organisation, type)` where the organisation requires a separate approver, and one
  exemption per `(organisation, type, project)`; a record approved by its own creator is marked by one
  `RecordSelfApproval` row, replaced at every approval.
- Skipping steps on one record is configured per project (a row exists once the project chose; no row follows the
  nearest ancestor, else off) and can be forbidden for the whole organisation, with exempt projects, mirroring the
  required states above.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint
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


class ProjectLifecycleSkipSetting(UUIDPKMixin, TimestampMixin, Base):
    """Whether a project allows a record to be moved past steps of its path.

    Attributes:
        project_id: The owning project.
        allowed: Whether skipping steps is on. No row follows the nearest ancestor project, else it is off.
    """

    __tablename__ = "project_lifecycle_skip_settings"
    __table_args__ = (UniqueConstraint("project_id", name="uq_project_lifecycle_skip_settings"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    allowed: Mapped[bool] = mapped_column(Boolean, default=False)


class OrganizationLifecycleSkipPolicy(UUIDPKMixin, TimestampMixin, Base):
    """The organisation's rule on skipping steps.

    Attributes:
        organization_id: The organisation.
        forbidden: Whether no project of the organisation may skip steps (except its exempt projects).
    """

    __tablename__ = "organization_lifecycle_skip_policies"
    __table_args__ = (UniqueConstraint("organization_id", name="uq_org_lifecycle_skip_policies"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    forbidden: Mapped[bool] = mapped_column(Boolean, default=False)


class OrganizationLifecycleSkipExemption(UUIDPKMixin, TimestampMixin, Base):
    """A project the organisation's ban on skipping steps does not bind.

    Attributes:
        organization_id: The organisation that granted the exemption.
        project_id: The exempt project.
        include_children: Whether the project's nested child projects are exempt too.
    """

    __tablename__ = "organization_lifecycle_skip_exemptions"
    __table_args__ = (UniqueConstraint("organization_id", "project_id", name="uq_org_lifecycle_skip_exemptions"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    include_children: Mapped[bool] = mapped_column(Boolean, default=False)


class ProjectApprovalSeparationSetting(UUIDPKMixin, TimestampMixin, Base):
    """A project's own choice on whether the creator of a record may approve it, for one record type.

    Attributes:
        project_id: The owning project.
        artefact_type: The registered record type with an approval gate.
        separate_approver: Whether a person other than the creator must approve. No row follows the nearest ancestor
            project, else the type's default (the creator may approve).
    """

    __tablename__ = "project_approval_separation_settings"
    __table_args__ = (UniqueConstraint("project_id", "artefact_type", name="uq_project_approval_separation_settings"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    artefact_type: Mapped[str] = mapped_column(String(64))
    separate_approver: Mapped[bool] = mapped_column(Boolean, default=False)


class OrganizationApprovalSeparationRequirement(UUIDPKMixin, TimestampMixin, Base):
    """An organisation's rule that a separate approver is required for one record type in every project.

    Attributes:
        organization_id: The organisation that requires it.
        artefact_type: The registered record type with an approval gate.
    """

    __tablename__ = "organization_approval_separation_requirements"
    __table_args__ = (
        UniqueConstraint("organization_id", "artefact_type", name="uq_org_approval_separation_requirements"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    artefact_type: Mapped[str] = mapped_column(String(64))


class OrganizationApprovalSeparationExemption(UUIDPKMixin, TimestampMixin, Base):
    """A project the organisation's requirement of a separate approver does not bind.

    Attributes:
        organization_id: The organisation that granted the exemption.
        artefact_type: The registered record type the exemption covers.
        project_id: The exempt project.
        include_children: Whether the project's nested child projects are exempt too.
    """

    __tablename__ = "organization_approval_separation_exemptions"
    __table_args__ = (
        UniqueConstraint("organization_id", "artefact_type", "project_id", name="uq_org_approval_separation_exemptions"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    artefact_type: Mapped[str] = mapped_column(String(64))
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    include_children: Mapped[bool] = mapped_column(Boolean, default=False)


class RecordSelfApproval(UUIDPKMixin, Base):
    """Marks a record whose latest approval was given by the person who created it.

    A row exists only while the latest approval of the record was a self-approval: every approval deletes the
    record's row and a self-approval adds a new one.

    Attributes:
        artefact_type: The registered record type.
        record_id: The record (not a foreign key: the type's table is registered by name).
        organization_id: The organisation the record belongs to.
        project_id: The record's project, `None` for a record the organisation owns.
        approved_by: The person who approved.
        approved_at: When (UTC).
    """

    __tablename__ = "record_self_approvals"
    __table_args__ = (UniqueConstraint("artefact_type", "record_id", name="uq_record_self_approvals"),)

    artefact_type: Mapped[str] = mapped_column(String(64))
    record_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    approved_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
