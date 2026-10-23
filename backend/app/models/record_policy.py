"""
Module: models.record_policy

The personal-data policy for record-table export and import: which sensitivity tags
(`app.modules.registry.RECORD_SENSITIVITY_TAGS`) may leave or enter the application through a file.

Design decisions:
- Two explicit-override-only tables, like `ServerModuleDefault` / `OrganizationModuleEnablement`: no
  server row means the tag is **excluded** (the secure default on a fresh install), no organisation row
  means "follow the server". Nothing is pre-created, so a later server change reaches every organisation
  that never overrode the tag.
- `tag` is a plain string validated by `services.record_policy` against the closed core vocabulary, not a
  database enum, so adding a tag is a code change in one place.
- Rows hold only the allow/deny decision and who set it, never any exported data.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin


class ServerRecordSensitivityDefault(TimestampMixin, Base):
    """The deployment-wide decision for one sensitivity tag.

    Attributes:
        tag: A `RECORD_SENSITIVITY_TAGS` value.
        allowed: Whether columns with this tag may be exported and imported by default.
        updated_by: The server administrator who last set it.
    """

    __tablename__ = "server_record_sensitivity_defaults"

    tag: Mapped[str] = mapped_column(String(40), primary_key=True)
    allowed: Mapped[bool] = mapped_column(Boolean)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)


class OrganizationRecordSensitivityOverride(TimestampMixin, Base):
    """One organisation's decision for one sensitivity tag, overriding the server default.

    Attributes:
        organization_id: The organisation.
        tag: A `RECORD_SENSITIVITY_TAGS` value.
        allowed: Whether columns with this tag may be exported and imported in this organisation.
        updated_by: The organisation administrator who last set it.
    """

    __tablename__ = "organization_record_sensitivity_overrides"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    tag: Mapped[str] = mapped_column(String(40), primary_key=True)
    allowed: Mapped[bool] = mapped_column(Boolean)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
