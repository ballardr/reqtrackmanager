"""
Module: models.external_reference

External references: pointers from any record to the same work in an outside tool (a Jira epic, a ServiceNow
ticket, a customer's register), so a record can be found from either side.

- `ExternalSystemDefinition`: the organisation's ordered list of outside systems, each with an optional URL template.
- `ProjectExternalSystem`: a project's view of that list (an override of an organisation entry, or its own entry);
  a hidden organisation entry is a `ProjectDefinitionSuppression` tombstone (as `services.type_vocabulary.TypeVocabulary`).
- `ExternalReference`: one pointer from a record to an item in a system, keyed by the registered artefact type
  string as tags and placements are, so a new record type needs no code here.

Design decisions:
- `artefact_type` is a plain registrable string validated against the registry, not a closed enum, and
  `artefact_id` has no foreign key (the record's owner calls `services.external_references.forget_record_references`
  on permanent deletion). The owning project and organisation are columns so deleting either removes the references.
- Exactly one system column is set: an organisation-owned record (`project_id` null) uses the organisation's entry,
  a project record the project's row (a CHECK ties them).
- `url_template` holds `{key}` once; a reference with no URL of its own links to the template with the key URL-encoded
  (`services.external_references.link_for`). Only `http` or `https` templates are accepted.
- `role` is optional: `origin` (the record came from that item) or `delivery` (it is built there).
"""

from __future__ import annotations

import enum
import uuid

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, UUIDPKMixin, str_enum


class ExternalReferenceRole(str, enum.Enum):
    """What a reference is: the item the record came from, or the one where it is delivered."""

    ORIGIN = "origin"
    DELIVERY = "delivery"


class ExternalSystemDefinition(UUIDPKMixin, TimestampMixin, Base):
    """Organisation-scoped base list of outside systems a record can point into (Jira, ServiceNow, ...).
    `sort_order` is the name `services.ordering.move_ordered` expects.

    Attributes:
        organization_id: The owning organisation.
        name: Display name, unique per organisation.
        sort_order: Display / picker order.
        is_active: Soft-disable; an inactive system drops out of every project's list without being deleted.
        url_template: Optional link pattern with one `{key}`, used for a reference that carries no URL of its own.
    """

    __tablename__ = "external_system_definitions"
    __table_args__ = (UniqueConstraint("organization_id", "name", name="uq_external_system_definitions_org_name"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(100))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    url_template: Mapped[str | None] = mapped_column(String(500), nullable=True)


class ProjectExternalSystem(UUIDPKMixin, TimestampMixin, Base):
    """A project's own view onto the external system list: an override of one organisation system, or a system of
    its own (`org_type_id` null, named by `name_override`; enforced by a CHECK). `url_template` on an override
    replaces the organisation's template here; null follows it."""

    __tablename__ = "project_external_systems"
    __table_args__ = (
        UniqueConstraint("project_id", "org_type_id", name="uq_project_external_systems_project_org_type"),
        CheckConstraint(
            "org_type_id IS NOT NULL OR name_override IS NOT NULL", name="ck_project_external_systems_local_has_name"
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"))
    org_type_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("external_system_definitions.id", ondelete="SET NULL"), nullable=True
    )
    name_override: Mapped[str | None] = mapped_column(String(100), nullable=True)
    display_order_override: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    url_template: Mapped[str | None] = mapped_column(String(500), nullable=True)


class ExternalReference(UUIDPKMixin, TimestampMixin, Base):
    """A pointer from a record to an item in an outside tool. Several per record, added and removed on their own (each
    with an audit event), so a change here does not create a content version.

    Attributes:
        artefact_type / artefact_id: The record (a registered artefact type string; no foreign key).
        organization_id: The record's organisation (the references go with it).
        project_id: The record's project, or null for an organisation-owned record.
        org_system_id / project_system_id: The system, from the list of the record's tier (exactly one is set).
        key: The item's key in that system (e.g. `PROJ-123`).
        url: Optional link to the item; only an absolute http(s) URL is accepted.
        note: Optional short text about the reference.
        role: Optional `origin` or `delivery`.
        created_by: Who added it.
    """

    __tablename__ = "external_references"
    __table_args__ = (
        CheckConstraint(
            "(org_system_id IS NOT NULL) <> (project_system_id IS NOT NULL)", name="ck_external_references_one_system"
        ),
        CheckConstraint(
            "(project_id IS NULL) = (org_system_id IS NOT NULL)", name="ck_external_references_tier_matches_owner"
        ),
        Index("ix_external_references_record", "artefact_type", "artefact_id"),
    )

    artefact_type: Mapped[str] = mapped_column(String(64))
    artefact_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    org_system_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("external_system_definitions.id", ondelete="CASCADE"), nullable=True, index=True
    )
    project_system_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_external_systems.id", ondelete="CASCADE"), nullable=True, index=True
    )
    key: Mapped[str] = mapped_column(String(100), default="")
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    note: Mapped[str] = mapped_column(String(500), default="")
    role: Mapped[ExternalReferenceRole | None] = mapped_column(str_enum(ExternalReferenceRole, 20), nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
