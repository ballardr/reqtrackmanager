"""
Module: services.record_list_report

The **Record list** report: the table of any record type that has a `RecordTableProvider`, as an on-screen
report, PDF, Word or CSV, so a person can produce "all Pain Points" from the Reports page without hunting for a
list page, and a list page's Export menu can offer the same PDF and Word with its own filters.

Responsibilities:
- Turn a `RecordTable` (`services.record_tables.build_table`) into a `ReportResult`: the provider's visible
  column labels, the filtered rows, a note naming the scope, the filters applied and any columns the
  personal-data policy left out, and per-cell tones for the columns that colour their cells on screen.
- List the record types a caller can run it for (`available_types`) and describe the report to the catalogue
  (`catalogue_entry`), since it is not a module's report and so is not in `ModuleDefinition.reports`.

Design decisions:
- One report with a `record_type` parameter, not one per type: the catalogue and the MCP tool stay one entry each
  while every type that gains a provider gains the report with no further code.
- The rows, the columns and the access rule are the export's, produced by the same functions
  (`build_table`, `resolve_export_columns`, `require_view`), so the report can never show a column or a record
  the CSV export would not; the CSV format of the report is the export's import file, byte for byte.
- A file (PDF, Word, CSV) is an export and audited as one (`records_exported`, counts and keys only); the
  on-screen run is a view of what the list shows and is not.
- Large documents are refused rather than laid out (`MAX_DOCUMENT_ROWS`): a PDF or Word of many thousands of rows
  holds a worker for a long time and cannot be read; the CSV has no such limit.

Dependencies: `services.record_tables` (the table), `services.report_framework` (result shapes and renderers),
`modules.registry` (the providers).
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.user import User
from app.modules.registry import artefact_type_enabled_for_project, get_record_table_providers
from app.services.link_nesting import ProjectRelation, related_projects
from app.services.permissions import encode_permission
from app.services.rbac import get_effective_permissions, permission_satisfied
from app.services.record_tables import RecordTable
from app.services.report_framework import (
    REPORT_FORMATS,
    ReportCatalogueEntryOut,
    ReportMetric,
    ReportParamOut,
    ReportResult,
    ReportSection,
)

REPORT_KEY = "record-list"
REPORT_TITLE = "Record list"
#: The catalogue groups a report under its module; this one belongs to the platform, not a module.
PLATFORM_KEY = "platform"
PLATFORM_NAME = "Platform"
#: The type the report opens on when the caller may list it.
PRIMARY_TYPE = "requirement"
#: Most rows a PDF or Word document is laid out for.
MAX_DOCUMENT_ROWS = 5000
PERSONAL_DATA_NOTE = (
    "Some columns holding personal data are left out, by your organisation's policy or because you do not hold "
    "the permission to export personal data."
)
SCOPE_CHOICE_LABELS = {
    "this": "This project only",
    "parents": "This project and its parents",
    "children": "This project and its children",
    "both": "This project, its parents and its children",
}


def available_types(db: Session, user: User, project: Project) -> list[tuple[str, str]]:
    """The record types `user` can run the report for in `project`, as `(type, plural label)` sorted by label.

    A type is available when it has a table, its module is on for the project and the person holds its `view`
    permission; the route enforces the same three, so the picker never offers a type that would fail.
    """
    held = get_effective_permissions(db, user.id, project_id=project.id)
    found = [
        (artefact_type, provider.label)
        for artefact_type, provider in get_record_table_providers().items()
        if artefact_type_enabled_for_project(db, artefact_type, project.id)
        and permission_satisfied(held, encode_permission(artefact_type, "view"))
    ]
    return sorted(found, key=lambda item: item[1].casefold())


def default_type(types: list[tuple[str, str]]) -> str:
    """The type the report opens on: Requirements (the product's primary list) when listable, else the first by label."""
    keys = [key for key, _ in types]
    return PRIMARY_TYPE if PRIMARY_TYPE in keys else keys[0]


def catalogue_entry(db: Session, user: User, project: Project) -> ReportCatalogueEntryOut | None:
    """The catalogue entry for the project, or `None` when the caller can list no record type.

    Args:
        db: Active session (read only).
        user: The caller.
        project: The project being reported on.

    Returns:
        An entry whose `record_type` parameter lists exactly the available types; `project_scope` is offered only
        when the project has a related project the person can open.
    """
    types = available_types(db, user, project)
    if not types:
        return None
    params = [
        ReportParamOut(
            name="record_type", type="string", default=default_type(types), choices=[key for key, _ in types],
            description="Which records to list.", label="Record type", choice_labels=dict(types),
        ),
    ]
    related, _ = related_projects(db, project, user.id, include_archived=False)
    if any(r.relation != ProjectRelation.SAME for r in related):
        params.append(ReportParamOut(
            name="project_scope", type="string", default="this", choices=list(SCOPE_CHOICE_LABELS),
            description="Also list the records of related projects you can open.", label="Projects",
            choice_labels=SCOPE_CHOICE_LABELS,
        ))
    params.append(ReportParamOut(
        name="tag", type="string", description="Only records carrying this tag (case-insensitive).", label="Tag",
    ))
    return ReportCatalogueEntryOut(
        module_key=PLATFORM_KEY, module_name=PLATFORM_NAME, key=REPORT_KEY, slug=REPORT_KEY, title=REPORT_TITLE,
        description="A table of any kind of record in this project: Requirements, Actions and every other record list.",
        scope="project", path=f"/api/v1/projects/{project.id}/reports/{REPORT_KEY}", formats=list(REPORT_FORMATS),
        supports_include_children=False, supports_project_filter=False, params=params,
    )


def collect(scope_label: str, label: str, table: RecordTable, *, scope_name: str = "this") -> ReportResult:
    """The report result for a built table.

    Args:
        scope_label: The name of what is reported on (the project's, or the organisation's for its own lists).
        label: The record type's plural label (`provider.label`), the report's title and table heading.
        table: The filtered table from `build_table`; its tones colour the cells of the columns that declare them.
        scope_name: The `project_scope` that was applied (`this`, `parents`, `children`, `both`).

    Returns:
        A one-section report; the first column of every row is the record's code.
    """
    keys = [key for key, _ in table.columns]
    tone_grid = [
        [table.tones[key].get(cell) if key in table.tones else None for key, cell in zip(keys, row, strict=True)]
        for row in table.rows
    ]
    notes = []
    if scope_name != "this":
        notes.append(f"Includes the records of related projects ({SCOPE_CHOICE_LABELS[scope_name].lower()}); the last column names the project.")
    if table.filter_keys:
        notes.append(f"Filtered by: {', '.join(table.filter_keys)}.")
    if table.omitted:
        notes.append(PERSONAL_DATA_NOTE)
    section = ReportSection(
        key="records", title=label, columns=[column_label for _, column_label in table.columns], rows=table.rows,
        tones=tone_grid if any(tone is not None for row in tone_grid for tone in row) else None,
    )
    return ReportResult(
        key=REPORT_KEY, title=label, scope_label=scope_label, generated_at=datetime.now(UTC), notes=notes,
        sections=[section], metrics=[ReportMetric("Records", len(table.rows))], eligible_projects=1,
    )

