"""
Module: services.report_grid

The custom table (`grid` block): its closed vocabularies and limits, the one span check every caller shares, and the
placement of finished cells that the four document renderers read.

Responsibilities:
- Name the limits (`MAX_GRID_COLUMNS`, `MAX_GRID_ROWS`, `MAX_CELL_CHARS`, row height bounds) and the closed vocabularies
  (alignment, vertical alignment, borders) the tree validator, the text view and the renderers agree on.
- `place_spans`: place cells, given only each cell's `(colspan, rowspan)`, and report every merge problem with the row
  and cell it concerns. The tree validator calls it on the saved tree, `place_grid` on the finished model, so the rule
  lives once.
- `place_grid`: a finished `Grid` as `PlacedCell`s (row, column, cell) in reading order; covered positions are the ones
  no cell starts at.
- `border_edges`: which edges of a cell are drawn for a `borders` setting, so PDF, Word, OpenDocument and the preview
  draw the same lines.
- `cell_paragraphs`: the paragraphs of a cell from the blocks its Markdown text reads as (a heading is bold, a list item
  carries its bullet or number, a line break starts a new paragraph).
- `low_contrast`: whether a cell's text and fill fall below the readable ratio (a warning, never an error).

Design decisions:
- A merged region is stored on its top-left cell (`colspan`, `rowspan`) and the covered positions are omitted from the
  row, as in HTML: a covered cell cannot hold text by mistake, and the check is one pass.
- Header rows are the leading rows only, and a merge may not cross from the header into the body (ODF, ReportLab and
  Word each repeat a leading group of rows).

Dependencies: `services.branding` (contrast ratio), `services.report_model` (the `Grid` model).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

from app.services.branding import contrast_ratio
from app.services.report_model import (
    Block,
    BulletList,
    Equation,
    Grid,
    GridCell,
    Heading,
    MathText,
    NumberedList,
    Paragraph,
    Styled,
    text_runs,
)

MAX_GRID_COLUMNS = 20
MAX_GRID_ROWS = 200
#: Longest text of one cell, in characters.
MAX_CELL_CHARS = 2000
#: Bounds of a row's minimum height, in mm (3 mm to 20 cm).
GRID_ROW_HEIGHT_MM = (3.0, 200.0)
GRID_HEIGHT_UNITS = ("cm", "mm")
GRID_ALIGNMENTS = ("left", "center", "right", "justify")
GRID_VALIGNMENTS = ("top", "middle", "bottom")
GRID_BORDERS = ("all", "outer", "horizontal", "none")
#: The border colour when the grid sets none, and the readable contrast between a cell's text and fill.
DEFAULT_BORDER_COLOUR = "#999999"
MIN_CONTRAST = 4.5


@dataclass(frozen=True)
class SpanProblem:
    """One merge problem: `row` and `cell` are 0-based; `cell` is `None` for a whole row."""

    row: int
    cell: int | None
    message: str


def place_spans(columns: int, rows: Sequence[Sequence[tuple[int, int]]], header_rows: int) -> tuple[list[list[int]], list[SpanProblem]]:
    """Places each row's cells left to right, skipping positions a merge from above covers.

    Args:
        columns: The number of columns.
        rows: Per row, the `(colspan, rowspan)` of each cell it lists (covered positions are not listed).
        header_rows: How many leading rows repeat; a merge may not cross from them into the body.

    Returns:
        The starting column of every cell, per row (a cell that could not be placed gets `-1`), and every problem: a span
        below 1, a merge past the grid or into the body from the header rows, a merge that overlaps another cell, a row with
        more or fewer cells than the columns need.
    """
    count = len(rows)
    taken = [[False] * columns for _ in range(count)]
    starts: list[list[int]] = []
    problems: list[SpanProblem] = []
    for r, row in enumerate(rows):
        c = 0
        here: list[int] = []
        for i, (colspan, rowspan) in enumerate(row):
            while c < columns and taken[r][c]:
                c += 1
            if c >= columns:
                problems.append(SpanProblem(r, i, "There are more cells in this row than columns."))
                here.append(-1)
                continue
            if colspan < 1 or rowspan < 1:
                problems.append(SpanProblem(r, i, "A merge spans at least one column and one row."))
                here.append(-1)
                c += 1
                continue
            if c + colspan > columns or r + rowspan > count:
                problems.append(SpanProblem(r, i, "This merge runs past the edge of the table."))
                here.append(-1)
                c += 1
                continue
            if r < header_rows < r + rowspan:
                problems.append(SpanProblem(r, i, "A merge cannot cross from the header rows into the body."))
            clash = any(taken[rr][cc] for rr in range(r, r + rowspan) for cc in range(c, c + colspan))
            if clash:
                problems.append(SpanProblem(r, i, "This merge overlaps another cell."))
            else:
                for rr in range(r, r + rowspan):
                    for cc in range(c, c + colspan):
                        taken[rr][cc] = True
            here.append(c)
            c += colspan
        if any(not taken[r][cc] for cc in range(columns)) and not any(p.row == r and p.cell is not None for p in problems):
            problems.append(SpanProblem(r, None, "This row has fewer cells than the table has columns."))
        starts.append(here)
    return starts, problems


@dataclass(frozen=True)
class PlacedCell:
    """A finished cell at its position; `last_row` / `last_col` are the far corner of its merge."""

    row: int
    col: int
    cell: GridCell

    @property
    def last_row(self) -> int:
        return self.row + self.cell.rowspan - 1

    @property
    def last_col(self) -> int:
        return self.col + self.cell.colspan - 1


def place_grid(grid: Grid) -> list[PlacedCell]:
    """The cells of a finished grid at their positions, in reading order.

    Raises:
        ValueError: The grid has a merge problem (the tree validator refuses these, so a run never gets here with one).
    """
    starts, problems = place_spans(
        len(grid.widths), [[(cell.colspan, cell.rowspan) for cell in row.cells] for row in grid.rows], grid.header_rows,
    )
    if problems:
        first = problems[0]
        raise ValueError(f"row {first.row + 1}: {first.message}")
    return [PlacedCell(r, starts[r][i], cell) for r, row in enumerate(grid.rows) for i, cell in enumerate(row.cells)]


def border_edges(borders: str, placed: PlacedCell, columns: int, rows: int) -> tuple[bool, bool, bool, bool]:
    """Which edges of a cell are drawn: `(top, right, bottom, left)`.

    `all` draws every cell edge, `outer` only the table's own edge, `horizontal` the lines between rows (and the table's top
    and bottom), `none` nothing.
    """
    if borders == "none":
        return False, False, False, False
    first_row, last_row = placed.row == 0, placed.last_row == rows - 1
    first_col, last_col = placed.col == 0, placed.last_col == columns - 1
    if borders == "all":
        return True, True, True, True
    if borders == "horizontal":
        return True, False, True, False
    return first_row, last_col, last_row, first_col


def _join(parts: list[str | Equation | Styled]) -> str:
    """Model text for runs: a plain string when nothing is styled, else a `MathText`."""
    return MathText(parts) if any(not isinstance(p, str) for p in parts) else "".join(str(p) for p in parts)


def text_lines(value: str) -> list[str]:
    """`value` split at its line breaks, each line keeping its styles and equations."""
    lines: list[list[str | Equation | Styled]] = [[]]
    for part in text_runs(value):
        if isinstance(part, Equation):
            lines[-1].append(part)
            continue
        text = part if isinstance(part, str) else part.text
        for i, piece in enumerate(text.split("\n")):
            if i:
                lines.append([])
            if piece:
                lines[-1].append(piece if isinstance(part, str) else replace(part, text=piece))
    return [_join(line) for line in lines]


def _prefixed(prefix: str, value: str) -> str:
    return _join([prefix, *text_runs(value)])


def _bolded(value: str) -> str:
    return _join([Styled(p, bold=True) if isinstance(p, str) else replace(p, bold=True) if isinstance(p, Styled) else p
                  for p in text_runs(value)])


def cell_paragraphs(blocks: Sequence[Block]) -> tuple[str, ...]:
    """The paragraphs of a cell, from the blocks its text reads as.

    A paragraph is one paragraph per line, a heading is bold, a list item carries its bullet or number, a display equation
    is drawn in line; anything else (a gap, a picture) is dropped. A cell with no text holds one empty paragraph.
    """
    out: list[str] = []
    for block in blocks:
        if isinstance(block, Paragraph):
            out.extend(text_lines(block.text))
        elif isinstance(block, Heading):
            out.extend(_bolded(line) for line in text_lines(block.text))
        elif isinstance(block, BulletList):
            out.extend(_prefixed("\u2022 ", item) for item in block.items)
        elif isinstance(block, NumberedList):
            out.extend(_prefixed(f"{number}. ", item) for number, item in enumerate(block.items, start=1))
        elif isinstance(block, Equation):
            out.append(MathText([Equation(block.tex, display=False)]))
    return tuple(out) or ("",)


def low_contrast(fill: str | None, colour: str | None) -> bool:
    """Whether a cell's text colour and fill are both set and fall below `MIN_CONTRAST` (a warning, not an error)."""
    return bool(fill and colour and contrast_ratio(fill, colour) < MIN_CONTRAST)


__all__ = [
    "DEFAULT_BORDER_COLOUR", "GRID_ALIGNMENTS", "GRID_BORDERS", "GRID_HEIGHT_UNITS", "GRID_ROW_HEIGHT_MM", "GRID_VALIGNMENTS",
    "MAX_CELL_CHARS", "MAX_GRID_COLUMNS", "MAX_GRID_ROWS", "MIN_CONTRAST", "PlacedCell", "SpanProblem", "border_edges",
    "cell_paragraphs", "low_contrast", "place_grid", "place_spans", "text_lines",
]
