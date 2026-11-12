"""
Module: modules.architecture.models

The two vocabularies every architecture record is typed by, and the records:

- `ArchitectureSymbol` — a drawing (a sanitised SVG, or one of the built-in set) an element type or element is shown with.
- `ArchitectureElementType` — what an element is (System, Service, Board, ...); it may name suggested connection types
  (`ArchitectureElementTypeSuggestion`) that a connection picker lists first.
- `ArchitectureConnectionType` — what an interface is (REST API, SPI, Power, ...); a type sits in a tree of any depth
  and may have several parents (`ArchitectureConnectionTypeParent`), so a group is itself a usable type.
- `ArchitectureElement` — a part of the product, in a tree, with `ArchitecturePort`s; owned by a project
  or by the organisation.
- `ArchitectureConnection` — an interface between two elements.
- `ArchitectureCollection`, `ArchitectureCollectionMember`, `ArchitectureCollectionGrant` — a named set of
  elements and who it is shared with (a project, optionally with its descendants, or a group).
- `ArchitectureDiagram` with its `ArchitectureDiagramPlacement`s, `ArchitectureDiagramNote`s,
  `ArchitectureDiagramAnchor`s and `ArchitectureDiagramToggle`s (and their manual `ArchitectureDiagramToggleMember`s) — a
  saved view over the project's model; it holds no truth of its own.

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

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, declared_attr, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, UUIDPKMixin
from app.models.principal import principal_check_constraint, principal_id_column, principal_type_column


class OwnedNamedMixin(UUIDPKMixin, TimestampMixin):
    """Columns shared by every table a project or the organisation owns a named, ordered list of (the two vocabularies
    and the symbol library), so the code that lists, hides and orders them treats them alike.

    Attributes:
        project_id: The owning project, or `NULL` for an organisation default.
        organization_id: The owning organisation, or `NULL` for a project row.
        name: Display name, unique within the owner.
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
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class OwnedVocabularyMixin(OwnedNamedMixin):
    """Columns shared by both vocabularies, on top of `OwnedNamedMixin`.

    Attributes:
        domain: A `Domain` value.
        color_light: Accent colour on a light theme, `#RRGGBB`, or `NULL` for the theme default.
        color_dark: Accent colour on a dark theme, `#RRGGBB`, or `NULL` for the theme default.
    """

    domain: Mapped[str] = mapped_column(String(20), default="any")
    color_light: Mapped[str | None] = mapped_column(String(7), nullable=True)
    color_dark: Mapped[str | None] = mapped_column(String(7), nullable=True)


class ArchitectureSymbol(OwnedNamedMixin, Base):
    """A drawing an element type, or one element, is shown with: a library entry, not a record (no code, link or search).

    Owned by a project or the organisation (a CHECK keeps exactly one) and listed, hidden and restored like a type
    (`service.SymbolLibrary`). Either a stored file (`file_asset_id`: an upload, kept in its sanitised form) or a
    built-in drawing (`builtin_key`, drawn by `symbols.BUILTIN_SVG`, no file); a CHECK keeps exactly one.

    Attributes:
        file_asset_id: The stored SVG, or `None` for a built-in. A copy of an inherited project row shares the file, so
            the file is deleted only with the last row that names it. `SET NULL` is a backstop only.
        builtin_key: The built-in drawing, or `None` for an upload. Built-in rows cannot be renamed.
    """

    __tablename__ = "architecture_symbols"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_architecture_symbols_project_name"),
        UniqueConstraint("organization_id", "name", name="uq_architecture_symbols_org_name"),
        CheckConstraint("(project_id IS NULL) <> (organization_id IS NULL)", name="ck_architecture_symbols_one_owner"),
        CheckConstraint("(file_asset_id IS NULL) <> (builtin_key IS NULL)", name="ck_architecture_symbols_one_source"),
    )

    file_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("file_assets.id", ondelete="SET NULL"), nullable=True, index=True
    )
    builtin_key: Mapped[str | None] = mapped_column(String(40), nullable=True)

    @property
    def is_builtin(self) -> bool:
        """Whether this is one of the built-in drawings."""
        return self.builtin_key is not None


