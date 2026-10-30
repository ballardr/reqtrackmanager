"""
Module: services.report_image_layout

How big a layout's `Image` block prints, the same in every document format.

Responsibilities:
- Read a picture's natural size (a raster's header, an SVG's declared size) in centimetres.
- Turn the block's width, unit and height, and the width of the text, into the size drawn (`placed_size_cm`).
- Do the same for the pictures of a table cell, against the cell's width, stacked or side by side (`place_cell_pictures`).

Design decisions:
- **One rule for four renderers**, so PDF, Word, ODT and HTML never disagree about a size. A width alone keeps the
  picture's shape; a height alone sizes it by height; both stretch it to those two. Whatever is asked, the picture is
  never wider than the text (the height shrinks with it). With no size the picture prints at its natural size at 96
  pixels per inch, shrunk to fit.
- A picture whose size cannot be read is not drawn (the caller skips it), never guessed.

Dependencies: Pillow, `svglib` (through `services.report_svg`), `services.report_model` (`Image`).
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image as PilImage
from svglib.svglib import svg2rlg

from app.services.report_model import Image, ImageCell
from app.services.report_svg import UnsafeSvgError, sanitize_svg

PIXELS_PER_CM = 96 / 2.54
POINTS_PER_CM = 72 / 2.54


def intrinsic_cm(block: Image) -> tuple[float, float] | None:
    """The picture's natural width and height in cm, or `None` when it cannot be read.

    Args:
        block: The image block (raster bytes or SVG markup).

    Returns:
        `(width, height)`, both positive.
    """
    if block.svg is not None:
        try:
            drawing = svg2rlg(io.StringIO(sanitize_svg(block.svg)))
        except (UnsafeSvgError, Exception):  # noqa: BLE001 - svglib raises many types on exotic markup
            return None
        if drawing is None or drawing.width <= 0 or drawing.height <= 0:
            return None
        return drawing.width / POINTS_PER_CM, drawing.height / POINTS_PER_CM
    try:
        with PilImage.open(io.BytesIO(block.data)) as image:
            width, height = image.size
    except Exception:  # noqa: BLE001 - not an image: skipped, as everywhere else
        return None
    if width <= 0 or height <= 0:
        return None
    return width / PIXELS_PER_CM, height / PIXELS_PER_CM


def placed_size_cm(block: Image, usable_cm: float) -> tuple[float, float] | None:
    """The size to draw `block` at, in cm.

    Args:
        block: The image block.
        usable_cm: The width of the text on the page the picture is on.

    Returns:
        `(width, height)` never wider than `usable_cm`, or `None` when the picture's size cannot be read.
    """
    natural = intrinsic_cm(block)
    if natural is None:
        return None
    natural_w, natural_h = natural
    ratio = natural_h / natural_w
    if block.width is not None:
        width = usable_cm * block.width / 100 if block.width_unit == "percent" else block.width
    elif block.height_cm is not None:
        width = block.height_cm / ratio
    else:
        width = natural_w
    height = block.height_cm if block.height_cm is not None else width * ratio
    if width > usable_cm:
        height, width = height * usable_cm / width, usable_cm
    return width, height


#: The gap between two pictures of one table cell, in cm.
CELL_GAP_CM = 0.15
#: The space a cell keeps free of pictures on each side (its padding), in cm.
CELL_PADDING_CM = 0.2


@dataclass(frozen=True)
class PlacedPicture:
    """One picture of a table cell at its drawn size.

    Attributes:
        image: The picture.
        width_cm: Drawn width.
        height_cm: Drawn height.
        line: Which line of the cell it is on: its own for `stacked`, shared with its neighbours for `side_by_side`.
    """

    image: Image
    width_cm: float
    height_cm: float
    line: int


def place_cell_pictures(cell: ImageCell, column_cm: float, max_height_cm: float | None) -> list[PlacedPicture]:
    """The pictures of a table cell at the sizes they are drawn, in the same way in every format.

    Each picture is sized as an Image block is, against the width inside the cell (`column_cm` less its padding), so a
    width in `percent` is a share of the column. Stacked pictures sit one per line; side-by-side pictures fill a line
    and wrap. A picture whose size cannot be read is left out.

    The only limit applied is the physical one: pictures are shrunk together, keeping their shapes, when the cell would
    otherwise be taller than a page (`max_height_cm`, the page's text height), which no renderer can lay out. A size the
    author chose is otherwise never reduced.

    Args:
        cell: The cell.
        column_cm: The column's width.
        max_height_cm: The tallest a cell can be on its page, or `None` for no limit (a browser lays out its own pages).

    Returns:
        The placed pictures in order.
    """
    inner = max(column_cm - 2 * CELL_PADDING_CM, 0.5)
    sized = [(image, size) for image in cell.images if (size := placed_size_cm(image, inner)) is not None]
    placed: list[PlacedPicture] = []
    line, used = 0, 0.0
    for image, (width, height) in sized:
        if cell.arrange == "side_by_side":
            if placed and used + CELL_GAP_CM + width > inner + 1e-6:
                line, used = line + 1, 0.0
            used += width + (CELL_GAP_CM if used else 0.0)
        elif placed:
            line += 1
        placed.append(PlacedPicture(image, width, height, line))
    if max_height_cm is not None and placed:
        heights = [max(p.height_cm for p in placed if p.line == n) for n in range(line + 1)]
        total = sum(heights) + CELL_GAP_CM * line
        if total > max_height_cm > 0:
            scale = max_height_cm / total
            placed = [PlacedPicture(p.image, p.width_cm * scale, p.height_cm * scale, p.line) for p in placed]
    return placed


__all__ = [
    "CELL_GAP_CM", "CELL_PADDING_CM", "POINTS_PER_CM", "PIXELS_PER_CM", "PlacedPicture", "intrinsic_cm", "place_cell_pictures",
    "placed_size_cm",
]
