"""
Module: services.report_pdf_running

Draws a document's running headers and footers on the pages of a ReportLab PDF.

Responsibilities:
- `RunningCanvas`: a canvas that keeps each finished page open until the document ends, so `{{pages}}` (the total) is
  known when the header and footer are drawn, in one render pass, and so a picture behind or in front of the text is
  drawn once the page's text is in place (`report_pdf_floating`).
- `PageNote`: what a page records about itself while it is laid out (its style, side and whether it is the first page
  of a section) for the canvas to draw later.
- `band_room_cm` and `grow_margins_for_bands`: the margin a wrapped band needs, and the document with margins raised to it.
- `draw_band`: one header or footer as an invisible three-column table in the page margin: left, centre and right
  cells, each holding up to three lines of runs in the band's font, size and colour (bold and italic where marked),
  and a logo at the start of one of them.

Design decisions:
- The band is drawn after the page's content, in the margin, never inside the text frame, so it cannot move the body. The
  layout check cannot know how far a value will wrap, so `grow_margins_for_bands` raises a style's top and bottom margins
  to what its wrapped band needs before the pages are laid out (a margin already large enough is kept).
- Cell widths and vertical alignment come from `report_band_cells.resolve_band_cells` (shared with the other formats);
  text is aligned left, centre or right in its cell and wrapped at spaces to the cell, so a long centre wraps while the
  short sides keep their width. The row is as tall as its tallest cell and a cell's logo and text sit at its alignment.
- A logo that cannot be decoded is left out: a bad picture never breaks a report.

- A band with no font follows the document's body font (the family active for the whole render); one with a font draws
  and measures in that family.

Dependencies: ReportLab, `services.report_band_cells`, `services.report_fonts`, `services.report_image_layout`, `services.report_running`,
`services.report_svg`.
"""

from __future__ import annotations

import io
import re
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass, replace
from typing import Any

from reportlab.graphics import renderPDF
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas

from app.services.report_band_cells import CELL_PADDING_CM, BandCell, resolve_band_cells
from app.services.report_fonts import draw_run, text_width, using_family
from app.services.report_image_layout import placed_size_cm
from app.services.report_model import PageField, PageStyle, PageStyleChange, ReportDocument, RunningBand
from app.services.report_page_styles import BAND_EDGE_CM
from app.services.report_pdf_floating import Floater, draw_floaters
from app.services.report_running import band_for_page, band_line_cm, band_size_pt, band_visible, cell_lines, unmark
from app.services.report_svg import svg_flowable

_GAP = 0.2 * cm
#: Points a word may pass its cell's room before it wraps (the resolver measures a cell's need to a hair, in another font context).
_FIT_SLACK = 1.0
#: The page number a band is measured with when its height is reserved (a page number is not known until the end).
_WIDEST_PAGE = 888
_ALIGN = {"left": "left", "centre": "center", "right": "right"}


@dataclass(frozen=True)
class PageNote:
    """What the canvas needs to draw a page's bands after the whole document is laid out.

    Attributes:
        style: The page style the page uses.
        verso: Whether it is a left-hand page of a double-sided document.
        first: Whether it is the first page of the document or of a section.
        number: The page number.
    """

    style: PageStyle
    verso: bool
    first: bool
    number: int


class RunningCanvas(Canvas):
    """A canvas that draws every page's header and footer when the document is saved, once the page count is known."""

    _startPage: Callable[[], None]  # ReportLab's own method; declared because its stubs do not list it

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._finished: list[dict] = []
        self.floaters: list[Floater] = []

    def showPage(self) -> None:  # noqa: N802 - ReportLab's name
        """Keeps the finished page open instead of writing it."""
        self._finished.append(dict(self.__dict__))
        self.floaters = []
        self._startPage()

    def save(self) -> None:
        """Draws each page's bands with the total known, writes the pages, then the file."""
        total = len(self._finished)
        for state in self._finished:
            self.__dict__.update(state)
            note: PageNote | None = state.get("_note")
            if note is not None:
                draw_floaters(self, state["floaters"], note.style, note.verso, behind=True)
                draw_floaters(self, state["floaters"], note.style, note.verso, behind=False)
                for band in (note.style.header, note.style.footer):
                    draw_band(self, band, note, total, header=band is note.style.header)
            super().showPage()
        super().save()


def _runs_of(parts, number: int, total: int) -> list[tuple[str, bool, bool]]:
    """A line's parts as `(text, bold, italic)` runs, with the page fields filled."""
    runs: list[tuple[str, bool, bool]] = []
    for part in parts:
        words, bold, italic = unmark(part)
        text = str(number) if words is PageField.PAGE else str(total) if words is PageField.PAGES else words
        if runs and runs[-1][1:] == (bold, italic):
            runs[-1] = (runs[-1][0] + text, bold, italic)
        else:
            runs.append((text, bold, italic))
    return runs


