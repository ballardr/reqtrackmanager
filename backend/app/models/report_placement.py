"""
Module: models.report_placement

Where a report appears in the Reports picker for one organisation or project: an override of its default folder and,
for a module report, whether it is shown at all.

Responsibilities:
- `ReportPlacement`: one row per (scope, report): the folder to file it under and/or hide it. A report is any entry of
  the report catalogue, named by a stable `report_key` (`services.report_placements`).

Design decisions:
- Configuration, like a layout: it changes what the picker lists, never what a person may run (access is checked on
  the run), so a hidden report is tidied away, not protected.
- `project_id IS NULL` is the organisation's tier. Both ids are real foreign keys with `ON DELETE CASCADE`, so deleting
  the owner removes its placements with no cleanup code. The key is text, not a foreign key, because a key names a
  module report, a layout or a pack; the services drop a row when the layout or pack goes.
- `folder` and `hidden` are each `NULL` for "no override here": a project row layered over its parents' and the
  organisation's, nearest first, per attribute (the nesting rule action types follow).
- Uniqueness is per owner (two partial unique indexes, as for layouts).
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, UUIDPKMixin


class ReportPlacement(UUIDPKMixin, TimestampMixin, Base):
    """An override of one report's folder and/or visibility in one scope's picker.

    Attributes:
        organization_id: Owning organisation (always set).
        project_id: The owning project, or `None` for the organisation's tier.
        report_key: Stable name of the report (`report:<module>.<key>`, `layout:<id>` or `pack:<id>`).
        folder: Folder path to file it under, `""` for the top level, `None` for no override.
        hidden: `True` to leave it out of the picker, `False` to show what a parent hid, `None` for no override.
        updated_by: Who last changed it, `None` once that user is deleted.
    """

    __tablename__ = "report_placements"
    __table_args__ = (
        Index(
            "uq_report_placements_org_key", "organization_id", "report_key", unique=True,
            postgresql_where=text("project_id IS NULL"),
        ),
        Index(
            "uq_report_placements_project_key", "project_id", "report_key", unique=True,
            postgresql_where=text("project_id IS NOT NULL"),
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=True
    )
    report_key: Mapped[str] = mapped_column(String(120))
    folder: Mapped[str | None] = mapped_column(String(120), nullable=True)
    hidden: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
