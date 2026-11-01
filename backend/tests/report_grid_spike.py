"""
Module: report_grid_spike

The custom-table (grid) spike: a prototype cell model and one drawing routine per document format, written against the
real renderers' building blocks, so the findings (docs/decisions.md, "custom tables spike") are measured and the
grid block built on them starts from working code.

Responsibilities:
- `Grid` / `GridRow` / `GridCell`: an author-written table. A merged region is stored on its top-left cell
  (`colspan`, `rowspan`) and the covered positions are *omitted*, as in HTML.
- `place`: checks the spans and returns the occupancy map every renderer reads, so the rules live once.
- `draw_pdf`, `draw_docx`, `draw_odt`, `draw_html`: the four renderings.

Design decisions:
- A distinct type from `Table` (whose rows are records); styles cascade grid, column, row, cell.
- Colours and alignments are closed vocabularies checked by `safe_colour` / the `ALIGN` tables; cell text only ever
  reaches the output as escaped text, never as markup, CSS or an attribute.

External dependencies: reportlab, python-docx, and the ODT/HTML helpers of the real renderers.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from typing import Any

from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph as RlParagraph
from reportlab.platypus import Table as RlTable
from reportlab.platypus import TableStyle

from app.services.branding import contrast_ratio
from app.services.report_odf import xml_text

ALIGN = ("left", "center", "right", "justify")
VALIGN = ("top", "middle", "bottom")
_HEX = re.compile(r"^#([0-9a-fA-F]{6})$")
_PDF_ALIGN = {"left": TA_LEFT, "center": TA_CENTER, "right": TA_RIGHT, "justify": TA_JUSTIFY}
_ODT_ALIGN = {"left": "start", "center": "center", "right": "end", "justify": "justify"}
_DOCX_VALIGN = {"top": "top", "middle": "center", "bottom": "bottom"}
_RL_VALIGN = {"top": "TOP", "middle": "MIDDLE", "bottom": "BOTTOM"}
MIN_CONTRAST = 4.5


class GridError(ValueError):
    """A grid the renderers cannot draw; the message names the cell."""


def safe_colour(value: str | None) -> str | None:
    """`value` as lower-case `#rrggbb`, or `None` for no colour.

    Raises:
        GridError: for anything that is not a six-digit hex colour (a word, CSS, markup).
    """
    if value in (None, "", "none"):
        return None
    if not isinstance(value, str) or not _HEX.match(value):
        raise GridError(f"not a colour: {str(value)[:20]!r}")
    return value.lower()


@dataclass(frozen=True)
class GridCell:
    """One authored cell. A `None` style value inherits from the row, the column, then the grid."""

    text: str = ""
    colspan: int = 1
    rowspan: int = 1
    align: str | None = None
    valign: str | None = None
    fill: str | None = None
    color: str | None = None
    bold: bool | None = None


@dataclass(frozen=True)
class GridRow:
    """A row of cells (covered positions omitted); `height_cm` is a minimum."""

    cells: list[GridCell]
    height_cm: float | None = None
    style: GridCell = field(default_factory=GridCell)


@dataclass(frozen=True)
class Grid:
    """An author-written table.

    Attributes:
        widths_cm: One width per column.
        rows: The rows.
        columns: Per-column style defaults (a `GridCell` whose text is ignored), same length as `widths_cm` or empty.
        header_rows: Leading rows repeated on each page.
        default: The grid-wide style default.
    """

    widths_cm: list[float]
    rows: list[GridRow]
    columns: list[GridCell] = field(default_factory=list)
    header_rows: int = 0
    default: GridCell = field(default_factory=GridCell)


@dataclass(frozen=True)
class Placed:
    """A cell at its grid position with its fully cascaded style."""

    row: int
    col: int
    cell: GridCell
    align: str
    valign: str
    fill: str | None
    color: str | None
    bold: bool

    @property
    def last_row(self) -> int:
        return self.row + self.cell.rowspan - 1

    @property
    def last_col(self) -> int:
        return self.col + self.cell.colspan - 1


def _cascade(grid: Grid, column: int, *layers: GridCell) -> dict[str, Any]:
    """The style of a cell: the most specific layer that sets a key wins (cell, column, grid)."""
    stack = [*layers, grid.columns[column] if grid.columns else GridCell(), grid.default]
    pick = lambda key, fallback: next((getattr(layer, key) for layer in stack if getattr(layer, key) is not None), fallback)  # noqa: E731
    return {"align": pick("align", "left"), "valign": pick("valign", "top"), "fill": pick("fill", None), "color": pick("color", None),
            "bold": pick("bold", False)}


def place(grid: Grid) -> tuple[list[Placed], list[list[tuple[int, int]]]]:
    """Checks the spans and places every cell.

    Returns:
        The cells in reading order, and `owner[r][c]` = the (row, col) of the cell covering that position.

    Raises:
        GridError: a merge that overlaps another or runs past the grid, a row that does not fill the columns, a value
            outside the closed vocabularies, or a merge that crosses the header/body boundary. The message names the cell.
    """
    columns, count = len(grid.widths_cm), len(grid.rows)
    owner: list[list[tuple[int, int] | None]] = [[None] * columns for _ in range(count)]
    placed: list[Placed] = []
    for r, row in enumerate(grid.rows):
        c = 0
        for cell in row.cells:
            while c < columns and owner[r][c] is not None:
                c += 1
            name = f"row {r + 1}, cell {c + 1}"
            if c >= columns:
                raise GridError(f"{name}: more cells than columns")
            if cell.colspan < 1 or cell.rowspan < 1:
                raise GridError(f"{name}: a span below 1")
            if c + cell.colspan > columns or r + cell.rowspan > count:
                raise GridError(f"{name}: the merge runs past the grid")
            if grid.header_rows and r < grid.header_rows <= r + cell.rowspan - 1:
                raise GridError(f"{name}: a merge cannot cross from the header rows into the body")
            for rr in range(r, r + cell.rowspan):
                for cc in range(c, c + cell.colspan):
                    if owner[rr][cc] is not None:
                        raise GridError(f"{name}: the merge overlaps another cell")
                    owner[rr][cc] = (r, c)
            style = _cascade(grid, c, cell, row.style)
            for key, allowed in (("align", ALIGN), ("valign", VALIGN)):
                if style[key] not in allowed:
                    raise GridError(f"{name}: {key} must be one of {', '.join(allowed)}")
            style["fill"], style["color"] = safe_colour(style["fill"]), safe_colour(style["color"])
            placed.append(Placed(r, c, cell, **style))
            c += cell.colspan
        if any(owner[r][cc] is None for cc in range(columns)):
            raise GridError(f"row {r + 1}: has fewer cells than the grid has columns")
    return placed, owner  # type: ignore[return-value]


def low_contrast(item: Placed) -> bool:
    """Whether a cell's text and fill are both set and fall below 4.5:1 (a warning, not an error)."""
    return bool(item.fill and item.color and contrast_ratio(item.fill, item.color) < MIN_CONTRAST)


