"""
Module: schemas.record_tables

Response models for the record table routes (`routers.record_tables`): a record type's columns and the
preview or result of an import. Requests are a query string (export) and an uploaded CSV (import), so there
are no request bodies.
"""

from __future__ import annotations

from pydantic import BaseModel


class RecordColumnOut(BaseModel):
    """One column of a record type's table.

    Attributes:
        key: The CSV header.
        label: The name a person sees.
        kind: `text`, `enum`, `principal`, `date`, `number`, `bool`, `instant` or `list`.
        importable: Whether an import writes it (otherwise export-only).
        editable: Whether the bulk edit grid offers it.
        required: Whether a new record needs a value.
        sensitivity: `none`, `personal`, `contact` or `free_text_people`.
        included: Whether the policy lets it leave or enter the app (`false` for an excluded column).
        choices: The accepted cell texts when they are a closed list, else `null` (free text).
    """

    key: str
    label: str
    kind: str
    importable: bool
    editable: bool
    required: bool
    sensitivity: str
    included: bool
    choices: list[str] | None = None


class RecordColumnsOut(BaseModel):
    """A record type's table definition for the Export menu and the Import wizard.

    Attributes:
        label: The plural name of the type.
        columns: Every column, `code` first.
        omitted_sensitivity: Sensitivity tags whose columns the policy leaves out.
        omitted_reasons: Why each omitted tag is left out: `policy` (the organisation or server excludes it) or
            `permission` (the policy allows it but the caller lacks `export_personal_data`).
        importable: Whether the type can be imported at all.
        can_import: Whether the caller may import it (importable, and they may create or update the records).
        not_importable_reason: Why not, when it cannot.
        filter_params: The list filters an export understands, besides `tag`, `tag_mode` and `project_scope`.
        max_rows / max_bytes: The import caps.
    """

    label: str
    columns: list[RecordColumnOut]
    omitted_sensitivity: list[str]
    omitted_reasons: dict[str, str]
    importable: bool
    can_import: bool
    not_importable_reason: str | None
    filter_params: list[str]
    max_rows: int
    max_bytes: int


class ColumnChangeOut(BaseModel):
    """One cell an update changes: the exported value and the file's."""

    column: str
    label: str
    before: str
    after: str


class RowResultOut(BaseModel):
    """What happened (or, in a preview, would happen) to one row.

    Attributes:
        row: The line number in the file (the header is row 1).
        action: `create`, `update`, `unchanged` or `error`.
        code: The record's code (the file's, for an error).
        changes: For an update, the cells that change.
        message: For an error, what was wrong.
    """

    row: int
    action: str
    code: str
    changes: list[ColumnChangeOut]
    message: str


class ImportResultOut(BaseModel):
    """The preview or result of an import.

    Attributes:
        applied: `false` for a preview (nothing was written).
        created / updated / unchanged / failed: Row counts.
        rows: One entry per data row.
        ignored_columns: `{header: reason}` for file columns that were not used.
        omitted_sensitivity: Sensitivity tags whose columns the policy excluded.
        error_csv: The failed rows with an `error` column, ready to fix and upload again; empty without errors.
    """

    applied: bool
    created: int
    updated: int
    unchanged: int
    failed: int
    rows: list[RowResultOut]
    ignored_columns: dict[str, str]
    omitted_sensitivity: list[str]
    error_csv: str


class GridColumnOut(BaseModel):
    """One column of the bulk edit grid.

    Attributes:
        key / label / kind: As `RecordColumnOut`.
        editable: Whether the grid edits it (provider-editable, importable and a closed-value kind).
        required: Whether the cell may not be blank.
        choices: The accepted texts for an enum column, else `null`.
    """

    key: str
    label: str
    kind: str
    editable: bool
    required: bool
    choices: list[str] | None = None


class GridRowOut(BaseModel):
    """One record of the grid: its cells by column key, and why it cannot be edited when it cannot.

    Attributes:
        id: The record's id.
        code: Its code as an export writes it.
        cells: Cell text by column key.
        read_only: The reason the row is read-only, or `null`.
        locks: Why a single cell cannot be edited, by column key (only the locked cells).
        project_id: The project that owns the record (differs from the list's project for a related project's row),
            or `null` for a record the organisation owns.
    """

    id: str
    code: str
    cells: dict[str, str]
    read_only: str | None = None
    locks: dict[str, str] = {}
    project_id: str | None = None


class RecordGridOut(BaseModel):
    """A list prepared for the bulk edit grid.

    Attributes:
        label: The plural name of the type.
        columns: Every column the personal-data policy lets through, `code` excluded.
        rows: At most `max_rows` records.
        total: How many records the filters matched.
        truncated: Whether `total` exceeds the rows loaded.
        max_rows: The row cap.
        can_edit: Whether the caller may update this type's records and it has an editable column.
        omitted_sensitivity: Sensitivity tags whose columns the policy left out.
    """

    label: str
    columns: list[GridColumnOut]
    rows: list[GridRowOut]
    total: int
    truncated: bool
    max_rows: int
    can_edit: bool
    omitted_sensitivity: list[str]


class GridRowUpdate(BaseModel):
    """The cells of one grid row to save.

    Attributes:
        cells: The new text by column key (only the cells that changed).
        expected: The text each of those cells had when the grid loaded it, so a cell changed since by someone
            else is refused instead of overwritten.
    """

    cells: dict[str, str]
    expected: dict[str, str] = {}
