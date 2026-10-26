"""
Module: services.report_widget_run

Runs the report behind a widget (`services.report_widgets`) inside a layout run and turns one component of
its `ReportResult` into blocks of the layout's document.

Responsibilities:
- `collect_widget`: build the report's `ReportContext` from the layout run's and call the report's own
  collector, with the report's cell tones applied.
- `part_blocks`: the one component a widget names (a table, the headline figures, or the notes) as blocks, with
  its rows ordered by the widget's `sort` when it has one.
- `output_digest`: a SHA-256 of what the report produced, so the run's provenance digest covers widget data.

Design decisions:
- **The report's own collector and gates, nothing new.** The context carries the layout run's organisation,
  in-scope projects and root project, so a widget sees exactly the projects the layout run does and the
  collector applies the same per-project checks (`ReportContext.eligible`) it applies standalone. The
  module/sub-component gate is checked by the caller before this runs (`report_widgets.widget_available`).
- **A component, never prose.** A table widget gives the table and nothing else: the section's heading and
  its one-line note belong to the layout, which writes them for its own reader. The figures widget is one
  `Measure | Value` table (three columns with a `Group` column when the report groups them) and the notes
  widget the report's caveats, one `Note` each. A part with nothing in it gives no blocks, and the layout's
  `empty` text (if any) says so.
- **Sorting is by the table's column headings, on what the cell shows.** A report's cells are text, so the
  sort reads each one the way a person would: a number as a number, an ISO date as a date, anything else as text
  without regard to case, and an empty cell last in either direction. A rating such as "High" therefore sorts
  alphabetically, not by severity; a widget cannot know the order of a report's own scale. A heading the table
  does not have is a warning and is ignored, never an error.
- **Sections the screen hides are included.** `ReportSection.screen` only decides what the Reports page
  shows; a document has no screen, and the PDF of the report always carries them.
- Cell text is plain; the renderers escape it, as for every other table.

Dependencies: `services.report_framework` (context, result, tones), `services.report_widgets`,
`services.report_model` (blocks).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from app.services.report_framework import (
    ReportContext,
    ReportResult,
    apply_cell_tones,
    normalise_metrics,
)
from app.services.report_model import Block, Note, Table
from app.services.report_widgets import KIND_FIGURES, KIND_NOTES, WidgetInfo, WidgetPart


def widget_context(base: ReportContext, widget: WidgetInfo, params: dict[str, Any]) -> ReportContext:
    """The context the report's collector receives when run from a layout.

    Args:
        base: The layout run's context (organisation, projects in scope, root project, reference date).
        widget: The widget being run.
        params: The typed parameter values (`report_widgets.typed_params`).

    Returns:
        A context for the widget's module, over the same projects.
    """
    return ReportContext(
        module_key=widget.module_key, organization=base.organization, projects=list(base.projects),
        root_project=base.root_project, params=params, all_org_projects=False, today=base.today,
    )


def collect_widget(db: Session, widget: WidgetInfo, ctx: ReportContext) -> ReportResult:
    """Runs the report's collector and applies its declared cell tones.

    Args:
        db: Active session (read only).
        widget: The widget to run.
        ctx: Its context (`widget_context`).

    Returns:
        The collected report.

    Raises:
        HTTPException: A collector refused its parameters (for example an unknown group id); the caller
            decides how the layout shows that.
    """
    return apply_cell_tones(widget.definition.collector(db, ctx), widget.definition.cell_tones)


_NUMBER_CELL = re.compile(r"[+-]?\d[\d,]*(?:\.\d+)?%?")
_DATE_CELL = re.compile(r"\d{4}-\d{2}-\d{2}")


def cell_sort_key(text: str) -> tuple[int, Any] | None:
    """How a table cell compares: numbers first (as numbers), then ISO dates, then text (case-insensitively).

    Args:
        text: The cell as the report prints it.

    Returns:
        `(rank, value)`, or `None` for an empty cell, which sorts last in either direction.
    """
    cell = text.strip()
    if not cell:
        return None
    if _NUMBER_CELL.fullmatch(cell):
        return 0, float(cell.replace(",", "").rstrip("%"))
    if _DATE_CELL.fullmatch(cell):
        return 1, cell
    return 2, cell.casefold()


def sorted_order(columns: list[str], rows: list[list[str]], sort: list[dict[str, Any]], warn: Callable[[str], None]) -> list[int]:
    """The row order a widget's `sort` asks for (indexes into `rows`); stable, first key most significant.

    Args:
        columns: The table's headings.
        rows: Its rows.
        sort: The widget's `[{column, descending?}]`.
        warn: Told about a heading the table does not have (that key is skipped).

    Returns:
        Row indexes in the new order.
    """
    order = list(range(len(rows)))
    by_heading = {c.casefold(): i for i, c in enumerate(columns)}
    for item in reversed(sort):
        column = by_heading.get(str(item["column"]).casefold())
        if column is None:
            warn(f'The table has no column "{item["column"]}" to sort by, so that sort was ignored.')
            continue

        keyed = [(i, cell_sort_key(rows[i][column]) if column < len(rows[i]) else None) for i in order]
        present = sorted(((i, k) for i, k in keyed if k is not None), key=lambda pair: pair[1], reverse=bool(item.get("descending")))
        order = [i for i, _ in present] + [i for i, k in keyed if k is None]
    return order


def part_blocks(
    result: ReportResult, part: WidgetPart, sort: list[dict[str, Any]] | None = None, warn: Callable[[str], None] | None = None,
) -> list[Block]:
    """The blocks of the one component a widget names.

    Args:
        result: The collected report.
        part: The component: a declared table (by its section key), the headline figures, or the notes.
        sort: The widget's `sort` (`[{column, descending?}]`), applied to a table or the figures.
        warn: Told about a sort that cannot be applied (a missing heading, or the notes, which are not a table).

    Returns:
        A `Table` (with the cell tones, in the sorted order) for a table or the figures, one `Note` per caveat for the
        notes, and no blocks when the component is empty or the report did not produce that table.
    """
    say = warn or (lambda message: None)
    if part.kind == KIND_NOTES:
        if sort:
            say("The notes are not a table, so the sort was ignored.")
        return [Note(note) for note in result.notes]
    if part.kind == KIND_FIGURES:
        metrics = normalise_metrics(result.metrics)
        if not metrics:
            return []
        if any(m.group for m in metrics):
            columns, rows = ["Group", "Measure", "Value"], [[m.group or "", m.label, str(m.value)] for m in metrics]
        else:
            columns, rows = ["Measure", "Value"], [[m.label, str(m.value)] for m in metrics]
        tones = None
    else:
        section = next((s for s in result.sections if s.key == part.key), None)
        if section is None or not section.rows or not section.columns:
            return []
        columns, rows, tones = section.columns, section.rows, section.tones
    if sort:
        order = sorted_order(columns, rows, sort, say)
        rows = [rows[i] for i in order]
        tones = [tones[i] for i in order] if tones else None
    return [Table(columns, rows, compact=True, tones=tones)]


def output_digest(result: ReportResult) -> str:
    """SHA-256 hex of what a report produced (notes, figures and every section's cells).

    A report's rows are its source data as the report states it, so a change in the data changes this.
    """
    metrics = [[m.group, m.label, str(m.value)] for m in normalise_metrics(result.metrics)]
    sections = [[s.key, s.title, s.columns, s.rows, s.note] for s in result.sections]
    payload = json.dumps([result.notes, metrics, sections], sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


__all__ = ["cell_sort_key", "collect_widget", "output_digest", "part_blocks", "sorted_order", "widget_context"]
