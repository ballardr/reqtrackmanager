"""
Module: models.generated_report

Provenance of a custom report run: one row per run of a report layout, recording what was run, for
whom, over what, so a report can be traced back to the layout version and data it came from and is
never a second, unattributed source of truth.

Responsibilities:
- `GeneratedReport`: the layout (id, name, version, tree hash), the caller, the UTC time, the engine
  version, the output format, the run's parameters and scope, the widgets used, record counts per
  type and a digest of the records read.

Design decisions:
- **A provenance row, not an output store.** No generated file is kept for a synchronous run; only
  its description. Stored output for asynchronous runs is a later addition to this table.
- **The layout is named, not linked.** `layout_id` has no foreign key and the name and tree hash are
  copied, so the row still says what was run after the layout (and its versions) is deleted. The
  organisation foreign key cascades, so deleting the organisation removes its provenance; the project
  key is `SET NULL` because `scope_project_ids` already names every project covered.
- **Counts and a digest, not record lists.** `source_digest` is a SHA-256 over every record read
  (type, id, last-change time, which for a versioned record is its current version's time), so a later
  run can tell whether the source data changed, without storing up to 200,000 identifiers per run.
- Contains no record content, layout text or cell value: only identifiers, counts and keys.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import UUIDPKMixin, utcnow

SCOPE_PROJECT = "project"
SCOPE_ORGANIZATION = "organization"


class GeneratedReport(UUIDPKMixin, Base):
    """One run of a report layout.

    Attributes:
        organization_id: The organisation the run belongs to.
        project_id: The project a project-level run was for; `None` for an organisation-wide run or once
            that project is deleted.
        scope: `project` or `organization`.
        layout_id: The layout run (no foreign key; see the module docstring).
        layout_name: The layout's name when it ran.
        layout_version: The layout version that ran.
        tree_hash: SHA-256 of that version's tree.
        requested_by: The caller, `None` once that user is deleted.
        created_at: When the run started (UTC).
        format: The output format requested (`json`, `pdf`, `docx`, `csv`).
        engine_version: The layout engine's version (changes when evaluation semantics change).
        params: Run parameters: `report_template_id`, `include_children`, `requested_project_ids`.
        scope_project_ids: The projects the run covered.
        widgets: The widgets the layout embedded (keys), `[]` until layouts can embed widgets.
        record_counts: Records read, by artefact type.
        stats: `blocks`, `rows`, `hidden`, `unavailable`, `warnings`, `duration_ms`.
        source_digest: SHA-256 hex over the records read (see the module docstring).
    """

    __tablename__ = "generated_reports"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), index=True, nullable=True
    )
    scope: Mapped[str] = mapped_column(String(20))
    layout_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    layout_name: Mapped[str] = mapped_column(String(200))
    layout_version: Mapped[int] = mapped_column(Integer)
    tree_hash: Mapped[str] = mapped_column(String(64))
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    format: Mapped[str] = mapped_column(String(10))
    engine_version: Mapped[str] = mapped_column(String(20))
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    scope_project_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    widgets: Mapped[list[str]] = mapped_column(JSONB, default=list)
    record_counts: Mapped[dict[str, int]] = mapped_column(JSONB, default=dict)
    stats: Mapped[dict[str, int]] = mapped_column(JSONB, default=dict)
    source_digest: Mapped[str] = mapped_column(String(64))