def _width(runs: list[tuple[str, bool, bool]], size: float) -> float:
    """The width of a line's runs in points."""
    return sum(text_width(text, size, bold=bold, italic=italic) for text, bold, italic in runs)


def _logo(band: RunningBand, cell_cm: float):
    """`(drawable, width_pt, height_pt)` for the band's logo, or `None` when it cannot be drawn."""
    if band.logo is None:
        return None
    sized = replace(band.logo, height_cm=band.logo_height_cm, width=None)
    size = placed_size_cm(sized, cell_cm)
    if size is None:
        return None
    width, height = size[0] * cm, size[1] * cm
    try:
        if sized.svg is not None:
            drawing = svg_flowable(sized.svg, width)
            if drawing is None or not hasattr(drawing, "scale"):
                return None
            drawing.scale(width / drawing.width, height / drawing.height)
            return drawing, width, height
        return ImageReader(io.BytesIO(sized.data)), width, height
    except Exception:  # noqa: BLE001 - a bad logo must never break report generation
        return None


def _wrap(runs: list[tuple[str, bool, bool]], size: float, limit: float) -> list[list[tuple[str, bool, bool]]]:
    """Breaks a line's runs at spaces into lines no wider than `limit` points (a word wider than that stays whole).

    Args:
        runs: The line as `(text, bold, italic)` runs.
        size: The text size in points.
        limit: The room in points.

    Returns:
        The lines, each a list of runs; an empty line stays one empty line.
    """
    lines: list[list[tuple[str, bool, bool]]] = [[]]
    used = 0.0
    for text, bold, italic in runs:
        for token in re.findall(r"\S+|\s+", text):
            token_w = text_width(token, size, bold=bold, italic=italic)
            if token.isspace():
                if used == 0.0:
                    continue  # no leading space on a wrapped line
            elif used and used + token_w > limit + _FIT_SLACK:
                if lines[-1]:
                    lines[-1][-1] = (lines[-1][-1][0].rstrip(), *lines[-1][-1][1:])
                lines.append([])
                used = 0.0
            if lines[-1] and lines[-1][-1][1:] == (bold, italic):
                lines[-1][-1] = (lines[-1][-1][0] + token, bold, italic)  # one run per stretch, as the text was written
            else:
                lines[-1].append((token, bold, italic))
            used += token_w
    while len(lines) > 1 and lines[-1] == []:
        lines.pop()
    return lines


def _offset(valign: str, room: float, content: float) -> float:
    """How far below the cell's top a block of height `content` starts in `room`, for `valign`."""
    return 0.0 if valign == "top" else room - content if valign == "bottom" else (room - content) / 2


@dataclass(frozen=True)
class _BandLayout:
    """A band laid out for one page: its resolved cells with their wrapped lines, the logo and the row's height in points."""

    band: RunningBand
    cells: list[tuple[BandCell, list[list[tuple[str, bool, bool]]], float]]  # (cell, wrapped lines, logo width in points)
    logo: Any
    size: float
    leading: float
    row_h: float


def _layout_band(band: RunningBand, style: PageStyle, page_w: float, *, verso: bool, number: int, total: int) -> _BandLayout:
    """Lays a band out as it prints on a page: cell widths, wrapped lines, logo and the height of the row.

    Args:
        band: The band as written (mirrored here for a left-hand page of a double-sided document).
        style: The page's style.
        page_w: The page width in points.
        verso: Whether the page is a left-hand one.
        number: The page number the band shows (a stand-in digit string measures the widest case).
        total: The page count the band shows.
    """
    band = band_for_page(band, mirrored=style.mirror, verso=verso)
    left, right = (edge * cm for edge in style.edges_cm(verso=verso))
    size = band_size_pt(band.size)
    leading = band_line_cm(band.size) * cm
    with using_family(band.font.key) if band.font else nullcontext():
        cells = resolve_band_cells(band, (page_w - left - right) / cm)
        logo_cell = next((c for c in cells if band.logo is not None and band.logo_slot == c.slot), None)
        logo = _logo(band, logo_cell.width_cm) if logo_cell else None
        laid = []
        for cell in cells:
            logo_w = logo[1] if logo and logo_cell is cell else 0.0
            lines = cell_lines(band.slot(cell.slot))
            room = cell.width_cm * cm - CELL_PADDING_CM * cm - logo_w - (_GAP if logo_w and lines else 0.0)
            text_lines = [wrapped for line in lines for wrapped in _wrap(_runs_of(line, number, total), size, max(room, size))]
            laid.append((cell, text_lines, logo_w))
    row_h = max(max(len(lines) for _, lines, _ in laid) * leading, logo[2] if logo else 0.0)
    return _BandLayout(band, laid, logo, size, leading, row_h)


