"""
Module: services.report_pdf_floating

Pictures that sit over the page rather than in the flow of a ReportLab PDF: a picture placed behind or in front of the text.

Responsibilities:
- `FloatingPicture`: a zero-size flowable that notes where in the flow it was met (the paragraph anchor) and hands the
  picture to the page's canvas.
- `draw_floaters`: draws a page's pictures at their anchors, once the page's text is laid out, so a picture behind the text
  can be put under it and one in front over it.

Design decisions:
- The picture is drawn when the document is saved (`report_pdf_running.RunningCanvas`, which keeps each page open), not
  when the flowable is met, because "behind" has to reach text that was drawn before the picture's own position in the
  flow. Behind-pictures are written at the start of the page's content stream, in-front pictures at its end.
- An anchor is a corner: the flow position (`paragraph`), the corner of the text area (`margin`, which follows a mirrored
  page's own inner margin) or of the sheet (`page`). The offsets run right and down from it, as in Word and ODT.
- A picture that cannot be drawn is left out: a bad picture never breaks a report.

Dependencies: ReportLab, `services.report_image_layout`, `services.report_svg`.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Any

from reportlab.graphics import renderPDF
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Flowable

from app.services.report_image_layout import placed_size_cm
from app.services.report_model import Image, PageStyle
from app.services.report_svg import svg_flowable


@dataclass
class Floater:
    """One layered picture on a page.

    Attributes:
        drawable: An `ImageReader` (raster) or a scaled ReportLab drawing (vector).
        width: Drawn width in points.
        height: Drawn height in points.
        behind: Whether it goes under the text rather than over it.
        anchor: `paragraph`, `margin` or `page`.
        offset_x: Points right of the anchor's corner.
        offset_y: Points below the anchor's corner.
        origin: The flow position (x, y in page points) a `paragraph` anchor is measured from.
    """

    drawable: Any
    width: float
    height: float
    behind: bool
    anchor: str
    offset_x: float
    offset_y: float
    origin: tuple[float, float]


def prepare(block: Image, usable_cm: float) -> tuple[Any, float, float] | None:
    """The drawable of a picture and its size in points, or `None` when it cannot be drawn.

    Args:
        block: The image block.
        usable_cm: The width of the text on the page, which caps the picture's width.
    """
    size = placed_size_cm(block, usable_cm)
    if size is None:
        return None
    width, height = size[0] * cm, size[1] * cm
    try:
        if block.svg is not None:
            drawing = svg_flowable(block.svg, width)
            if drawing is None or not hasattr(drawing, "scale"):
                return None
            drawing.scale(width / drawing.width, height / drawing.height)
            return drawing, width, height
        return ImageReader(io.BytesIO(block.data)), width, height
    except Exception:  # noqa: BLE001 - a bad picture must never break report generation
        return None


class FloatingPicture(Flowable):
    """A flowable with no size that registers a layered picture on the page it lands on.

    Args:
        block: The image block (placement `behind` or `front`).
        usable_cm: The width of the text, which caps the picture's width.
    """

    def __init__(self, block: Image, usable_cm: float) -> None:
        super().__init__()
        self._prepared = prepare(block, usable_cm)
        self._block = block

    def wrap(self, avail_width: float, avail_height: float) -> tuple[float, float]:
        """Takes no room."""
        return 0, 0

    def draw(self) -> None:
        """Hands the picture and the position it was met at to the page's canvas."""
        floaters = getattr(self.canv, "floaters", None)
        if self._prepared is None or floaters is None:
            return
        drawable, width, height = self._prepared
        block = self._block
        floaters.append(Floater(
            drawable, width, height, block.placement == "behind", block.anchor,
            block.offset_x_cm * cm, block.offset_y_cm * cm, self.canv.absolutePosition(0, 0),
        ))


def _draw(canvas: Any, floater: Floater, corner: tuple[float, float]) -> None:
    """Draws one picture with its top-left at the corner moved by its offsets."""
    x = corner[0] + floater.offset_x
    y = corner[1] - floater.offset_y - floater.height
    canvas.saveState()
    if isinstance(floater.drawable, ImageReader):
        canvas.drawImage(floater.drawable, x, y, floater.width, floater.height, mask="auto")
    else:
        renderPDF.draw(floater.drawable, canvas, x, y)
    canvas.restoreState()


def draw_floaters(canvas: Any, floaters: list[Floater], style: PageStyle, verso: bool, *, behind: bool) -> None:
    """Draws the page's pictures behind (or in front of) its text.

    Behind-pictures are moved to the start of the page's content so the text is drawn over them.

    Args:
        canvas: The canvas, restored to the page.
        floaters: The pictures the page's flowables registered.
        style: The page's style (its margins give the `margin` corner).
        verso: Whether it is a left-hand page of a double-sided document.
        behind: Which pictures to draw: those behind the text, or those in front of it.
    """
    chosen = [f for f in floaters if f.behind == behind]
    if not chosen:
        return
    page_h = canvas._pagesize[1]
    left = style.edges_cm(verso=verso)[0] * cm
    start = len(canvas._code)
    for floater in chosen:
        corner = {
            "page": (0.0, page_h),
            "margin": (left, page_h - style.margins.top * cm),
        }.get(floater.anchor, floater.origin)
        _draw(canvas, floater, corner)
    if behind:  # the page's text is already in its content: put these first
        drawn = canvas._code[start:]
        del canvas._code[start:]
        canvas._code[0:0] = drawn
