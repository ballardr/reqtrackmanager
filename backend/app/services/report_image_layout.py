"""
Module: services.report_image_layout

How big a layout's `Image` block prints, the same in every document format.

Responsibilities:
- Read a picture's natural size (a raster's header, an SVG's declared size) in centimetres.
- Turn the block's width, unit and height, and the width of the text, into the size drawn (`placed_size_cm`).

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

from PIL import Image as PilImage
from svglib.svglib import svg2rlg

from app.services.report_model import Image
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


__all__ = ["POINTS_PER_CM", "PIXELS_PER_CM", "intrinsic_cm", "placed_size_cm"]