# ---- PDF --------------------------------------------------------------------------------------------------------


def draw_pdf(grid: Grid, frame_height: float = 700.0) -> RlTable:
    """The grid as a ReportLab table: `SPAN`, `BACKGROUND`, `VALIGN` per cell, Paragraph cells for alignment and colour.

    Row heights are the larger of the row's minimum and what its single-row cells need (a ReportLab row has no minimum).
    A row taller than `frame_height` points would raise `LayoutError` (the whole run fails), so the cell's text is a list
    of paragraphs, one per line of the author's text, and the table may split inside a row (`splitInRow`).
    """
    placed, _ = place(grid)
    widths = [w * cm for w in grid.widths_cm]
    data: list[list[Any]] = [[""] * len(widths) for _ in grid.rows]
    commands: list[tuple] = [("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#999999")), ("LEFTPADDING", (0, 0), (-1, -1), 4),
                             ("RIGHTPADDING", (0, 0), (-1, -1), 4)]
    needed = [0.0] * len(grid.rows)
    for item in placed:
        style = ParagraphStyle(
            f"g{item.row}_{item.col}", fontName="Helvetica-Bold" if item.bold else "Helvetica", fontSize=9, leading=11,
            alignment=_PDF_ALIGN[item.align], textColor=colors.HexColor(item.color or "#000000"),
        )
        paragraphs = [RlParagraph(html.escape(line) or "&nbsp;", style) for line in item.cell.text.split("\n")]
        data[item.row][item.col] = paragraphs
        span_width = sum(widths[item.col : item.last_col + 1]) - 8
        if item.cell.rowspan == 1:
            needed[item.row] = max(needed[item.row], sum(p.wrap(span_width, 10_000)[1] for p in paragraphs) + 6)
        a, b = (item.col, item.row), (item.last_col, item.last_row)
        if item.cell.colspan > 1 or item.cell.rowspan > 1:
            commands.append(("SPAN", a, b))
        if item.fill:
            commands.append(("BACKGROUND", a, b, colors.HexColor(item.fill)))
        commands.append(("VALIGN", a, b, _RL_VALIGN[item.valign]))
    heights = [max(row.height_cm * cm if row.height_cm else 0, needed[i]) or None for i, row in enumerate(grid.rows)]
    too_tall = any(h and h > frame_height for h in heights)
    heights = [None if h and h > frame_height else h for h in heights]  # a row too tall for a page is sized by ReportLab and split
    # Splitting inside a row is allowed only for a grid that has such a row: it lifts the keep-a-row-whole rule for every row.
    return RlTable(data, colWidths=widths, rowHeights=heights, style=TableStyle(commands), repeatRows=grid.header_rows,
                   splitInRow=1 if too_tall else 0)


