"""
Module: services.report_shapes

The `shape` layout block: a coloured rectangle, ellipse, line or arrow (or an author's own SVG) that sits in line with
the text, beside it, or behind or in front of it.

Responsibilities:
- Name the kinds, colour tokens and limits the tree validator, the block schema and the text format share.
- `shape_svg`: draw a preset shape as SVG markup at its printed size, in the colours the run resolved.
- `colour_hex`: resolve a colour token (`accent`, `white`, `black`) or a hex colour to `#rrggbb`.
- `svg_problem`: why an author's SVG cannot be used (the report image sanitiser plus a size check), or `None`.

Design decisions:
- **A shape is a generated picture.** The evaluator hands the SVG to the report model's `Image`, so a shape inherits the
  placements, anchors, offsets and layering the four document formats already draw for pictures (vector in PDF and HTML,
  a transparent PNG in Word and OpenDocument), and a layer drawn later in the document is drawn above an earlier one.
  Native Word and ODT shape objects were not built: they add a second drawing path per format for a flat colour.
- **Nothing the author types becomes markup.** A preset is built here from validated numbers and a validated colour; a
  custom SVG is allow-listed by `report_svg.sanitize_svg`, which every renderer applies again.
- **Sizes are exact.** A preset has an explicit width and height in cm or mm (no percentage: the size of the text area
  is unknown when the picture is drawn, and a stretched outline or corner would print wrongly). A shape wider than the
  text is scaled down with its proportions kept.
- A line or arrow is drawn in the outline colour across the middle of its box; its height is the arrowhead's room.

Dependencies: `lxml`, `services.report_svg`.
"""

from __future__ import annotations

import re
from typing import Any

from lxml import etree

from app.services.report_svg import MAX_SVG_CHARS, UnsafeSvgError, sanitize_svg

#: The kinds of preset, and `custom` for an author's SVG.
SHAPE_PRESETS = ("rectangle", "rounded", "ellipse", "triangle", "line", "arrow")
SHAPE_KINDS = (*SHAPE_PRESETS, "custom")
#: Kinds drawn as a stroke only: they have an outline colour and width and no fill.
LINE_KINDS = ("line", "arrow")
#: Colour names a fill or outline may use besides a hex colour; `none` leaves it unpainted.
COLOUR_TOKENS = ("accent", "white", "black", "none")
SHAPE_UNITS = ("cm", "mm")
#: Bounds of the outline width, in mm.
OUTLINE_WIDTH_MM = (0.1, 20.0)
DEFAULT_OUTLINE_WIDTH_MM = 0.5
DEFAULT_FILL = "accent"
DEFAULT_LINE_COLOUR = "black"
#: Bounds of a preset's width and height, in cm.
SHAPE_SIZE_CM = (0.1, 100.0)
#: Most characters of a custom SVG's source stored in a layout.
MAX_SHAPE_SVG_CHARS = 50_000

_HEX = re.compile(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})")
_PX_PER_CM = 96 / 2.54
_PX_PER_MM = _PX_PER_CM / 10


def colour_problem(value: Any) -> str | None:
    """Why `value` is not a colour a shape may use (`None` when it is).

    Args:
        value: A hex colour (`#rgb` or `#rrggbb`) or one of `COLOUR_TOKENS`.
    """
    if isinstance(value, str) and (value in COLOUR_TOKENS or _HEX.fullmatch(value)):
        return None
    return f"Must be a hex colour such as #475569, or one of: {', '.join(COLOUR_TOKENS)}."


def colour_hex(value: str, accent: str) -> str | None:
    """A validated colour token or hex colour as `#rrggbb`, or `None` for `none`.

    Args:
        value: The colour as the layout stores it (already checked by `colour_problem`).
        accent: The organisation's report accent as `#rrggbb`, for `accent`.
    """
    if value == "none":
        return None
    if value == "accent":
        return colour_hex(accent, accent)
    if value == "white":
        return "#ffffff"
    if value == "black":
        return "#000000"
    if len(value) == 4:  # #rgb
        value = "#" + "".join(c * 2 for c in value[1:])
    return value.lower()


