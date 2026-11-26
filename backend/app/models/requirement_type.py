"""
Module: models.requirement_type

The requirement type vocabulary: an ordered list of kinds a requirement can be (Business, Stakeholder, Project by
default), in two tiers as `services.type_vocabulary.TypeVocabulary` defines them.

- `RequirementTypeDefinition`: the organisation's ordered list. `sort_order` is the name `services.ordering.move_ordered`
  expects.
- `ProjectRequirementType`: a project's view of that list: an override of one organisation entry, or an entry of its
  own (`org_type_id` null, named by `name_override`; a CHECK enforces it). A hidden organisation entry is a
  `ProjectDefinitionSuppression` tombstone.

Design decisions:
- The list order is for display. `rank` is the type's priority, kept apart from the order so a display change never
  alters traceability meaning: a lower number is higher priority (further upstream, 1 the top), equal ranks are peers
  and a null rank is unranked (sorts last, never compared). Which type must trace to which stays a traceability rule;
  rules may read the rank.
- A requirement version references a project type row (`RequirementVersion.project_type_id`), never an organisation
  entry directly; choosing an organisation entry creates a passthrough project row.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, UUIDPKMixin


class RequirementTypeDefinition(UUIDPKMixin, TimestampMixin, Base):
    """The organisation's list of requirement types.

    Attributes:
        organization_id: The owning organisation.
        name: Display name, unique per organisation.
        sort_order: Display and picker order.
        is_active: Soft-disable; an inactive type drops out of every project's list without being deleted.
        rank: Priority (lower is higher, 1 the top); null is unranked.
    """

    __tablename__ = "requirement_type_definitions"
    __table_args__ = (UniqueConstraint("organization_id", "name", name="uq_requirement_type_definitions_org_name"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(100))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ProjectRequirementType(UUIDPKMixin, TimestampMixin, Base):
    """A project's own view onto the requirement type list: an override of one organisation type (rename, reorder,
    disable, re-rank), or a type of its own (`org_type_id` null, named by `name_override`). A null `rank` on an override
    follows the organisation's."""

    __tablename__ = "project_requirement_types"
    __table_args__ = (
        UniqueConstraint("project_id", "org_type_id", name="uq_project_requirement_types_project_org_type"),
        CheckConstraint(
            "org_type_id IS NOT NULL OR name_override IS NOT NULL", name="ck_project_requirement_types_local_has_name"
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"))
    org_type_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("requirement_type_definitions.id", ondelete="SET NULL"), nullable=True
    )
    name_override: Mapped[str | None] = mapped_column(String(100), nullable=True)
    display_order_override: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