# ---- Word -------------------------------------------------------------------------------------------------------


def _docx_props(cell, item: Placed) -> None:
    """Shading and vertical alignment on a table cell (also on the cells a vertical merge continues through)."""
    properties = cell._tc.get_or_add_tcPr()
    if item.fill:
        shading = OxmlElement("w:shd")
        shading.set(qn("w:val"), "clear")
        shading.set(qn("w:color"), "auto")
        shading.set(qn("w:fill"), item.fill.lstrip("#").upper())
        properties.append(shading)
    vertical = OxmlElement("w:vAlign")
    vertical.set(qn("w:val"), _DOCX_VALIGN[item.valign])
    properties.append(vertical)


def draw_docx(doc, grid: Grid, usable_cm: float):
    """The grid as a real Word table: `gridSpan` and `vMerge` through python-docx's merge, then per-cell shading, vertical
    alignment, paragraph alignment and run colour; `trHeight` at least, `cantSplit` on every row, `tblHeader` on header rows."""
    placed, _ = place(grid)
    scale = usable_cm / sum(grid.widths_cm)
    table = doc.add_table(rows=len(grid.rows), cols=len(grid.widths_cm), style="Table Grid")
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    for column, width in zip(table.columns, grid.widths_cm, strict=True):
        column.width = Cm(width * scale)
    for index, row in enumerate(grid.rows):
        tr = table.rows[index]._tr
        properties = tr.get_or_add_trPr()
        properties.append(OxmlElement("w:cantSplit"))
        if row.height_cm:
            height = OxmlElement("w:trHeight")
            height.set(qn("w:val"), str(round(row.height_cm * 567)))
            height.set(qn("w:hRule"), "atLeast")
            properties.append(height)
        if index < grid.header_rows:
            properties.append(OxmlElement("w:tblHeader"))
    for item in placed:
        origin = table.cell(item.row, item.col)
        if item.cell.colspan > 1 or item.cell.rowspan > 1:
            origin = origin.merge(table.cell(item.last_row, item.last_col))
        paragraph = origin.paragraphs[0]
        for extra in origin.paragraphs[1:]:  # the merge keeps the covered cells' empty paragraphs
            extra._p.getparent().remove(extra._p)
        paragraph.alignment = {"left": 0, "center": 1, "right": 2, "justify": 3}[item.align]
        run = paragraph.add_run(item.cell.text)
        run.font.size = Pt(9)
        run.font.bold = item.bold
        if item.color:
            run.font.color.rgb = RGBColor.from_string(item.color.lstrip("#").upper())
        for r in range(item.row, item.last_row + 1):
            for c in range(item.col, item.last_col + 1):
                _docx_props(table.cell(r, c), item)
        if item.cell.rowspan > 1:
            _keep_group_together(table, item)
    return table


def _keep_group_together(table, item: Placed) -> None:
    """Word keeps rows on one page when every paragraph but the last row's is `keepNext`, so a vertical merge does not
    straddle a page break (a row may still not fit with the group: the group is then split, as Word does for any table)."""
    for r in range(item.row, item.last_row):
        for c in range(len(table.columns)):
            for paragraph in table.cell(r, c).paragraphs:
                paragraph.paragraph_format.keep_with_next = True


