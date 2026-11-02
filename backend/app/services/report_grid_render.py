"""
Module: services.report_grid_render

The four drawings of a custom table (`Grid`): ReportLab (PDF), python-docx (Word), OpenDocument (ODT) and HTML.

Responsibilities:
- One function per format. Each reads the finished grid (`report_grid.place_grid`: positions, merges, resolved style) and
  draws merged cells, per-cell fill, text colour, bold, alignment and vertical alignment, per-row minimum height, borders, forced
  column widths and repeating header rows, the same in all four.
- Take the renderer's own inline-text writer as a callback, so a cell's bold, italic, code, links and equations are drawn by
  exactly the code that draws a paragraph elsewhere, and this module never imports a renderer.

Design decisions:
- **Rows stay whole, merged groups stay together.** PDF keeps a row whole (ReportLab default), ODT sets `keep-together`, Word
  `cantSplit` plus `keepNext` on every paragraph of a vertical merge but its last row (Word otherwise splits the merge across
  a page). A group taller than a page splits, as any table does.
- **A row taller than a page must not fail the run.** ReportLab raises `LayoutError` for one, so the PDF drawing gives a cell's
  text as a list of paragraphs, cuts a paragraph that alone exceeds a page, leaves such a row's height to ReportLab and allows
  splitting inside rows only for a grid that has one.
- **Font and size come from the column or the grid** (resolved onto each cell by the evaluator; never a row or cell). A cell
  without them keeps the document's font and the table's own 9 pt, so a grid that sets nothing draws as before.
- **No author text reaches markup except as escaped text.** A colour is written only from the `#rrggbb` the colour resolver
  returned (checked again here), alignments come from closed tables, and numbers are formatted by this module.

Dependencies: reportlab, python-docx, `services.report_grid`, `services.report_column_width`, `services.report_fonts`.
"""

from __future__ import annotations

import html
import re
from collections.abc import Callable
from contextlib import nullcontext
from typing import Any
from xml.sax.saxutils import quoteattr

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

from app.services.report_column_width import resolve_table_widths_cm
from app.services.report_fonts import FontFamily, active_face, pdf_face, using_family
from app.services.report_grid import PlacedCell, border_edges, place_grid
from app.services.report_model import Grid

_HEX = re.compile(r"#[0-9a-f]{6}")
_CELL_POINTS = 9.0
_PDF_ALIGN: dict[str, Any] = {"left": TA_LEFT, "center": TA_CENTER, "right": TA_RIGHT, "justify": TA_JUSTIFY}
_RL_VALIGN = {"top": "TOP", "middle": "MIDDLE", "bottom": "BOTTOM"}
_DOCX_VALIGN = {"top": "top", "middle": "center", "bottom": "bottom"}
_DOCX_ALIGN = {"left": 0, "center": 1, "right": 2, "justify": 3}
_ODT_ALIGN = {"left": "start", "center": "center", "right": "end", "justify": "justify"}
#: A paragraph taller than this share of the page is cut so a row can always be split to fit.
_MAX_PARAGRAPH_SHARE = 0.9


def _hex(value: str | None) -> str | None:
    """`value` when it is a `#rrggbb` colour, else `None`: the last check before a colour is written into markup."""
    return value.lower() if isinstance(value, str) and _HEX.fullmatch(value.lower()) else None


# ---- PDF --------------------------------------------------------------------------------------------------------


def _fit(paragraphs: list[RlParagraph], width: float, limit: float) -> list[Any]:
    """The paragraphs, with any that is taller than `limit` points cut into pieces that are not."""
    fitted: list[Any] = []
    for paragraph in paragraphs:
        pending: Any = paragraph
        while pending.wrap(width, 100_000)[1] > limit:
            pieces = pending.split(width, limit)
            if len(pieces) < 2:
                break
            fitted.append(pieces[0])
            pending = pieces[1]
        fitted.append(pending)
    return fitted


