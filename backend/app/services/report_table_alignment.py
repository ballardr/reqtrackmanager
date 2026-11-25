"""
Module: services.report_table_alignment

Tables with the same headings in one document share one set of column widths, so they read as one list.

Responsibilities:
- `column_needs`: what each column of a table needs (used by the evaluator and the PDF).
- `align_tables`: give every table of a group (same headings, same usable page width) the same relative widths, written
  as `Table.weights`, which every renderer honours.

Design decisions:
- The rule runs on the finished document and is idempotent, so the organisation-wide run applies it again after joining
  the projects' documents.
- A table already sized (`widths`, `col_widths_cm`, or `weights`) is never regrouped (the author wins); a group of one,
  an empty table and a one-column table are left alone. Groups also split by the page style's usable width.
- A module report's usual widths (`Table.usual_widths`) fix the columns they name and the rest share what is left, for a
  group or a lone table. A layout can turn alignment off (`ReportDocument.align_tables`), which also skips usual widths.
- Text is measured in the active PDF font; other formats use only the proportions.

Dependencies: `report_model`, `report_column_width`, `report_fonts`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from app.services.report_column_width import resolve_table_widths_cm
from app.services.report_fonts import text_width
from app.services.report_model import Block, PageStyleChange, ReportDocument, Table

#: Font size of a table cell in the PDF, in points (the measure's basis).
CELL_FONT_SIZE = 7.5
#: Most a cell's whole text is allowed to ask for, in points.
MAX_CELL_POINTS = 70.0
#: Most a single unbroken word is allowed to ask for, in points: a pasted unbroken string must not claim the page.
MAX_WORD_POINTS = 100.0
#: Cell padding added to every column's need, in points.
CELL_PADDING_POINTS = 14.0


def column_needs(columns: Sequence[str], rows: Sequence[Sequence[object]]) -> list[float]:
    """What each column needs in points: its longest unbreakable word (so a code stays on one line), or its longest cell if
    that asks for more, each capped, plus the cell padding.

    Args:
        columns: The table's headings.
        rows: The body rows (an image cell counts as its text, which is empty).

    Returns:
        One need per column.
    """
    needs = []
    for index, heading in enumerate(columns):
        cells = [str(row[index]) for row in rows if index < len(row)]
        words = max((text_width(word, CELL_FONT_SIZE, bold=True) for word in heading.split()), default=0.0)
        words = max([words, *(text_width(word, CELL_FONT_SIZE) for cell in cells for word in cell.split())])
        whole = max((text_width(cell, CELL_FONT_SIZE) for cell in cells), default=0.0)
        needs.append(max(min(words, MAX_WORD_POINTS), min(whole, MAX_CELL_POINTS)) + CELL_PADDING_POINTS)
    return needs


def _eligible(table: Table) -> bool:
    """Whether the rule may size `table`: nothing forced by the author or the engine, rows to measure, several columns."""
    if table.widths or table.col_widths_cm or (table.weights and not table.aligned):
        return False
    return bool(table.rows) and len(table.columns) > 1


def align_tables(document: ReportDocument) -> ReportDocument:
    """Gives the tables of each group the same column widths.

    Args:
        document: The evaluated document.

    Returns:
        `document` itself when the layout turned the alignment off or there is nothing to size (no group of two tables and no
        table with usual widths), else a copy whose sized tables carry `weights`.
    """
    if not document.align_tables:
        return document
    usable = document.style.usable_width_cm
    groups: dict[tuple[tuple[str, ...], float], list[tuple[int, Table]]] = {}
    for index, block in enumerate(document.blocks):
        if isinstance(block, PageStyleChange):
            usable = block.style.usable_width_cm
        elif isinstance(block, Table) and _eligible(block):
            groups.setdefault((tuple(block.columns), round(usable, 2)), []).append((index, block))
    blocks: list[Block] = list(document.blocks)
    changed = False
    for (columns, usable_cm), members in groups.items():
        specs = next((table.usual_widths for _, table in members if table.usual_widths), None)
        if len(members) < 2 and specs is None:
            continue
        measured = [column_needs(columns, table.rows) for _, table in members]
        needs = [max(column) for column in zip(*measured, strict=True)]
        weights = resolve_table_widths_cm(specs or [None] * len(columns), usable_cm, needs)
        for index, table in members:
            blocks[index] = replace(table, weights=weights, aligned=True)
        changed = True
    return replace(document, blocks=blocks) if changed else document