def docx_problems(table) -> list[str]:
    """Structural checks Word is strict about: every row's cells add up to the grid's columns, and a `vMerge` continuation
    sits under a cell with the same `gridSpan` that is itself a `restart` or a continuation."""
    grid_cols = len(table._tbl.tblGrid.findall(qn("w:gridCol")))
    problems: list[str] = []
    above: list[tuple[int, str | None]] = []  # (span, vmerge) per cell of the previous row, by starting column
    for r, tr in enumerate(table._tbl.tr_lst):
        total, current, column = 0, {}, 0
        for tc in tr.tc_lst:
            properties = tc.tcPr
            span = int(properties.find(qn("w:gridSpan")).get(qn("w:val"))) if properties.find(qn("w:gridSpan")) is not None else 1
            merge = properties.find(qn("w:vMerge"))
            kind = None if merge is None else (merge.get(qn("w:val")) or "continue")
            if kind == "continue" and (r == 0 or current_above(above, column) != span):
                problems.append(f"row {r + 1}: a vertical continuation has no cell of the same width above it")
            current[column] = (span, kind)
            column += span
            total += span
        if total != grid_cols:
            problems.append(f"row {r + 1}: cells add up to {total}, the grid has {grid_cols}")
        above = current  # type: ignore[assignment]
    return problems


def current_above(above: Any, column: int) -> int | None:
    """The span of the cell that starts at `column` in the previous row, or `None`."""
    entry = above.get(column) if isinstance(above, dict) else None
    return entry[0] if entry else None


# ---- ODT --------------------------------------------------------------------------------------------------------


def draw_odt(grid: Grid, usable_cm: float, name: str, styles: list[str]) -> str:
    """The grid as ODF table markup. Appends the automatic styles it needs to `styles`.

    A merge is `number-columns-spanned` / `number-rows-spanned` on its top-left cell plus a `covered-table-cell` for every
    other position; a row's minimum height and `keep-together` are row properties; header rows are one
    `table:table-header-rows` group.
    """
    placed, owner = place(grid)
    by_position = {(p.row, p.col): p for p in placed}
    scale = usable_cm / sum(grid.widths_cm)
    styles.append(
        f'<style:style style:name="{name}" style:family="table"><style:table-properties style:width="{usable_cm:.3f}cm" '
        'table:align="margins" fo:margin-bottom="0.2cm"/></style:style>'
    )
    out = [f'<table:table table:name="{name}" table:style-name="{name}">']
    for index, width in enumerate(grid.widths_cm):
        styles.append(
            f'<style:style style:name="{name}_c{index}" style:family="table-column">'
            f'<style:table-column-properties style:column-width="{width * scale:.3f}cm"/></style:style>'
        )
        out.append(f'<table:table-column table:style-name="{name}_c{index}"/>')
    for r, row in enumerate(grid.rows):
        minimum = f' style:min-row-height="{row.height_cm:.3f}cm"' if row.height_cm else ""
        styles.append(
            f'<style:style style:name="{name}_r{r}" style:family="table-row">'
            f'<style:table-row-properties fo:keep-together="always"{minimum}/></style:style>'
        )
        cells = []
        for c in range(len(grid.widths_cm)):
            item = by_position.get((r, c))
            if item is None:
                assert owner[r][c] != (r, c)
                cells.append("<table:covered-table-cell/>")
                continue
            tag = f"{name}_{r}_{c}"
            fill = f' fo:background-color="{item.fill}"' if item.fill else ""
            styles.append(
                f'<style:style style:name="{tag}" style:family="table-cell"><style:table-cell-properties '
                f'fo:border="0.5pt solid #999999" fo:padding="0.08cm" style:vertical-align="{item.valign}"{fill}/></style:style>'
            )
            weight = ' fo:font-weight="bold"' if item.bold else ""
            colour = f' fo:color="{item.color}"' if item.color else ""
            styles.append(
                f'<style:style style:name="{tag}p" style:family="paragraph" style:parent-style-name="Standard">'
                f'<style:paragraph-properties fo:text-align="{_ODT_ALIGN[item.align]}" fo:margin-top="0cm" fo:margin-bottom="0cm"/>'
                f'<style:text-properties fo:font-size="9pt"{weight}{colour}/></style:style>'
            )
            spans = ""
            if item.cell.colspan > 1:
                spans += f' table:number-columns-spanned="{item.cell.colspan}"'
            if item.cell.rowspan > 1:
                spans += f' table:number-rows-spanned="{item.cell.rowspan}"'
            text = xml_text(item.cell.text)  # newlines and runs of spaces as ODF elements; markup escaped
            cells.append(f'<table:table-cell table:style-name="{tag}"{spans} office:value-type="string">'
                         f'<text:p text:style-name="{tag}p">{text}</text:p></table:table-cell>')
        markup = f'<table:table-row table:style-name="{name}_r{r}">{"".join(cells)}</table:table-row>'
        if r == 0 and grid.header_rows:
            out.append("<table:table-header-rows>")
        out.append(markup)
        if grid.header_rows and r == grid.header_rows - 1:
            out.append("</table:table-header-rows>")
    out.append("</table:table>")
    return "".join(out)


