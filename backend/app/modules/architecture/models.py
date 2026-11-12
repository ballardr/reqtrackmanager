"""
Module: modules.architecture.models

The two vocabularies every architecture record is typed by, and the records:

- `ArchitectureElementType` — what an element is (System, Service, Board, ...).
- `ArchitectureConnectionType` — what an interface is (REST API, SPI, Power, ...).
- `ArchitectureElement` — a part of the product, in a tree, with `ArchitecturePort`s.
- `ArchitectureConnection` — an interface between two elements.

Each is one table whose owner is a project *or* an organisation (a CHECK keeps
exactly one). An organisation row is a default every project of the organisation
sees; a project row is its own addition. A project hides an organisation
default with a tombstone (`services.definition_suppression`) instead of
overriding it, so a row never needs a second set of columns for overrides.

A name is unique within its owner. Records will reference a type row directly,
whichever tier owns it, so hiding a default never changes a record that holds it.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, UUIDPKMixin
from app.models.principal import principal_check_constraint, principal_id_column, principal_type_column


class OwnedVocabularyMixin(UUIDPKMixin, TimestampMixin):
    """Columns shared by both vocabularies.

    Attributes:
        project_id: The owning project, or `NULL` for an organisation default.
        organization_id: The owning organisation, or `NULL` for a project row.
        name: Display name, unique within the owner.
        domain: A `Domain` value.
        color_light: Accent colour on a light theme, `#RRGGBB`, or `NULL` for the theme default.
        color_dark: Accent colour on a dark theme, `#RRGGBB`, or `NULL` for the theme default.
        sort_order: Picker order among the owner's rows.
    """

    @declared_attr
    def project_id(cls) -> Mapped[uuid.UUID | None]:
        return mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True)

    @declared_attr
    def organization_id(cls) -> Mapped[uuid.UUID | None]:
        return mapped_column(
            UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True,
        )

    name: Mapped[str] = mapped_column(String(100))
    domain: Mapped[str] = mapped_column(String(20), default="any")
    color_light: Mapped[str | None] = mapped_column(String(7), nullable=True)
    color_dark: Mapped[str | None] = mapped_column(String(7), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class ArchitectureElementType(OwnedVocabularyMixin, Base):
    """An element type (a project's own, or an organisation default).

    Attributes:
        shape: An `ElementShape` value, the outline drawn when no symbol is set.
    """

    __tablename__ = "architecture_element_types"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_architecture_element_types_project_name"),
        UniqueConstraint("organization_id", "name", name="uq_architecture_element_types_org_name"),
        CheckConstraint(
            "(project_id IS NULL) <> (organization_id IS NULL)", name="ck_architecture_element_types_one_owner",
        ),
    )

    shape: Mapped[str] = mapped_column(String(20), default="rectangle")


class ArchitectureConnectionType(OwnedVocabularyMixin, Base):
    """A connection type (a project's own, or an organisation default).

    Attributes:
        line_style: A `LineStyle` value.
        directional: Whether the interface has a direction (one-way); `False` is two-way.
    """

    __tablename__ = "architecture_connection_types"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_architecture_connection_types_project_name"),
        UniqueConstraint("organization_id", "name", name="uq_architecture_connection_types_org_name"),
        CheckConstraint(
            "(project_id IS NULL) <> (organization_id IS NULL)", name="ck_architecture_connection_types_one_owner",
        ),
    )

    line_style: Mapped[str] = mapped_column(String(20), default="solid")
    directional: Mapped[bool] = mapped_column(Boolean, default=True)


class ArchitectureElement(UUIDPKMixin, TimestampMixin, Base):
    """A part of the product: a system, service, board, sensor and so on.

    Elements form a tree through `parent_id` (the service enforces the same owner, no cycles and the depth
    cap). The record has no version rows: `version` is an optimistic counter that a save must quote, and the
    audit trail holds the history. A record that only exists inside a project is project-owned; the
    organisation tier arrives with sharing.

    Attributes:
        project_id: The owning project.
        unique_code: Project-scoped identifier (`ELM-001`), from `services.sequences.generate_unique_code`.
        name / description: Display name and free text.
        element_type_id: The element's type row, whichever tier owns it. No cascade (checked at the end of the
            statement, so a project's deletion can remove its types and elements together): the service never
            deletes a type that is in use.
        parent_id: The containing element, or `None` for a root. `SET NULL` is a backstop only: the service
            refuses to delete an element that has children.
        owner_type / owner_id: Optional principal (a user or a group) accountable for the element.
        status: A `RecordStatus` value.
        version: Optimistic counter, starting at 1 and advanced by every change to the element or its ports.
        creator_id: Who created the record.
        is_archived / archived_at / archived_by: Soft-delete.
    """

    __tablename__ = "architecture_elements"
    __table_args__ = (
        UniqueConstraint("project_id", "unique_code", name="uq_architecture_elements_project_unique_code"),
        CheckConstraint("parent_id IS NULL OR parent_id <> id", name="ck_architecture_elements_not_own_parent"),
        principal_check_constraint("owner", nullable=True),
        Index("ix_architecture_elements_project_parent", "project_id", "parent_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    unique_code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    element_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("architecture_element_types.id"), index=True
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("architecture_elements.id", ondelete="SET NULL"), nullable=True, index=True
    )
    owner_type: Mapped[str | None] = principal_type_column(nullable=True)
    owner_id: Mapped[uuid.UUID | None] = principal_id_column(nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    version: Mapped[int] = mapped_column(Integer, default=1)
    creator_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)


class ArchitecturePort(UUIDPKMixin, TimestampMixin, Base):
    """A named attachment point on an element. A child list of the element, not a coded record.

    Attributes:
        element_id: The element it belongs to; deleting the element removes its ports.
        name: Unique within the element.
        direction: A `PortDirection` value.
        connection_type_id: The interface the port speaks, or `None`. `SET NULL` is a backstop: a connection
            type in use is never deleted.
        sort_order: Order within the element.
    """

    __tablename__ = "architecture_ports"
    __table_args__ = (UniqueConstraint("element_id", "name", name="uq_architecture_ports_element_name"),)

    element_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("architecture_elements.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    direction: Mapped[str] = mapped_column(String(10), default="both")
    connection_type_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("architecture_connection_types.id", ondelete="SET NULL"), nullable=True,
        index=True,
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class ArchitectureConnection(UUIDPKMixin, TimestampMixin, Base):
    """An interface between two elements (optionally via a port on each).

    Attributes:
        project_id: The owning project, which created it.
        unique_code: Project-scoped identifier (`CON-001`).
        name: Display name; may be empty in the API, in which case the summary shows the ends.
        connection_type_id: The interface type row. No cascade, as for `ArchitectureElement.element_type_id`.
        source_element_id / target_element_id: The two ends (never the same element). No cascade: the service
            refuses to delete an element a connection names, since the connection would lose an end.
        source_port_id / target_port_id: A port of the matching end, or `None`. `SET NULL` when the port is removed.
        protocol: Free-text detail (version, topic, baud rate).
        description: Free text.
        status: A `RecordStatus` value.
        version: Optimistic counter.
        creator_id / is_archived / archived_at / archived_by: As for `ArchitectureElement`.
    """

    __tablename__ = "architecture_connections"
    __table_args__ = (
        UniqueConstraint("project_id", "unique_code", name="uq_architecture_connections_project_unique_code"),
        CheckConstraint("source_element_id <> target_element_id", name="ck_architecture_connections_distinct_ends"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    unique_code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200), default="")
    connection_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("architecture_connection_types.id"), index=True
    )
    source_element_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("architecture_elements.id"), index=True
    )
    source_port_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("architecture_ports.id", ondelete="SET NULL"), nullable=True
    )
    target_element_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("architecture_elements.id"), index=True
    )
    target_port_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("architecture_ports.id", ondelete="SET NULL"), nullable=True
    )
    protocol: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="draft")
    version: Mapped[int] = mapped_column(Integer, default=1)
    creator_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
