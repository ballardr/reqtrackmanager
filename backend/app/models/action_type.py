"""
Module: models.action_type

Project-scoped requirement-action type definitions (e.g. "Review", "Test"),
the vocabulary a `RequirementAction.action_type_id` picks from.

Design decision: action types are project-scoped (`CustomFieldDefinition`'s pattern), not org-scoped,
as a plain per-project FK. A child project with none of its own falls back to its nearest ancestor's
(`services.project_hierarchy.resolve_effective_action_types`). See docs/decisions.md.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, UUIDPKMixin


class ActionTypeDefinition(UUIDPKMixin, TimestampMixin, Base):
    """A project-defined requirement-action type (e.g. "Review", "Test").

    Attributes:
        project_id: The owning project.
        name: Display name, unique within the project.
        sort_order: Display/picker order among the project's action types.
    """

    __tablename__ = "action_type_definitions"
    __table_args__ = (UniqueConstraint("project_id", "name"),)

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(100))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