# ---- HTML -------------------------------------------------------------------------------------------------------


def draw_html(grid: Grid, usable_cm: float) -> str:
    """The grid as an HTML table. Alignment is a class from a closed list; colours are written only after `safe_colour`
    accepted them (so a style attribute never carries author text); a minimum height is a number."""
    placed, _ = place(grid)
    by_position = {(p.row, p.col): p for p in placed}
    scale = usable_cm / sum(grid.widths_cm)
    cols = "".join(f'<col style="width:{w * scale:.3f}cm">' for w in grid.widths_cm)
    rows = []
    for r, row in enumerate(grid.rows):
        cells = []
        for c in range(len(grid.widths_cm)):
            item = by_position.get((r, c))
            if item is None:
                continue
            style = ";".join(
                part for part in (
                    f"background-color:{item.fill}" if item.fill else "", f"color:{item.color}" if item.color else "",
                    "font-weight:bold" if item.bold else "",
                ) if part
            )
            attrs = f' class="a-{item.align} v-{item.valign}"'
            if item.cell.colspan > 1:
                attrs += f' colspan="{item.cell.colspan}"'
            if item.cell.rowspan > 1:
                attrs += f' rowspan="{item.cell.rowspan}"'
            if style:
                attrs += f' style="{style}"'
            cells.append(f"<td{attrs}>{html.escape(item.cell.text).replace(chr(10), '<br>')}</td>")
        height = f' style="height:{row.height_cm:.3f}cm"' if row.height_cm else ""
        tag = f"<tr{height}>{''.join(cells)}</tr>"
        rows.append(tag)
    head = f"<thead>{''.join(rows[: grid.header_rows])}</thead>" if grid.header_rows else ""
    return f'<table class="grid fixed"><colgroup>{cols}</colgroup>{head}<tbody>{"".join(rows[grid.header_rows:])}</tbody></table>'


HTML_CSS = (
    "table.grid{border-collapse:collapse;table-layout:fixed;width:100%} table.grid td{border:.5pt solid #999;padding:.08cm;"
    "overflow-wrap:anywhere;font:9pt Helvetica,Arial,sans-serif} .a-left{text-align:left}.a-center{text-align:center}"
    ".a-right{text-align:right}.a-justify{text-align:justify}.v-top{vertical-align:top}.v-middle{vertical-align:middle}"
    ".v-bottom{vertical-align:bottom} table.grid tr{break-inside:avoid}"
)


def the_case_set() -> Grid:
    """The plan's case set: a 4 x 4 grid with a column-spanning title, a row-spanning label, black bold columns 1 and 3, a
    right-aligned, a justified and a middle-aligned cell, and a blank 2 cm row."""
    black = GridCell(fill="#000000", color="#ffffff", bold=True)
    long_text = ("A longer review note that has to wrap across several lines so that justification and the height of the "
                 "row it shares with a vertical merge can be seen in every format.")
    return Grid(
        widths_cm=[3.5, 5.0, 3.0, 5.0],
        columns=[black, GridCell(), black, GridCell()],
        header_rows=1,
        rows=[
            GridRow([GridCell("Document details", colspan=4, align="center", fill="#1f4e79", color="#ffffff", bold=True)]),
            GridRow([GridCell("Document"), GridCell("Quarterly risk report"), GridCell("Version"), GridCell("1.2", align="right")]),
            GridRow([GridCell("Review", rowspan=2, valign="middle"), GridCell(long_text, align="justify"), GridCell("Date"),
                     GridCell("")]),
            GridRow([GridCell("Reviewer"), GridCell("Status"), GridCell("Draft", valign="middle", align="center")]),
            GridRow([GridCell("Approval"), GridCell(""), GridCell("Date"), GridCell("")], height_cm=2.0),
        ],
    )


__all__ = [
    "Grid", "GridCell", "GridError", "GridRow", "Placed", "draw_docx", "draw_html", "draw_odt", "draw_pdf", "low_contrast", "place",
    "safe_colour", "the_case_set",
]
