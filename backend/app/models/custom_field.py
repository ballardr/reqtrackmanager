"""
Module: models.custom_field

Per-project customisable attribute definitions for requirements and change
requests (Pelion v2, C-C-01, C-C-02). The *values* for these fields are not
stored in a separate versioned table; they live in a `custom_fields` JSONB
column added directly to `RequirementVersion`/`ChangeRequestVersion`
(see models/requirement.py, models/change_request.py) so custom attribute
changes are captured by the exact same version-history/change-log mechanism
as the standard fields, rather than needing a second, parallel history model.
"""

from __future__ import annotations

import enum
import uuid
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, UUIDPKMixin, str_enum


class CustomFieldEntityKind(str, enum.Enum):
    """Which kind of entity a custom field definition applies to."""

    REQUIREMENT = "requirement"
    CHANGE_REQUEST = "change_request"


class CustomFieldType(str, enum.Enum):
    """Supported custom attribute types (C-C-02)."""

    SHORT_TEXT = "short_text"
    LONG_TEXT = "long_text"
    CHECKBOX = "checkbox"
    LIST = "list"


class CustomFieldDefinition(UUIDPKMixin, TimestampMixin, Base):
    """A project-scoped custom attribute definition (C-C-01).

    Attributes:
        options: For `CustomFieldType.LIST` fields, the list of selectable
            option strings; null/unused for other types.
    """

    __tablename__ = "custom_field_definitions"

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"))
    entity_kind: Mapped[CustomFieldEntityKind] = mapped_column(str_enum(CustomFieldEntityKind, 20))
    name: Mapped[str] = mapped_column(String(255))
    field_type: Mapped[CustomFieldType] = mapped_column(str_enum(CustomFieldType, 20))
    options: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    required: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
