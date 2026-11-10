"""
Module: services.logo_plate

Draws the organisation's logo on a coloured plate (the "logo band" colour) so a light logo stays visible on white
report paper.

Responsibilities:
- `plate_resolved`: a `ResolvedImage` (raster bytes or sanitised SVG) returned on a plate of the given colour.
- `plate_raster_bytes`: the same for raw raster bytes (the built-in report cover).

Design decisions:
- The plate is part of the picture, not a drawing instruction. Every report renderer already embeds a logo (inline,
  wrapped, behind text, in a header or footer) in all four formats, so compositing once here gives the same band in
  each with no per-format colour code, and a layout's picture placement settings keep working unchanged.
- Only the organisation's logo is plated; a library picture is the author's own and is never altered.
- The colour is a validated `#rrggbb` and is only ever written as a fill value; anything else leaves the logo as it was.

Dependencies: Pillow, lxml (via `services.report_svg`'s sanitised SVG), `services.report_images.ResolvedImage`.
"""

from __future__ import annotations

import io
import re
from dataclasses import replace
from typing import TYPE_CHECKING

from lxml import etree
from PIL import Image as PilImage

from app.services.report_raster import max_image_pixels
from app.services.report_svg import SVG_NS

if TYPE_CHECKING:
    from app.services.report_images import ResolvedImage

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_NUMBER = re.compile(r"^\s*([0-9]*\.?[0-9]+)\s*(?:px)?\s*$")
#: Padding around the logo, as a share of its longer side.
PADDING = 0.15


def plate_raster_bytes(data: bytes, band_hex: str) -> bytes:
    """A raster logo on a plate of `band_hex`.

    Args:
        data: PNG or JPEG bytes.
        band_hex: The plate colour, `#rrggbb`.

    Returns:
        PNG bytes with the logo centred on the plate, or `data` unchanged when the colour is invalid, the image cannot
        be read or the plated picture would exceed the pixel limit.
    """
    if not _HEX.match(band_hex):
        return data
    try:
        with PilImage.open(io.BytesIO(data)) as source:
            logo = source.convert("RGBA")
        pad = max(2, round(max(logo.size) * PADDING))
        size = (logo.size[0] + 2 * pad, logo.size[1] + 2 * pad)
        if size[0] * size[1] > max_image_pixels():
            return data
        plate = PilImage.new("RGBA", size, band_hex)
        plate.alpha_composite(logo, (pad, pad))
        out = io.BytesIO()
        plate.convert("RGB").save(out, "PNG", optimize=True)
        return out.getvalue()
    except Exception:  # noqa: BLE001 - an unreadable logo must never break report generation
        return data


def _plate_svg(svg: str, band_hex: str) -> str:
    """Sanitised SVG markup with a `band_hex` rectangle behind its drawing, or the markup unchanged when it has no size."""
    root = etree.fromstring(svg.encode("utf-8"), etree.XMLParser(resolve_entities=False, no_network=True))
    box = (root.get("viewBox") or "").replace(",", " ").split()
    try:
        if len(box) == 4:
            x, y, w, h = (float(v) for v in box)
        else:
            width_match = _NUMBER.match(root.get("width") or "")
            height_match = _NUMBER.match(root.get("height") or "")
            if width_match is None or height_match is None:
                return svg
            x, y, w, h = 0.0, 0.0, float(width_match.group(1)), float(height_match.group(1))
    except ValueError:
        return svg
    if w <= 0 or h <= 0:
        return svg
    pad = max(w, h) * PADDING
    root.set("viewBox", f"{x - pad:g} {y - pad:g} {w + 2 * pad:g} {h + 2 * pad:g}")
    for name, whole, added in (("width", w, 2 * pad), ("height", h, 2 * pad)):
        match = _NUMBER.match(root.get(name) or "")
        if match:
            root.set(name, f"{float(match.group(1)) * (whole + added) / whole:g}")
    rect = etree.Element(f"{{{SVG_NS}}}rect", x=f"{x - pad:g}", y=f"{y - pad:g}",
                         width=f"{w + 2 * pad:g}", height=f"{h + 2 * pad:g}", fill=band_hex)
    root.insert(0, rect)
    return etree.tostring(root, encoding="unicode")


def plate_resolved(image: ResolvedImage, band_hex: str) -> ResolvedImage:
    """A resolved logo on a plate of `band_hex`.

    Args:
        image: The logo, as `load_org_logo` resolved it (raster `data` or sanitised `svg`).
        band_hex: The plate colour, `#rrggbb`.

    Returns:
        The plated picture, or `image` unchanged when the colour is invalid or the picture cannot be plated.
    """
    if not _HEX.match(band_hex):
        return image
    if image.svg is not None:
        try:
            return replace(image, svg=_plate_svg(image.svg, band_hex))
        except etree.XMLSyntaxError:
            return image
    plated = plate_raster_bytes(image.data, band_hex)
    if plated is image.data:
        return image
    with PilImage.open(io.BytesIO(plated)) as opened:
        return replace(image, data=plated, width_px=opened.size[0], height_px=opened.size[1])


__all__ = ["PADDING", "plate_raster_bytes", "plate_resolved"]