def band_room_cm(band: RunningBand | None, style: PageStyle, *, verso: bool) -> float:
    """The margin a band needs on a page of `style` once its text has wrapped: the gap to the page edge plus the row's height.

    Args:
        band: The header or footer, or `None`.
        style: The page style it is printed on.
        verso: Whether to measure the left-hand page (a mirrored band has its cells swapped there).

    Returns:
        Centimetres, or 0 when the band prints nothing. Page numbers are measured as the widest the document could show.
    """
    if band is None or band.empty:
        return 0.0
    layout = _layout_band(band, style, style.dimensions_cm[0] * cm, verso=verso, number=_WIDEST_PAGE, total=_WIDEST_PAGE)
    return BAND_EDGE_CM + layout.row_h / cm


def grow_margins_for_bands(document: ReportDocument) -> ReportDocument:
    """`document` with each page style's top and bottom margins raised to hold its header and footer.

    A header or footer wraps to the width of its cells, so a long value can need more lines than the margin the layout
    check measured; the page's text then starts below the band instead of under it. A margin the author set that is
    already large enough is kept.

    Args:
        document: The neutral report, its bands already filled.

    Returns:
        A copy whose document style and section styles have the grown margins; the same object when nothing grows.
    """

    def grown(style: PageStyle) -> PageStyle:
        sides = (False, True) if style.mirror else (False,)
        top = max([style.margins.top, *(band_room_cm(style.header, style, verso=v) for v in sides)])
        bottom = max([style.margins.bottom, *(band_room_cm(style.footer, style, verso=v) for v in sides)])
        if (top, bottom) == (style.margins.top, style.margins.bottom):
            return style
        return replace(style, margins=replace(style.margins, top=top, bottom=bottom))

    own = grown(document.style)
    blocks = [replace(b, style=grown(b.style)) if isinstance(b, PageStyleChange) else b for b in document.blocks]
    return replace(document, blocks=blocks, margins=own.margins)


def draw_band(canvas: Any, band: RunningBand | None, note: PageNote, total: int, *, header: bool) -> None:
    """Draws a header or footer on the current page of `canvas`.

    Args:
        canvas: The canvas, restored to the page.
        band: The band, or `None` (a plain page, which has none).
        note: The page's style, side, position in its section and number.
        total: The number of pages in the document.
        header: Whether this is the header (the top margin) rather than the footer.
    """
    if not band_visible(band, first_page=note.first):
        return
    assert band is not None
    style = note.style
    page_w, page_h = canvas._pagesize
    layout = _layout_band(band, style, page_w, verso=note.verso, number=note.number, total=total)
    left = style.edges_cm(verso=note.verso)[0] * cm
    row_h, size, leading, logo = layout.row_h, layout.size, layout.leading, layout.logo
    bottom = page_h - BAND_EDGE_CM * cm - row_h if header else BAND_EDGE_CM * cm
    canvas.saveState()
    if layout.band.colour:
        canvas.setFillColor(colors.HexColor(layout.band.colour))
    with using_family(layout.band.font.key) if layout.band.font else nullcontext():
        x0 = left
        for cell, text_lines, logo_w in layout.cells:
            x1 = x0 + cell.width_cm * cm
            align = _ALIGN[cell.slot]
            widths = [_width(runs, size) for runs in text_lines]
            text_w = max(widths, default=0.0)
            gap = _GAP if logo_w and text_lines else 0.0
            group = logo_w + gap + text_w
            start = x0 if align == "left" else x1 - group if align == "right" else (x0 + x1) / 2 - group / 2
            top = bottom + row_h
            if logo and logo_w:
                _draw_logo(canvas, logo, start, top - _offset(cell.valign, row_h, logo[2]) - logo[2])
                start += logo_w + gap
            text_top = top - _offset(cell.valign, row_h, len(text_lines) * leading)
            for k, (runs, line_w) in enumerate(zip(text_lines, widths, strict=True)):
                baseline = text_top - (k + 1) * leading + (leading - size) / 2 + 0.2 * size
                x = start if align == "left" else start + text_w - line_w if align == "right" else start + (text_w - line_w) / 2
                for text, bold, italic in runs:
                    x += draw_run(canvas, x, baseline, text, size, bold=bold, italic=italic)
            x0 = x1
    canvas.restoreState()


def _draw_logo(canvas: Canvas, logo, x: float, y: float) -> None:
    drawable, width, height = logo
    if isinstance(drawable, ImageReader):
        canvas.drawImage(drawable, x, y, width, height, mask="auto")
    else:
        renderPDF.draw(drawable, canvas, x, y)
