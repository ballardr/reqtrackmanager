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
- **A provenance row; output is stored only for a background run.** No generated file is kept for a
  synchronous run (`status` `completed`); only its description. A background run's row is also its job:
  `queued` -> `running` -> `ready` (the file is in object storage under `output_key`) or `failed`, and a
  `ready` row becomes `expired` when the retention passes (`services.report_run_jobs`), the file deleted and the
  row kept as provenance. The row holds the request (layout version, format, parameters) so the job can run
  later as the same person.
- **The layout is named, not linked.** `layout_id` has no foreign key and the name and tree hash are
  copied, so the row still says what was run after the layout (and its versions) is deleted. The
  organisation foreign key cascades, so deleting the organisation removes its provenance; the project
  key is `SET NULL` because `scope_project_ids` already names every project covered.
- **Versions for versioned records, a digest for all.** `record_versions` names the version of every
  versioned record in the report (`{type: {record id: version number}}`), bounded by
  `report_layout_eval.MAX_RECORDED_VERSIONS` (`record_versions_truncated` says when it was cut).
  `source_digest` is a SHA-256 over every record in the report (type, id, last-change time, which for a
  versioned record is its current version's time), so a later run can tell whether the data changed even
  when the list was cut.
- Contains no record content, layout text or cell value: only identifiers, counts and keys.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import UUIDPKMixin, utcnow

SCOPE_PROJECT = "project"
SCOPE_ORGANIZATION = "organization"

STATUS_COMPLETED = "completed"
STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_READY = "ready"
STATUS_FAILED = "failed"
STATUS_EXPIRED = "expired"


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
        widgets: Keys of the widgets that ran (`<module key>.<report slug>`, distinct, sorted); `[]` for a layout with none.
        record_counts: Records read, by artefact type.
        stats: `blocks`, `rows`, `hidden`, `unavailable`, `warnings`, `duration_ms`.
        source_digest: SHA-256 hex over the records in the report (see the module docstring).
        record_versions: `{type: {record id: version number}}` of the versioned records in the report.
        record_versions_truncated: Whether `record_versions` was cut at the bound (the digest still covers all).
        status: `completed` (a synchronous run), or a background run's `queued`, `running`, `ready`, `failed`, `expired`.
        started_at / finished_at: When a background run began and ended (UTC); `None` otherwise.
        expires_at: When a `ready` run's stored output is deleted (UTC).
        output_key / output_filename / output_size: The stored file's storage key, download name and size in bytes.
        error: Why a `failed` run failed, in words safe to show the requester (never record content).
        pack_run_id: Shared by the rows of one report pack run (one row per entry); `None` for a run of a single layout.
        report_key: `<module key>.<report key>` when the row records a module report run as a pack entry (then
            `layout_id` is a stable id derived from that key and `layout_version` is 0); `None` for a layout.
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
    record_versions: Mapped[dict[str, dict[str, int]]] = mapped_column(JSONB, default=dict, server_default="{}")
    record_versions_truncated: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    status: Mapped[str] = mapped_column(String(12), default=STATUS_COMPLETED, server_default=STATUS_COMPLETED, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    output_key: Mapped[str | None] = mapped_column(String(300), nullable=True)
    output_filename: Mapped[str | None] = mapped_column(String(300), nullable=True)
    output_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    pack_run_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True, index=True)
    report_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