def pdf_grid(grid: Grid, usable_width: float, frame_height: float, markup: Callable[[str, bool], str]) -> RlTable:
    """The grid as a ReportLab table.

    Args:
        grid: The finished grid.
        usable_width: The width available, in points.
        frame_height: The height of a page's text area, in points.
        markup: `(paragraph, bold)` to ReportLab paragraph markup, the renderer's own (escaping, styles, equations).

    Returns:
        A table of paragraph-list cells, with `SPAN`, `BACKGROUND` and `VALIGN` per cell, the borders, repeating header rows
        and, for a row taller than a page, a height left to ReportLab with splitting inside rows allowed.
    """
    placed = place_grid(grid)
    widths = [w * cm for w in resolve_table_widths_cm(grid.widths, usable_width / cm)]
    data: list[list[Any]] = [[""] * len(widths) for _ in grid.rows]
    line = colors.HexColor(_hex(grid.border_color) or "#999999")
    commands: list[tuple] = [("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4)]
    last = (-1, -1)
    if grid.borders == "all":
        commands.append(("GRID", (0, 0), last, 0.5, line))
    elif grid.borders == "outer":
        commands.append(("BOX", (0, 0), last, 0.5, line))
    elif grid.borders == "horizontal":
        commands += [("LINEABOVE", (0, 0), last, 0.5, line), ("LINEBELOW", (0, 0), last, 0.5, line)]
    needed = [0.0] * len(grid.rows)
    for item in placed:
        cell = item.cell
        points = cell.size or _CELL_POINTS
        style = ParagraphStyle(
            f"grid_{item.row}_{item.col}", fontName=pdf_face(cell.font.key, bold=cell.bold) if cell.font else active_face(cell.bold),
            fontSize=points, leading=points + 2, alignment=_PDF_ALIGN[cell.align],
            textColor=colors.HexColor(_hex(cell.color) or "#000000"),
        )
        span_width = sum(widths[item.col : item.last_col + 1]) - 8
        with using_family(cell.font.key) if cell.font else nullcontext():  # fallback characters follow the cell's family
            marked = [markup(text, cell.bold) or "&nbsp;" for text in cell.paragraphs]
        paragraphs = _fit(
            [RlParagraph(text, style) for text in marked], max(span_width, 1), frame_height * _MAX_PARAGRAPH_SHARE,
        )
        data[item.row][item.col] = paragraphs
        if cell.rowspan == 1:
            needed[item.row] = max(needed[item.row], sum(p.wrap(max(span_width, 1), 100_000)[1] for p in paragraphs) + 6)
        a, b = (item.col, item.row), (item.last_col, item.last_row)
        if cell.colspan > 1 or cell.rowspan > 1:
            commands.append(("SPAN", a, b))
        if fill := _hex(cell.fill):
            commands.append(("BACKGROUND", a, b, colors.HexColor(fill)))
        commands.append(("VALIGN", a, b, _RL_VALIGN[cell.valign]))
    heights: list[float | None] = []
    too_tall = False
    for index, row in enumerate(grid.rows):
        height = max(row.height_cm * cm if row.height_cm else 0.0, needed[index])
        if height > frame_height:
            too_tall, height = True, 0.0
        heights.append(height or None)
    # A ReportLab row has no minimum height, so each is the larger of the author's minimum and what its text needs. Splitting
    # inside a row lifts the keep-a-row-whole rule for every row, so it is allowed only for a grid that has a row too tall.
    return RlTable(
        data, colWidths=widths, rowHeights=heights, style=TableStyle(commands), repeatRows=grid.header_rows if grid.repeat_header else 0,
        splitInRow=1 if too_tall else 0,
    )


# ---- Word -------------------------------------------------------------------------------------------------------


def _docx_cell_properties(cell: Any, item: PlacedCell) -> None:
    """Shading and vertical alignment of a table cell; also written on the cells a vertical merge continues through, so the
    merge does not depend on which cell a reader takes its style from."""
    properties = cell._tc.get_or_add_tcPr()
    if fill := _hex(item.cell.fill):
        shading = OxmlElement("w:shd")
        shading.set(qn("w:val"), "clear")
        shading.set(qn("w:color"), "auto")
        shading.set(qn("w:fill"), fill.lstrip("#").upper())
        properties.append(shading)
    vertical = OxmlElement("w:vAlign")
    vertical.set(qn("w:val"), _DOCX_VALIGN[item.cell.valign])
    properties.append(vertical)


def _docx_borders(table: Any, borders: str, colour: str) -> None:
    """The table's own border set: every edge, the outer edge, the lines between rows, or none."""
    edges = {
        "top": borders != "none", "bottom": borders != "none", "left": borders in ("all", "outer"), "right": borders in ("all", "outer"),
        "insideH": borders in ("all", "horizontal"), "insideV": borders == "all",
    }
    element = OxmlElement("w:tblBorders")
    for name, drawn in edges.items():
        edge = OxmlElement(f"w:{name}")
        edge.set(qn("w:val"), "single" if drawn else "nil")
        if drawn:
            edge.set(qn("w:sz"), "4")
            edge.set(qn("w:space"), "0")
            edge.set(qn("w:color"), colour.lstrip("#").upper())
        element.append(edge)
    table._tbl.tblPr.append(element)


def docx_grid(
    doc: Any, grid: Grid, usable_cm: float, add_text: Callable[..., Any],
    font_look: Callable[[FontFamily | None, float | None], Callable[[Any], None] | None] | None = None,
) -> Any:
    """The grid as a real Word table, followed by an empty paragraph that keeps two tables from merging.

    Args:
        doc: The python-docx document.
        grid: The finished grid.
        usable_cm: The width of the text area.
        add_text: `(paragraph, text, style)` writes model text into a paragraph, calling `style(run)` on each plain run (the
            renderer's own `_add_text`).
        font_look: `(family, size)` to the function that sets that family on a run (the renderer's own `_block_look`), or
            `None` when the renderer has none; only called for a cell whose column or grid sets a family.
    """
    placed = place_grid(grid)
    widths = resolve_table_widths_cm(grid.widths, usable_cm)
    table = doc.add_table(rows=len(grid.rows), cols=len(widths))
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    _docx_borders(table, grid.borders, _hex(grid.border_color) or "#999999")
    for column, width in zip(table.columns, widths, strict=True):
        column.width = Cm(width)
    for index, row in enumerate(grid.rows):
        properties = table.rows[index]._tr.get_or_add_trPr()
        properties.append(OxmlElement("w:cantSplit"))
        if row.height_cm:
            height = OxmlElement("w:trHeight")
            height.set(qn("w:val"), str(round(row.height_cm * 567)))
            height.set(qn("w:hRule"), "atLeast")
            properties.append(height)
        if index < grid.header_rows and grid.repeat_header:
            properties.append(OxmlElement("w:tblHeader"))
        for cell, width in zip(table.rows[index].cells, widths, strict=True):
            cell.width = Cm(width)
    for item in placed:
        origin = table.cell(item.row, item.col)
        if item.cell.colspan > 1 or item.cell.rowspan > 1:
            origin = origin.merge(table.cell(item.last_row, item.last_col))
        for extra in origin.paragraphs[1:]:  # a merge keeps the covered cells' empty paragraphs
            extra._p.getparent().remove(extra._p)
        colour = _hex(item.cell.color)

        family = font_look(item.cell.font, None) if font_look is not None and item.cell.font is not None else None

        points = item.cell.size or _CELL_POINTS

        def style(run: Any, bold: bool = item.cell.bold, colour: str | None = colour, family: Any = family, points: float = points) -> None:
            run.font.size = Pt(points)
            if family is not None:
                family(run)
            if bold:
                run.font.bold = True
            if colour:
                run.font.color.rgb = RGBColor.from_string(colour.lstrip("#").upper())

        for number, text in enumerate(item.cell.paragraphs):
            paragraph = origin.paragraphs[0] if number == 0 else origin.add_paragraph()
            paragraph.alignment = _DOCX_ALIGN[item.cell.align]
            paragraph.paragraph_format.space_before = Pt(0)
            paragraph.paragraph_format.space_after = Pt(0)
            if not add_text(paragraph, text, style):
                style(paragraph.add_run(""))  # an all-equation paragraph still gets its size
        for r in range(item.row, item.last_row + 1):
            for c in range(item.col, item.last_col + 1):
                _docx_cell_properties(table.cell(r, c), item)
        if item.cell.rowspan > 1:  # Word splits a vertical merge across a page unless every row but the last is kept with the next
            for r in range(item.row, item.last_row):
                for c in range(len(widths)):
                    for paragraph in table.cell(r, c).paragraphs:
                        paragraph.paragraph_format.keep_with_next = True
    doc.add_paragraph()
    return table


# ---- ODT --------------------------------------------------------------------------------------------------------


def odt_grid(
    grid: Grid, name: str, usable_cm: float, inline: Callable[[str], str], styles: list[str], families: list[FontFamily] | None = None,
) -> str:
    """The grid as OpenDocument table markup; appends the automatic styles it uses to `styles` and each font family a cell
    sets to `families` (so the document declares it).

    A merge is `number-columns-spanned` / `number-rows-spanned` on its top-left cell plus a `covered-table-cell` for every
    other position; header rows are one `table:table-header-rows` group; a row's minimum height and `keep-together` are row
    properties. Cell and paragraph styles are shared by cells that look alike.
    """
    placed = place_grid(grid)
    by_position = {(p.row, p.col): p for p in placed}
    widths = resolve_table_widths_cm(grid.widths, usable_cm)
    columns, count = len(widths), len(grid.rows)
    line = _hex(grid.border_color) or "#999999"
    styles.append(
        f'<style:style style:name="{name}" style:family="table"><style:table-properties style:width="{usable_cm:.3f}cm" '
        'table:align="margins" fo:margin-bottom="0.2cm"/></style:style>'
    )
    out = [f'<table:table table:name="{name}" table:style-name="{name}">']
    for index, width in enumerate(widths):
        styles.append(
            f'<style:style style:name="{name}_c{index}" style:family="table-column">'
            f'<style:table-column-properties style:column-width="{width:.3f}cm"/></style:style>'
        )
        out.append(f'<table:table-column table:style-name="{name}_c{index}"/>')
    known: dict[tuple, str] = {}

    def cell_styles(item: PlacedCell) -> tuple[str, str]:
        cell = item.cell
        key = (
            cell.align, cell.valign, _hex(cell.fill), _hex(cell.color), cell.bold, border_edges(grid.borders, item, columns, count),
            cell.font.key if cell.font else None, cell.size,
        )
        if key not in known:
            tag = f"{name}_s{len(known)}"
            known[key] = tag
            edges = "".join(
                f' fo:border-{side}="{"0.5pt solid " + line if drawn else "none"}"'
                for side, drawn in zip(("top", "right", "bottom", "left"), key[5], strict=True)
            )
            fill = f' fo:background-color="{key[2]}"' if key[2] else ""
            weight = ' fo:font-weight="bold"' if cell.bold else ""
            colour = f' fo:color="{key[3]}"' if key[3] else ""
            face = ""
            if cell.font is not None:
                face = f" style:font-name={quoteattr(cell.font.word_name)}"
                if families is not None and cell.font not in families:
                    families.append(cell.font)
            styles.append(
                f'<style:style style:name="{tag}" style:family="table-cell"><style:table-cell-properties{edges} fo:padding="0.08cm" '
                f'style:vertical-align="{cell.valign}"{fill}/></style:style>'
            )
            styles.append(
                f'<style:style style:name="{tag}p" style:family="paragraph" style:parent-style-name="Standard">'
                f'<style:paragraph-properties fo:text-align="{_ODT_ALIGN[cell.align]}" fo:margin-top="0cm" fo:margin-bottom="0cm"/>'
                f'<style:text-properties fo:font-size="{cell.size or _CELL_POINTS:g}pt"{face}{weight}{colour}/></style:style>'
            )
        return known[key], f"{known[key]}p"

    for r, row in enumerate(grid.rows):
        minimum = f' style:min-row-height="{row.height_cm:.3f}cm"' if row.height_cm else ""
        styles.append(
            f'<style:style style:name="{name}_r{r}" style:family="table-row">'
            f'<style:table-row-properties fo:keep-together="always"{minimum}/></style:style>'
        )
        cells = []
        for c in range(columns):
            item = by_position.get((r, c))
            if item is None:
                cells.append("<table:covered-table-cell/>")
                continue
            cell_style, paragraph_style = cell_styles(item)
            spans = ""
            if item.cell.colspan > 1:
                spans += f' table:number-columns-spanned="{item.cell.colspan}"'
            if item.cell.rowspan > 1:
                spans += f' table:number-rows-spanned="{item.cell.rowspan}"'
            body = "".join(f'<text:p text:style-name="{paragraph_style}">{inline(text)}</text:p>' for text in item.cell.paragraphs)
            cells.append(f'<table:table-cell table:style-name="{cell_style}"{spans} office:value-type="string">{body}</table:table-cell>')
        if r == 0 and grid.header_rows and grid.repeat_header:
            out.append("<table:table-header-rows>")
        out.append(f'<table:table-row table:style-name="{name}_r{r}">{"".join(cells)}</table:table-row>')
        if grid.repeat_header and grid.header_rows and r == grid.header_rows - 1:
            out.append("</table:table-header-rows>")
    out.append("</table:table>")
    return "".join(out)


# ---- HTML -------------------------------------------------------------------------------------------------------


GRID_CSS = (
    "table.grid { table-layout: fixed; border-collapse: collapse; width: 100%; font-size: 9pt; } "
    "table.grid td { padding: .08cm .15cm; border: 0 solid var(--grid-line, #999); overflow-wrap: anywhere; } "
    "table.grid tbody tr:nth-child(even) td { background-color: transparent; } table.grid tr { break-inside: avoid; } "
    "table.grid td.bt { border-top-width: .5pt; } table.grid td.br { border-right-width: .5pt; } "
    "table.grid td.bb { border-bottom-width: .5pt; } table.grid td.bl { border-left-width: .5pt; } "
    "table.grid td.a-left { text-align: left; } table.grid td.a-center { text-align: center; } "
    "table.grid td.a-right { text-align: right; } table.grid td.a-justify { text-align: justify; } "
    "table.grid td.v-top { vertical-align: top; } table.grid td.v-middle { vertical-align: middle; } "
    "table.grid td.v-bottom { vertical-align: bottom; } table.grid td p { margin: 0; min-height: 1em; }"
)


def html_grid(grid: Grid, inline: Callable[[str], str]) -> str:
    """The grid as an HTML table.

    Alignment, vertical alignment and border edges are classes from closed lists; a fill or text colour is written into `style`
    only when it is a `#rrggbb` colour, and a row's height only as a number, so no author text reaches an attribute.
    """
    placed = place_grid(grid)
    by_position = {(p.row, p.col): p for p in placed}
    widths = resolve_table_widths_cm(grid.widths, 100.0)  # a nominal width: the columns come out as percentages
    total = sum(widths) or 1.0
    columns, count = len(widths), len(grid.rows)
    cols = "".join(f'<col style="width:{w / total * 100:.3f}%">' for w in widths)
    rows: list[str] = []
    for r, row in enumerate(grid.rows):
        cells = []
        for c in range(columns):
            item = by_position.get((r, c))
            if item is None:
                continue
            cell = item.cell
            edges = border_edges(grid.borders, item, columns, count)
            classes = " ".join(
                ["a-" + cell.align, "v-" + cell.valign, *(cls for cls, drawn in zip(("bt", "br", "bb", "bl"), edges, strict=True) if drawn)]
            )
            fill, colour = _hex(cell.fill), _hex(cell.color)
            style = ";".join(
                part for part in (
                    f"background-color:{fill}" if fill else "", f"color:{colour}" if colour else "", "font-weight:bold" if cell.bold else "",
                    f"font-family:{cell.font.css_stack}" if cell.font else "", f"font-size:{cell.size:g}pt" if cell.size else "",
                ) if part
            )
            style = html.escape(style, quote=True)
            attrs = f' class="{classes}"'
            if cell.colspan > 1:
                attrs += f' colspan="{cell.colspan}"'
            if cell.rowspan > 1:
                attrs += f' rowspan="{cell.rowspan}"'
            if style:
                attrs += f' style="{style}"'
            body = "".join(f"<p>{inline(text)}</p>" for text in cell.paragraphs)
            cells.append(f"<td{attrs}>{body}</td>")
        height = f' style="height:{row.height_cm:.3f}cm"' if row.height_cm else ""
        rows.append(f"<tr{height}>{''.join(cells)}</tr>")
    head = f"<thead>{''.join(rows[: grid.header_rows])}</thead>" if grid.header_rows else ""
    line = _hex(grid.border_color) or "#999999"
    return (
        f'<table class="grid" style="--grid-line:{html.escape(line)}"><colgroup>{cols}</colgroup>{head}'
        f'<tbody>{"".join(rows[grid.header_rows:])}</tbody></table>'
    )


__all__ = ["GRID_CSS", "docx_grid", "html_grid", "odt_grid", "pdf_grid"]
