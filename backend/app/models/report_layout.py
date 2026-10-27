"""
Module: models.report_layout

Custom report layouts: a person-authored tree of blocks that the report engine evaluates into a
document or a set of tables (`services.report_layout_tree`, `services.report_layout_eval`).

Responsibilities:
- `ReportLayout`: the named, owned definition (organisation- or project-level) and a pointer to its
  latest version.
- `ReportLayoutVersion`: one immutable saved tree. Editing a layout appends a version; a run pins one.

Design decisions:
- A layout is configuration, not an artefact type: no `PREFIX-nnn` code, not linkable, not searched.
- `project_id IS NULL` is an organisation-level layout. Both ids are real foreign keys with
  `ON DELETE CASCADE`, so deleting the owner removes its layouts and versions with no cleanup code.
- The tree is stored as the author wrote it (JSONB, `schema_version` inside) plus a SHA-256 of its
  canonical JSON, so an unchanged save is detected and a run can record exactly what it used.
- A version row is never updated; an ORM-level guard refuses it so a later change cannot rewrite
  history that a provenance row points at.
- Name uniqueness is per owner (two partial unique indexes, as for link types).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, event, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, UUIDPKMixin, utcnow

FAMILY_DOCUMENT = "document"
FAMILY_TABLE = "table"
LAYOUT_FAMILIES: tuple[str, ...] = (FAMILY_DOCUMENT, FAMILY_TABLE)


class ReportLayout(UUIDPKMixin, TimestampMixin, Base):
    """A named report layout owned by an organisation or one of its projects.

    Attributes:
        organization_id: Owning organisation (always set).
        project_id: The owning project, or `None` for an organisation-level layout.
        name: Display name, unique within the owner (case-insensitively, checked by the service).
        description: What the layout reports.
        family: `document` (PDF, DOCX, ODT, HTML ...) or `table` (CSV, XLSX, ODS ...); fixed at creation.
        current_version: The latest `ReportLayoutVersion.version`.
        created_by: The author, `None` once that user is deleted.
    """

    __tablename__ = "report_layouts"
    __table_args__ = (
        Index(
            "uq_report_layouts_org_name", "organization_id", "name", unique=True,
            postgresql_where=text("project_id IS NULL"),
        ),
        Index(
            "uq_report_layouts_project_name", "project_id", "name", unique=True,
            postgresql_where=text("project_id IS NOT NULL"),
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=True
    )
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    family: Mapped[str] = mapped_column(String(20))
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class ReportLayoutVersion(UUIDPKMixin, Base):
    """One immutable saved version of a layout.

    Attributes:
        layout_id: The layout.
        version: 1, 2, 3 ... within the layout.
        schema_version: The tree vocabulary version the tree was written in.
        tree: The layout tree (`services.report_layout_tree`).
        tree_hash: SHA-256 hex of the canonical JSON of `tree`.
        comment: The author's note on this change.
        created_by: The author, `None` once that user is deleted.
        created_at: When saved (UTC).
    """

    __tablename__ = "report_layout_versions"
    __table_args__ = (UniqueConstraint("layout_id", "version", name="uq_report_layout_versions_layout_version"),)

    layout_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("report_layouts.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    schema_version: Mapped[int] = mapped_column(Integer)
    tree: Mapped[dict[str, Any]] = mapped_column(JSONB)
    tree_hash: Mapped[str] = mapped_column(String(64))
    comment: Mapped[str] = mapped_column(String(500), default="")
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


@event.listens_for(ReportLayoutVersion, "before_update")
def _refuse_version_update(mapper: Any, connection: Any, target: ReportLayoutVersion) -> None:
    """Refuses to update a saved version: history that a run's provenance points at must not change."""
    raise ValueError("A report layout version is immutable; save a new version instead.")
