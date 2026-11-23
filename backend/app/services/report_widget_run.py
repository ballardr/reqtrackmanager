"""
Module: services.report_widget_run

Runs the report behind a widget (`report_widgets`) inside a layout run and turns one component of its `ReportResult`
into blocks of the layout's document.

Responsibilities:
- `collect_widget` (the report's `ReportContext` from the layout run's, the report's own collector, its cell tones);
  `part_blocks` (a table, the headline figures or the notes as blocks, rows ordered by the widget's `sort`);
  `output_digest` (SHA-256 so provenance covers widget data).

Design decisions:
- The report's own collector and gates: the context carries the layout run's organisation, projects and root project, so
  per-project checks (`ReportContext.eligible`) apply as standalone; the caller checks module availability first.
- A component, never prose: a table widget gives the table only; the figures widget is one `Measure | Value` table (with a
  `Group` column when grouped) and notes are one `Note` each. An empty part gives no blocks, so the layout's `empty` text applies.
- Sorting is by column heading on the displayed text: numbers as numbers, ISO dates as dates, other text case-insensitively,
  empty cells last in both directions, so "High" sorts alphabetically, not by severity. An unknown heading is a warning.
- A section with a `drawing` gives a full-width `Image` (a sort on it is ignored with a warning). Sections hidden on screen
  (`ReportSection.screen`) are still included. Cell text is plain and escaped by the renderers.

Dependencies: `report_framework`, `report_widgets`, `report_model`.
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
    apply_usual_widths,
    normalise_metrics,
)
from app.services.report_model import Block, Image, Note, Table
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
        viewer_id=base.viewer_id, record_order=widget.definition.record_order,
    )


def collect_widget(db: Session, widget: WidgetInfo, ctx: ReportContext) -> ReportResult:
    """Runs the report's collector and applies its declared cell tones and usual column widths.

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
    result = apply_cell_tones(widget.definition.collector(db, ctx), widget.definition.cell_tones)
    return apply_usual_widths(result, widget.definition.usual_widths)


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
        tones = usual = None
    else:
        section = next((s for s in result.sections if s.key == part.key), None)
        if section is not None and section.drawing:
            if sort:
                say("A drawing is not a table, so the sort was ignored.")
            return [Image(svg=section.drawing, alt=section.title, width=100, width_unit="percent")]
        if section is None or not section.rows or not section.columns:
            return []
        columns, rows, tones, usual = section.columns, section.rows, section.tones, section.usual_widths
    if sort:
        order = sorted_order(columns, rows, sort, say)
        rows = [rows[i] for i in order]
        tones = [tones[i] for i in order] if tones else None
    return [Table(columns, rows, compact=True, tones=tones, usual_widths=usual)]


def output_digest(result: ReportResult) -> str:
    """SHA-256 hex of what a report produced (notes, figures and every section's cells).

    A report's rows are its source data as the report states it, so a change in the data changes this.
    """
    metrics = [[m.group, m.label, str(m.value)] for m in normalise_metrics(result.metrics)]
    sections = [
        [s.key, s.title, s.columns, s.rows, s.note, hashlib.sha256(s.drawing.encode()).hexdigest() if s.drawing else ""]
        for s in result.sections
    ]
    payload = json.dumps([result.notes, metrics, sections], sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


__all__ = ["cell_sort_key", "collect_widget", "output_digest", "part_blocks", "sorted_order", "widget_context"]
