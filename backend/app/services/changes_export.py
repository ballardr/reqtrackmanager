"""
Module: services.changes_export

The project History page as a file: the filtered timeline as CSV, PDF, Word, ODF or HTML.

Responsibilities:
- Turn the entries of `services.changes` into one report table (`build_history_result`) with the columns
  Time (UTC), Type, Event, Action, Record code, Record, Person.
- Apply the personal-data rule of the record exports: the Person column is a `personal` column, left out
  unless the organisation's policy and the caller's `export_personal_data` permission allow it
  (`services.record_policy.tag_decisions`), and the file says so in a note.
- Write the CSV (`history_csv`, formula-guarded like every export) and audit one export event with counts and
  filter keys only (`audit_history_export`).

Design decisions:
- The history is not a registered record type (an event is never authored or imported), so it has no
  `RecordTableProvider`, no Import and no `code` first column; this is the one list whose Export is its own
  route (docs/decisions.md). Every other rule of "Every Record List Exports" holds: filters respected, formula
  guard, personal data governed by the one policy, one audit event with no cell values.
- Times are UTC ISO 8601 instants (past instants), never converted on the server.
- A record is named by its code through `services.codes.display_code` (the project's own code bare unless the
  organisation enforces it), and by its title; a record the caller may not open has no code or title.

External dependencies: `services.changes`, `services.codes`, `services.record_policy`, `services.report_framework`.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.project import Project
from app.models.user import User
from app.modules.registry import get_artefact_type_label
from app.schemas.changes import ChangeEntryOut
from app.services.activity_kinds import KIND_LABELS
from app.services.audit import log_event
from app.services.codes import display_code, label_title
from app.services.record_policy import tag_decisions
from app.services.record_tables import write_cell
from app.services.report_framework import ReportMetric, ReportResult, ReportSection

REPORT_TITLE = "Project history"
#: Most entries one export holds; a larger result is refused and the caller narrows the filters.
MAX_EXPORT_ROWS = 50000
#: Most rows a PDF or Word document is laid out for (the CSV is not limited by this).
MAX_DOCUMENT_ROWS = 5000
PERSONAL_DATA_NOTE = (
    "The Person column is left out, by your organisation's policy or because you do not hold "
    "the permission to export personal data."
)
_COLUMNS = ["Time (UTC)", "Type", "Event", "Action", "Record code", "Record"]


def _humanise(key: str) -> str:
    """A stored key as words (`project_stage` -> `Project stage`)."""
    return key.replace("_", " ").capitalize()


def _record(entry: ChangeEntryOut, project: Project, organization: Organization | None) -> tuple[str, str]:
    """The code and title an entry names, or two empty strings for a record that cannot be named.

    Requirements and change requests carry both in `detail`; every other registered type carries a
    `record_label` (code and title) when the caller may see the record.
    """
    detail = entry.detail or {}
    enforced = bool(organization and organization.enforce_code_everywhere)
    if entry.entity_type == "requirement" and isinstance(detail.get("unique_code"), str):
        code = display_code(detail["unique_code"], project.code, own_project_code=project.code, enforced=enforced)
        return code, str(detail.get("name") or "")
    if entry.entity_type == "change_request" and isinstance(detail.get("unique_code"), str):
        code = display_code(detail["unique_code"], project.code, own_project_code=project.code, enforced=enforced)
        return code, str(detail.get("proposed_name") or "")
    if entry.record_label:
        first, _, rest = entry.record_label.partition(" ")
        if rest and label_title(entry.record_label) != entry.record_label:
            return display_code(first, project.code, own_project_code=project.code, enforced=enforced), rest
        return "", entry.record_label
    return "", ""


def _type_label(entity_type: str) -> str:
    """The name an entry shows for its type: the registered label, else the key as words."""
    return get_artefact_type_label(entity_type)


def build_history_result(
    db: Session, user: User, project: Project, entries: list[ChangeEntryOut], *, filter_keys: list[str],
) -> tuple[ReportResult, bool]:
    """The report for `entries`, and whether the Person column was included.

    Args:
        db: Active session (read only).
        user: The caller, whose export permission governs the Person column.
        project: The project the history belongs to.
        entries: The filtered timeline (already carrying actor names and record labels).
        filter_keys: The names of the filters applied (shown in a note; never their values).

    Returns:
        `(result, include_person)`.
    """
    organization = db.get(Organization, project.organization_id)
    include_person = tag_decisions(db, user, project.organization_id, project.id)["personal"].allowed
    columns = [*_COLUMNS, *(["Person"] if include_person else [])]
    rows: list[list[str]] = []
    for entry in entries:
        code, title = _record(entry, project, organization)
        row = [
            entry.timestamp.astimezone(UTC).isoformat().replace("+00:00", "Z"), _type_label(entry.entity_type),
            KIND_LABELS.get(entry.kind, KIND_LABELS["other"]), _humanise(entry.action), code, title,
        ]
        if include_person:
            row.append(entry.actor_display_name or "")
        rows.append(row)
    notes = []
    if filter_keys:
        notes.append(f"Filtered by: {', '.join(filter_keys)}.")
    if not include_person:
        notes.append(PERSONAL_DATA_NOTE)
    section = ReportSection(key="history", title=REPORT_TITLE, columns=columns, rows=rows)
    result = ReportResult(
        key="project-history", title=REPORT_TITLE, scope_label=project.name, generated_at=datetime.now(UTC),
        notes=notes, sections=[section], metrics=[ReportMetric("Events", len(rows))], eligible_projects=1,
    )
    return result, include_person


def history_csv(result: ReportResult) -> bytes:
    """The table as UTF-8 CSV with a byte-order mark, every cell formula-guarded."""
    section = result.sections[0]
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([write_cell(column) for column in section.columns])
    for row in section.rows:
        writer.writerow([write_cell(cell) for cell in row])
    return b"\xef\xbb\xbf" + buffer.getvalue().encode("utf-8")


def audit_history_export(
    db: Session, user: User, project: Project, *, fmt: str, rows: int, columns: int, filter_keys: list[str],
    omitted: bool,
) -> None:
    """Records one `records_exported` event (counts and filter keys only) and commits it."""
    detail: dict[str, Any] = {
        "record_type": "project_history", "format": fmt, "rows": rows, "columns": columns, "filters": filter_keys,
        "omitted_sensitivity": ["personal"] if omitted else [],
    }
    log_event(
        db, action="records_exported", actor_id=user.id, entity_type="project", entity_id=project.id,
        project_id=project.id, organization_id=project.organization_id, detail=detail,
    )
    db.commit()
