"""
Module: services.report_pdf_running

Draws a document's running headers and footers on the pages of a ReportLab PDF.

Responsibilities:
- `RunningCanvas`: a canvas that keeps each finished page open until the document ends, so `{{pages}}` (the total) is
  known when the header and footer are drawn, in one render pass, and so a picture behind or in front of the text is
  drawn once the page's text is in place (`report_pdf_floating`).
- `PageNote`: what a page records about itself while it is laid out (its style, side and whether it is the first page
  of a section) for the canvas to draw later.
- `draw_band`: one header or footer as an invisible three-column table in the page margin: left, centre and right
  cells, each holding up to three lines, and a logo at the start of one of them.

Design decisions:
- The band is drawn after the page's content, in the margin the layout checked it fits, never inside the text frame, so
  it cannot move the body.
- A cell is left-, centre- or right-aligned in a third of the text width (the same widths for every page of a style),
  and the row is as tall as its tallest cell; the text is centred on the logo when there is one.
- A logo that cannot be decoded is left out: a bad picture never breaks a report.

Dependencies: ReportLab, `services.report_fonts`, `services.report_image_layout`, `services.report_running`,
`services.report_svg`.
"""

from __future__ import annotations

import io
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

from reportlab.graphics import renderPDF
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas

from app.services.report_fonts import draw_aligned, text_width
from app.services.report_image_layout import placed_size_cm
from app.services.report_model import SLOT_NAMES, PageField, PageStyle, RunningBand
from app.services.report_page_styles import BAND_EDGE_CM, BAND_LINE_CM
from app.services.report_pdf_floating import Floater, draw_floaters
from app.services.report_running import band_for_page, band_visible, cell_lines
from app.services.report_svg import svg_flowable

_SIZE = 8
_GAP = 0.2 * cm
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


def _text_of(parts, number: int, total: int) -> str:
    """A line's parts as text, with the page fields filled."""
    return "".join(
        str(number) if part is PageField.PAGE else str(total) if part is PageField.PAGES else part for part in parts
    )


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
    band = band_for_page(band, mirrored=style.mirror, verso=note.verso)
    page_w, page_h = canvas._pagesize
    left, right = (edge * cm for edge in style.edges_cm(verso=note.verso))
    cell_w = (page_w - left - right) / 3
    logo = _logo(band, cell_w / cm)
    lines = {slot: cell_lines(band.slot(slot)) for slot in SLOT_NAMES}
    leading = BAND_LINE_CM * cm
    row_h = max(max((len(v) for v in lines.values()), default=0) * leading, logo[2] if logo else 0.0)
    bottom = page_h - BAND_EDGE_CM * cm - row_h if header else BAND_EDGE_CM * cm
    canvas.saveState()
    for index, slot in enumerate(SLOT_NAMES):
        x0 = left + index * cell_w
        x1 = x0 + cell_w
        align = _ALIGN[slot]
        text_lines = [_text_of(line, note.number, total) for line in lines[slot]]
        text_w = max((text_width(t, _SIZE) for t in text_lines), default=0.0)
        logo_w = logo[1] if logo and band.logo_slot == slot else 0.0
        gap = _GAP if logo_w and text_lines else 0.0
        group = logo_w + gap + text_w
        start = x0 if align == "left" else x1 - group if align == "right" else (x0 + x1) / 2 - group / 2
        if logo_w:
            _draw_logo(canvas, logo, start, bottom + (row_h - logo[2]) / 2)
            start += logo_w + gap
        block_h = len(text_lines) * leading
        top = bottom + (row_h + block_h) / 2
        for k, text in enumerate(text_lines):
            baseline = top - (k + 1) * leading + (leading - _SIZE) / 2 + 0.2 * _SIZE
            anchor = start if align == "left" else start + text_w if align == "right" else start + text_w / 2
            draw_aligned(canvas, anchor, baseline, text, _SIZE, align)
    canvas.restoreState()


def _draw_logo(canvas: Canvas, logo, x: float, y: float) -> None:
    drawable, width, height = logo
    if isinstance(drawable, ImageReader):
        canvas.drawImage(drawable, x, y, width, height, mask="auto")
    else:
        renderPDF.draw(drawable, canvas, x, y)
