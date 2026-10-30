"""
Module: models.report_snippet

Author-saved report snippets: a named fragment of a layout (its blocks and the page styles and variables they use) that
an author keeps at organisation or project level and inserts into other layouts (`services.report_snippet_store`).

Responsibilities:
- `SavedReportSnippet`: one saved fragment and who owns it.

Design decisions:
- A saved snippet is configuration, not an artefact type: no `PREFIX-nnn` code, not linkable, not searched.
- The fragment is stored as the author saved it and is copied into a layout on insert; nothing links back, so editing or
  deleting a snippet never changes a layout. It has no versions: changing the blocks means saving the selection again.
- `project_id IS NULL` is an organisation-level snippet. Both ids are real foreign keys with `ON DELETE CASCADE`, so
  deleting the owner removes its snippets with no cleanup code.
- Name uniqueness is per owner (two partial unique indexes, as for layouts and packs).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, UUIDPKMixin


class SavedReportSnippet(UUIDPKMixin, TimestampMixin, Base):
    """A report snippet saved by an author for an organisation or one of its projects.

    Attributes:
        organization_id: Owning organisation (always set).
        project_id: The owning project, or `None` for an organisation-level snippet.
        name: Display name, unique within the owner (case-insensitively, checked by the service).
        description: One sentence about what it adds.
        category: The group the picker lists it under.
        family: `document` or `table`, the layout family it can be inserted into.
        blocks: The blocks inserted (a list of block objects, valid against the block schemas).
        root: Root-level things the blocks use, `{"page_styles": [...], "variables": [...]}` (either may be absent).
        created_by: The author, `None` once that user is deleted.
    """

    __tablename__ = "report_snippets"
    __table_args__ = (
        Index(
            "uq_report_snippets_org_name", "organization_id", "name", unique=True,
            postgresql_where=text("project_id IS NULL"),
        ),
        Index(
            "uq_report_snippets_project_name", "project_id", "name", unique=True,
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
    category: Mapped[str] = mapped_column(String(60))
    family: Mapped[str] = mapped_column(String(20))
    blocks: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    root: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
