"""
Module: modules.architecture.models

The two vocabularies every architecture record is typed by:

- `ArchitectureElementType` — what an element is (System, Service, Board, ...).
- `ArchitectureConnectionType` — what an interface is (REST API, SPI, Power, ...).

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

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, UUIDPKMixin


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