class ArchitectureElementType(OwnedVocabularyMixin, Base):
    """An element type (a project's own, or an organisation default).

    Attributes:
        shape: An `ElementShape` value, the outline drawn when no symbol is set.
        symbol_id: The symbol its elements are drawn with, or `None` to draw `shape`. `SET NULL` is a backstop: a
            symbol in use is never deleted.
        suggestion_links: The connection types suggested for a connection that has an element of this type at an end.
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
    symbol_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("architecture_symbols.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Declared only so a flush inserts a new symbol before a type or element that names it; never loaded through.
    symbol: Mapped[ArchitectureSymbol | None] = relationship("ArchitectureSymbol", lazy="raise", viewonly=False)
    # Loaded with the row (one extra statement per list) so an API list carries the ids without a read per row.
    suggestion_links: Mapped[list[ArchitectureElementTypeSuggestion]] = relationship(
        "ArchitectureElementTypeSuggestion", foreign_keys="ArchitectureElementTypeSuggestion.element_type_id",
        lazy="selectin", cascade="all, delete-orphan", order_by="ArchitectureElementTypeSuggestion.connection_type_id",
        back_populates="element_type",
    )

    @property
    def suggested_connection_type_ids(self) -> list[uuid.UUID]:
        """The ids of the connection types suggested for this element type (empty for none)."""
        return [link.connection_type_id for link in self.suggestion_links]


class ArchitectureElementTypeSuggestion(Base):
    """One suggestion: a connection with an element of `element_type_id` at an end is offered `connection_type_id` first.

    Guidance only: nothing is refused when another type is chosen. The connection type is in the element type's own
    tier or an organisation default visible to it (the service checks). Deleting either type removes the row.

    Attributes:
        element_type_id: The element type the suggestion belongs to.
        connection_type_id: The suggested connection type.
    """

    __tablename__ = "architecture_element_type_suggestions"

    element_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("architecture_element_types.id", ondelete="CASCADE"), primary_key=True,
    )
    connection_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("architecture_connection_types.id", ondelete="CASCADE"), primary_key=True,
        index=True,
    )
    element_type: Mapped[ArchitectureElementType] = relationship(
        "ArchitectureElementType", foreign_keys=[element_type_id], back_populates="suggestion_links", lazy="raise",
    )


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
    # Loaded with the row (one extra statement per list) so an API list carries `parent_ids` without a read per row.
    parent_links: Mapped[list[ArchitectureConnectionTypeParent]] = relationship(
        "ArchitectureConnectionTypeParent", foreign_keys="ArchitectureConnectionTypeParent.child_id", lazy="selectin",
        cascade="all, delete-orphan", order_by="ArchitectureConnectionTypeParent.parent_id", back_populates="child",
    )

    @property
    def parent_ids(self) -> list[uuid.UUID]:
        """The ids of the types this one sits under (empty for a root)."""
        return [link.parent_id for link in self.parent_links]


class ArchitectureConnectionTypeParent(Base):
    """One edge of the connection type tree: `child_id` sits under `parent_id`.

    A type may have several parents and the tree has any depth (the service refuses a cycle and a chain deeper than
    `connection_tree.MAX_TYPE_DEPTH`). A parent is in the child's own tier or an organisation default visible to it.
    Deleting either type removes the edge: the children of a deleted group become roots.

    Attributes:
        child_id: The nested type.
        parent_id: The type it sits under.
    """

    __tablename__ = "architecture_connection_type_parents"
    __table_args__ = (CheckConstraint("child_id <> parent_id", name="ck_architecture_connection_type_parents_not_self"),)

    child_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("architecture_connection_types.id", ondelete="CASCADE"), primary_key=True,
    )
    parent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("architecture_connection_types.id", ondelete="CASCADE"), primary_key=True, index=True,
    )
    child: Mapped[ArchitectureConnectionType] = relationship(
        "ArchitectureConnectionType", foreign_keys=[child_id], back_populates="parent_links", lazy="raise",
    )


class ArchitectureElement(UUIDPKMixin, TimestampMixin, Base):
    """A part of the product: a system, service, board, sensor and so on.

    Elements form a tree through `parent_id` (the service enforces the same owner, no cycles and the depth
    cap). The record has no version rows: `version` is an optimistic counter that a save must quote, and the
    audit trail holds the history. An element is owned by a project or by the organisation (a CHECK keeps
    exactly one); another owner reaches it only through the visibility rules in `visibility`.

    Attributes:
        project_id: The owning project, or `None` for an organisation-owned element.
        organization_id: The owning organisation, or `None` for a project-owned element.
        unique_code: Identifier unique within its owner (`ELM-001`), from `services.sequences.generate_unique_code`.
        name / description: Display name and free text.
        element_type_id: The element's type row, whichever tier owns it. No cascade (checked at the end of the
            statement, so a project's deletion can remove its types and elements together): the service never
            deletes a type that is in use.
        parent_id: The containing element, or `None` for a root. `SET NULL` is a backstop only: the service
            refuses to delete an element that has children.
        owner_type / owner_id: Optional principal (a user or a group) accountable for the element.
        symbol_id: A symbol drawn instead of the type's, or `None` to use the type's. The owner's own symbol (a project
            element: the project's effective library; an organisation element: the organisation's). `SET NULL` is a backstop.
        status: A `RecordStatus` value.
        version: Optimistic counter, starting at 1 and advanced by every change to the element or its ports.
        creator_id: Who created the record.
        is_archived / archived_at / archived_by: Soft-delete.
    """

    __tablename__ = "architecture_elements"
    __table_args__ = (
        UniqueConstraint("project_id", "unique_code", name="uq_architecture_elements_project_unique_code"),
        UniqueConstraint("organization_id", "unique_code", name="uq_architecture_elements_org_unique_code"),
        CheckConstraint("(project_id IS NULL) <> (organization_id IS NULL)", name="ck_architecture_elements_one_owner"),
        CheckConstraint("parent_id IS NULL OR parent_id <> id", name="ck_architecture_elements_not_own_parent"),
        principal_check_constraint("owner", nullable=True),
        Index("ix_architecture_elements_project_parent", "project_id", "parent_id"),
    )

    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True
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
    symbol_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("architecture_symbols.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Declared only so a flush inserts a new symbol before a type or element that names it; never loaded through.
    symbol: Mapped[ArchitectureSymbol | None] = relationship("ArchitectureSymbol", lazy="raise", viewonly=False)
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
        source_element_id / target_element_id: The two ends (never the same element). An end may belong to
            another owner the project can see (`visibility`). No cascade: the service refuses to delete an
            element a connection names, since the connection would lose an end.
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


class ArchitectureCollection(UUIDPKMixin, TimestampMixin, Base):
    """A named set of elements that an owner shares with projects and groups.

    A collection has no code and no record page of its own: it is an access grouping, not something a
    requirement or report names. Its owner is a project or the organisation (a CHECK keeps exactly one) and
    its members belong to that same owner.

    Attributes:
        project_id / organization_id: The owner; exactly one is set.
        name: Unique within the owner.
        description: Free text.
        creator_id: Who created it.
    """

    __tablename__ = "architecture_collections"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_architecture_collections_project_name"),
        UniqueConstraint("organization_id", "name", name="uq_architecture_collections_org_name"),
        CheckConstraint("(project_id IS NULL) <> (organization_id IS NULL)", name="ck_architecture_collections_one_owner"),
    )

    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    creator_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))


class ArchitectureCollectionMember(UUIDPKMixin, TimestampMixin, Base):
    """An element in a collection. Its children follow it (the nearest member ancestor decides), so only the
    top of a subtree is listed.

    Attributes:
        collection_id: The collection; deleting it removes its members.
        element_id: The element, which the service keeps in the collection's owner; deleting the element removes
            the membership.
    """

    __tablename__ = "architecture_collection_members"
    __table_args__ = (UniqueConstraint("collection_id", "element_id", name="uq_architecture_collection_members"),)

    collection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("architecture_collections.id", ondelete="CASCADE"), index=True
    )
    element_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("architecture_elements.id", ondelete="CASCADE"), index=True
    )


class ArchitectureCollectionGrant(UUIDPKMixin, TimestampMixin, Base):
    """Access to a collection for one project or one group of the collection owner's organisation.

    Exactly one target is set: a project (with `include_descendants`, resolved at read time so a child project
    added later is covered), or a group (`group_type` is `org_group` or `project_group`). The group has no
    foreign key (see `models.principal`); `PrincipalReference` blocks deleting a group a grant names.

    Attributes:
        collection_id: The collection; deleting it removes its grants.
        project_id: The granted project, or `None` for a group grant.
        group_type / group_id: The granted group, or `None` for a project grant.
        include_descendants: For a project grant, whether every child project (now or later) is included.
        created_by: Who granted it.
    """

    __tablename__ = "architecture_collection_grants"
    __table_args__ = (
        UniqueConstraint("collection_id", "project_id", name="uq_architecture_collection_grants_project"),
        UniqueConstraint("collection_id", "group_type", "group_id", name="uq_architecture_collection_grants_group"),
        CheckConstraint("(project_id IS NULL) <> (group_id IS NULL)", name="ck_architecture_collection_grants_one_target"),
        CheckConstraint("project_id IS NOT NULL OR NOT include_descendants", name="ck_architecture_collection_grants_descendants"),
        CheckConstraint("group_type IS NULL OR group_type IN ('org_group', 'project_group')", name="ck_architecture_collection_grants_group_type"),
        principal_check_constraint("group", nullable=True),
    )

    collection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("architecture_collections.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    group_type: Mapped[str | None] = principal_type_column(nullable=True)
    group_id: Mapped[uuid.UUID | None] = principal_id_column(nullable=True)
    include_descendants: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))


class ArchitectureDiagram(UUIDPKMixin, TimestampMixin, Base):
    """A saved view over the project's model: which elements are drawn where, and how connections are shown.

    A diagram stores placements, notes and toggles only; the elements and connections it draws are the model's, so
    deleting a diagram loses nothing from the model. Its `version` is advanced by every change to the diagram or to
    its placements, notes and toggles, so an editor holding a stale copy is told before it overwrites.

    Attributes:
        project_id: The owning project.
        unique_code: Project-scoped identifier (`DGM-001`).
        name / purpose: Display name and what the view is for.
        scope_element_id: The element the diagram shows the inside of, or `None` for the system context (the
            root elements). `SET NULL` when the element is deleted.
        connection_detail: When false the diagram draws plain lines (no type, protocol or port labels) and
            parallel lines collapse into one; when true connections are typed and labelled.
        status: A `RecordStatus` value.
        version: Optimistic counter.
        creator_id / is_archived / archived_at / archived_by: As for `ArchitectureElement`.
    """

    __tablename__ = "architecture_diagrams"
    __table_args__ = (UniqueConstraint("project_id", "unique_code", name="uq_architecture_diagrams_project_unique_code"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    unique_code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200))
    purpose: Mapped[str] = mapped_column(Text, default="")
    scope_element_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("architecture_elements.id", ondelete="SET NULL"), nullable=True, index=True
    )
    connection_detail: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    version: Mapped[int] = mapped_column(Integer, default=1)
    creator_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)


class ArchitectureDiagramPlacement(UUIDPKMixin, TimestampMixin, Base):
    """An element drawn on a diagram, with its box.

    Attributes:
        diagram_id: The diagram; deleting it removes its placements.
        element_id: The element (the diagram's project's own, or one another owner shares with it). Deleting the
            element removes the placement; deleting the placement never touches the element.
        x / y / width / height: The box in diagram units.
        collapsed: Whether the box is drawn as one block (its placed descendants are not nested inside it). Carried
            for the editor; the resolver does not read it.
    """

    __tablename__ = "architecture_diagram_placements"
    __table_args__ = (UniqueConstraint("diagram_id", "element_id", name="uq_architecture_diagram_placements"),)

    diagram_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("architecture_diagrams.id", ondelete="CASCADE"), index=True
    )
    element_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("architecture_elements.id", ondelete="CASCADE"), index=True
    )
    x: Mapped[float] = mapped_column(Float, default=0.0)
    y: Mapped[float] = mapped_column(Float, default=0.0)
    width: Mapped[float] = mapped_column(Float, default=160.0)
    height: Mapped[float] = mapped_column(Float, default=80.0)
    collapsed: Mapped[bool] = mapped_column(Boolean, default=False)


class ArchitectureDiagramNote(UUIDPKMixin, TimestampMixin, Base):
    """A plain-text note on a diagram: the only shape with no element behind it. Never rendered as markup.

    Attributes:
        diagram_id: The diagram; deleting it removes its notes.
        text: The note's text.
        x / y / width / height: The box in diagram units.
        sort_order: Order among the diagram's notes.
    """

    __tablename__ = "architecture_diagram_notes"

    diagram_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("architecture_diagrams.id", ondelete="CASCADE"), index=True
    )
    text: Mapped[str] = mapped_column(Text, default="")
    x: Mapped[float] = mapped_column(Float, default=0.0)
    y: Mapped[float] = mapped_column(Float, default=0.0)
    width: Mapped[float] = mapped_column(Float, default=160.0)
    height: Mapped[float] = mapped_column(Float, default=60.0)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class ArchitectureDiagramAnchor(UUIDPKMixin, TimestampMixin, Base):
    """Where a drawn line meets its boxes, when a person has chosen it (otherwise the nearest points are used).

    The anchor belongs to the *drawn line*, keyed by the pair of placed elements it joins, so a line that stands for
    several connections (merged or rolled up) has one anchor for all of them. An end left empty is chosen
    automatically: the point of its box nearest the other end.

    Attributes:
        diagram_id: The diagram; deleting it removes its anchors.
        source_element_id / target_element_id: The two placed elements; deleting either removes the anchor. Both must
            be placed on the diagram, which the layout save enforces and an unplace repeats.
        source_point / target_point: An `AttachPoint` value, or `None` for automatic (at least one is set).
    """

    __tablename__ = "architecture_diagram_anchors"
    __table_args__ = (
        UniqueConstraint("diagram_id", "source_element_id", "target_element_id", name="uq_architecture_diagram_anchors"),
        CheckConstraint("source_element_id <> target_element_id", name="ck_architecture_diagram_anchors_distinct"),
        CheckConstraint(
            "source_point IS NOT NULL OR target_point IS NOT NULL", name="ck_architecture_diagram_anchors_something_set",
        ),
    )

    diagram_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("architecture_diagrams.id", ondelete="CASCADE"), index=True
    )
    source_element_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("architecture_elements.id", ondelete="CASCADE"), index=True
    )
    target_element_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("architecture_elements.id", ondelete="CASCADE"), index=True
    )
    source_point: Mapped[str | None] = mapped_column(String(16), nullable=True)
    target_point: Mapped[str | None] = mapped_column(String(16), nullable=True)


class ArchitectureDiagramToggle(UUIDPKMixin, TimestampMixin, Base):
    """A named switch on a diagram (for example "Security devices"): when off, its members are hidden.

    Membership is the union of the manual members (`ArchitectureDiagramToggleMember`) and the elements and
    connections the `rule` matches.

    Attributes:
        diagram_id: The diagram; deleting it removes its toggles.
        name: Unique within the diagram.
        default_on: The state a report or export uses unless a call names the states.
        rule: `{"element_type_ids", "domains", "connection_type_ids", "tags"}`, each a list (all optional). It names
            vocabulary rows, domains and tag names, never a record, so it travels in a bundle without references.
        sort_order: Order among the diagram's toggles.
    """

    __tablename__ = "architecture_diagram_toggles"
    __table_args__ = (UniqueConstraint("diagram_id", "name", name="uq_architecture_diagram_toggles_name"),)

    diagram_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("architecture_diagrams.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    default_on: Mapped[bool] = mapped_column(Boolean, default=True)
    rule: Mapped[dict] = mapped_column(JSONB, default=dict)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class ArchitectureDiagramToggleMember(UUIDPKMixin, TimestampMixin, Base):
    """An element or a connection a toggle names by hand; exactly one of the two ids is set.

    Attributes:
        toggle_id: The toggle; deleting it removes its members.
        element_id / connection_id: The member; deleting the record removes the membership.
    """

    __tablename__ = "architecture_diagram_toggle_members"
    __table_args__ = (
        CheckConstraint("(element_id IS NULL) <> (connection_id IS NULL)", name="ck_architecture_diagram_toggle_members_one"),
        UniqueConstraint("toggle_id", "element_id", name="uq_architecture_diagram_toggle_members_element"),
        UniqueConstraint("toggle_id", "connection_id", name="uq_architecture_diagram_toggle_members_connection"),
    )

    toggle_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("architecture_diagram_toggles.id", ondelete="CASCADE"), index=True
    )
    element_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("architecture_elements.id", ondelete="CASCADE"), nullable=True, index=True
    )
    connection_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("architecture_connections.id", ondelete="CASCADE"), nullable=True, index=True
    )