def svg_problem(source: Any) -> str | None:
    """Why `source` cannot be a custom shape (`None` when it can).

    Args:
        source: The author's SVG markup.
    """
    if not isinstance(source, str) or not source.strip():
        return "Paste the SVG markup."
    if len(source) > MAX_SHAPE_SVG_CHARS:
        return f"The SVG is too long ({len(source)} characters; the limit is {MAX_SHAPE_SVG_CHARS})."
    if len(source) > MAX_SVG_CHARS:  # defensive: the shape limit is the tighter one
        return "The SVG is too large."
    try:
        clean = sanitize_svg(source)
    except UnsafeSvgError as exc:
        return str(exc)
    root = etree.fromstring(clean.encode("utf-8"))
    if "viewBox" not in root.attrib and not ("width" in root.attrib and "height" in root.attrib):
        return "Give the SVG a viewBox, or a width and a height on its svg element, so it has a shape to scale."
    return None


def _num(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def shape_svg(node: dict[str, Any], *, accent: str) -> str:
    """The SVG of a preset shape block, at its printed size.

    Args:
        node: A validated `shape` node whose `shape` is in `SHAPE_PRESETS`, with `width` and `height`.
        accent: The organisation's report accent as `#rrggbb`.

    Returns:
        SVG markup: a root sized in pixels (96 per inch) and a drawing inside it that keeps clear of the edge by half the
        outline, so a thick outline is not clipped.
    """
    kind = node["shape"]
    width = node["width"] / 10 if node.get("width_unit") == "mm" else node["width"]
    height = node["height"] / 10 if node.get("height_unit") == "mm" else node["height"]
    w, h = width * _PX_PER_CM, height * _PX_PER_CM
    line_kind = kind in LINE_KINDS
    stroke = colour_hex(node.get("outline", DEFAULT_LINE_COLOUR if line_kind else "none"), accent)
    fill = None if line_kind else colour_hex(node.get("fill", DEFAULT_FILL), accent)
    sw = node.get("outline_width", DEFAULT_OUTLINE_WIDTH_MM) * _PX_PER_MM if stroke else 0.0
    half = sw / 2
    paint = f'fill="{fill or "none"}"' + (f' stroke="{stroke}" stroke-width="{_num(sw)}"' if stroke else "")
    x0, y0, x1, y1 = half, half, w - half, h - half
    if kind == "rectangle":
        drawing = f'<rect x="{_num(x0)}" y="{_num(y0)}" width="{_num(x1 - x0)}" height="{_num(y1 - y0)}" {paint}/>'
    elif kind == "rounded":
        radius = min(x1 - x0, y1 - y0) * 0.2
        drawing = (
            f'<rect x="{_num(x0)}" y="{_num(y0)}" width="{_num(x1 - x0)}" height="{_num(y1 - y0)}" '
            f'rx="{_num(radius)}" ry="{_num(radius)}" {paint}/>'
        )
    elif kind == "ellipse":
        drawing = f'<ellipse cx="{_num(w / 2)}" cy="{_num(h / 2)}" rx="{_num((x1 - x0) / 2)}" ry="{_num((y1 - y0) / 2)}" {paint}/>'
    elif kind == "triangle":
        points = f"{_num(w / 2)},{_num(y0)} {_num(x1)},{_num(y1)} {_num(x0)},{_num(y1)}"
        drawing = f'<polygon points="{points}" {paint}/>'
    elif kind == "line":
        drawing = f'<line x1="0" y1="{_num(h / 2)}" x2="{_num(w)}" y2="{_num(h / 2)}" stroke="{stroke or "none"}" stroke-width="{_num(sw)}"/>'
    else:  # arrow: a shaft and a filled head at the right whose height is the box's
        head = min(h, w / 2)
        colour = stroke or "none"
        drawing = (
            f'<line x1="0" y1="{_num(h / 2)}" x2="{_num(w - head / 2)}" y2="{_num(h / 2)}" stroke="{colour}" stroke-width="{_num(sw)}"/>'
            f'<polygon points="{_num(w)},{_num(h / 2)} {_num(w - head)},0 {_num(w - head)},{_num(h)}" fill="{colour}"/>'
        )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{_num(w)}" height="{_num(h)}" viewBox="0 0 {_num(w)} {_num(h)}">'
        f"{drawing}</svg>"
    )


__all__ = [
    "COLOUR_TOKENS", "DEFAULT_FILL", "DEFAULT_LINE_COLOUR", "DEFAULT_OUTLINE_WIDTH_MM", "LINE_KINDS", "MAX_SHAPE_SVG_CHARS",
    "OUTLINE_WIDTH_MM", "SHAPE_KINDS", "SHAPE_PRESETS", "SHAPE_SIZE_CM", "SHAPE_UNITS", "colour_hex", "colour_problem",
    "shape_svg", "svg_problem",
]
