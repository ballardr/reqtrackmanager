"""
Module: models.report_folder

A folder of the Reports picker that an organisation or project has created, so it exists before any report is filed in it.

Responsibilities:
- `ReportFolder`: one row per (scope, path). The path is a tidied folder path (`services.report_folders`).

Design decisions:
- A folder is still only a label on a layout, a pack or a placement; this table only records the folders a person added
  (a folder in use needs no row). The picker's tree is the union of both.
- `project_id IS NULL` is the organisation's tier. Both ids are real foreign keys with `ON DELETE CASCADE`.
- Uniqueness is per owner and case-insensitive (two partial unique indexes on the lower-cased path).
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, UUIDPKMixin


class ReportFolder(UUIDPKMixin, TimestampMixin, Base):
    """A folder an organisation or project added to its Reports picker.

    Attributes:
        organization_id: Owning organisation (always set).
        project_id: The owning project, or `None` for the organisation's tier.
        path: The folder path (`Handover/Quarterly`, one to three levels).
        created_by: Who added it, `None` once that user is deleted.
    """

    __tablename__ = "report_folders"
    __table_args__ = (
        Index(
            "uq_report_folders_org_path", "organization_id", text("lower(path)"), unique=True,
            postgresql_where=text("project_id IS NULL"),
        ),
        Index(
            "uq_report_folders_project_path", "project_id", text("lower(path)"), unique=True,
            postgresql_where=text("project_id IS NOT NULL"),
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=True
    )
    path: Mapped[str] = mapped_column(String(120))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
