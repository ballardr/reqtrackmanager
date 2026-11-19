"""
Module: models.code_prefix

`OrganizationCodePrefix` and `ProjectCodePrefix`: the prefix an organisation, or one
project, uses for the codes of new records of one registered artefact type (`ADR-006`
where the built-in default is `DEC-006`).

Design decisions:
- A sparse override map, one row per `(owner, artefact_type)`: no row means "follow the
  next tier" (project, then its nearest ancestor project that sets one, then the
  organisation, then the type's built-in default; `services.code_prefixes`).
- `artefact_type` is a plain registrable string checked at the service layer against the
  registry's declared defaults, never a closed enum a module would have to hand-edit.
- A prefix only decides the code of records created afterwards. A stored `unique_code`
  never changes, and the counters (`models.sequence`) are untouched, so a number is
  never reused across a prefix change.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, UUIDPKMixin


class OrganizationCodePrefix(UUIDPKMixin, TimestampMixin, Base):
    """One organisation-level record code prefix override.

    Attributes:
        organization_id: The organisation that chose the prefix.
        artefact_type: The registered artefact type it applies to.
        prefix: 2 to 5 upper-case letters (`code_rules.record_prefix_error`).
    """

    __tablename__ = "organization_code_prefixes"
    __table_args__ = (
        UniqueConstraint("organization_id", "artefact_type", name="uq_organization_code_prefixes_org_type"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    artefact_type: Mapped[str] = mapped_column(String(40))
    prefix: Mapped[str] = mapped_column(String(5))


class ProjectCodePrefix(UUIDPKMixin, TimestampMixin, Base):
    """One project-level record code prefix override.

    Attributes:
        project_id: The project that chose the prefix; its nested projects follow it until they set their own.
        artefact_type: The registered artefact type it applies to.
        prefix: 2 to 5 upper-case letters (`code_rules.record_prefix_error`).
    """

    __tablename__ = "project_code_prefixes"
    __table_args__ = (UniqueConstraint("project_id", "artefact_type", name="uq_project_code_prefixes_project_type"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    artefact_type: Mapped[str] = mapped_column(String(40))
    prefix: Mapped[str] = mapped_column(String(5))
