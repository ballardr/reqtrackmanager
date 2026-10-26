"""
Module: services.report_svg

Safe handling of SVG figures (diagrams, equations) that a report embeds: allow-listing the markup, drawing
it into a PDF as vector, and rasterising it for Word.

Responsibilities:
- `sanitize_svg`: parse untrusted SVG markup and return a copy holding only allow-listed elements and
  attributes; refuse anything that could fetch, execute or expand.
- `svg_flowable`: a ReportLab flowable for the PDF (vector through `svglib`, a PNG through `resvg-py` if
  `svglib` cannot draw it).
- `svg_png`: PNG bytes for Word (`python-docx` cannot embed SVG).

Design decisions:
- **Untrusted until sanitised, sanitised by every consumer.** A figure may be built from record text or a
  module's own diagram code, so the markup is never trusted. The sanitiser refuses a `DOCTYPE`/`ENTITY`
  (entity expansion), parses with entity resolution, DTD loading and network access off, drops every element
  and attribute outside an allow-list (no `script`, `foreignObject`, `image`, `style` element, event
  handler), keeps `href` only when it points at an element of the same document (`#id`) and refuses any
  value with an external `url(...)`, a script or data URI. Each renderer calls it again, so a figure that
  skipped one caller's check cannot reach another.
- **Text needs a font.** `resvg-py` draws no text without fonts, so the bundled DejaVu directory is always
  passed and system fonts are skipped, which also makes the output the same on every host.
- A figure that cannot be drawn is skipped by the renderer, as a bad raster image is: it never fails a report.

Dependencies: `lxml`, `svglib`, `resvg-py`, ReportLab; the font directory is `app/assets/fonts`.
"""

from __future__ import annotations

import io
import re
from pathlib import Path

import resvg_py
from lxml import etree
from reportlab.platypus import Flowable
from reportlab.platypus import Image as RlImage
from svglib.svglib import svg2rlg

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
#: Largest SVG source accepted, in characters.
MAX_SVG_CHARS = 1_000_000
FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"

_ELEMENTS = frozenset({
    "svg", "g", "defs", "symbol", "use", "path", "rect", "circle", "ellipse", "line", "polyline", "polygon", "text",
    "tspan", "title", "desc", "linearGradient", "radialGradient", "stop", "clipPath", "marker",
})
_ATTRIBUTES = frozenset({
    "id", "x", "y", "x1", "y1", "x2", "y2", "cx", "cy", "r", "rx", "ry", "fx", "fy", "width", "height", "d", "points",
    "transform", "viewBox", "preserveAspectRatio", "fill", "fill-opacity", "fill-rule", "stroke", "stroke-width",
    "stroke-opacity", "stroke-linecap", "stroke-linejoin", "stroke-dasharray", "stroke-dashoffset",
    "stroke-miterlimit", "opacity", "font-family", "font-size", "font-weight", "font-style", "text-anchor",
    "dominant-baseline", "letter-spacing", "dx", "dy", "offset", "stop-color", "stop-opacity", "gradientUnits",
    "gradientTransform", "spreadMethod", "clip-path", "clipPathUnits", "marker-start", "marker-mid", "marker-end",
    "markerWidth", "markerHeight", "markerUnits", "refX", "refY", "orient", "version", "style", "href",
})
_STYLE_VALUE = re.compile(r"^[A-Za-z0-9 \t:;#.,%()\-_'\"/]*$")
_EXTERNAL_URL = re.compile(r"url\(\s*['\"]?\s*(?!#)", re.IGNORECASE)
_HARMFUL = re.compile(r"javascript:|data:|expression\(|@import|<|>", re.IGNORECASE)


class UnsafeSvgError(ValueError):
    """The SVG is malformed, too large or contains something that is not allowed."""


def _local(name: object) -> str:
    return etree.QName(name).localname if isinstance(name, str) else ""


def sanitize_svg(source: str) -> str:
    """Returns `source` reduced to allow-listed elements and attributes.

    Args:
        source: SVG markup (untrusted).

    Returns:
        The sanitised SVG as a string, with an `xmlns` declaration on the root.

    Raises:
        UnsafeSvgError: The markup is too large, declares a DOCTYPE or entity, is not well-formed, is not an
            `svg` document, or an attribute value is harmful (script, data or external `url(...)`).
    """
    if len(source) > MAX_SVG_CHARS:
        raise UnsafeSvgError("The SVG is too large.")
    lowered = source.lower()
    if "<!doctype" in lowered or "<!entity" in lowered:
        raise UnsafeSvgError("The SVG may not declare a DOCTYPE or an entity.")
    parser = etree.XMLParser(
        resolve_entities=False, no_network=True, load_dtd=False, dtd_validation=False, huge_tree=False,
        remove_comments=True, remove_pis=True,
    )
    try:
        root = etree.fromstring(source.encode("utf-8"), parser)
    except (etree.XMLSyntaxError, ValueError) as exc:
        raise UnsafeSvgError("The SVG is not well-formed.") from exc
    if etree.QName(root).namespace != SVG_NS or _local(root.tag) != "svg":
        raise UnsafeSvgError("The document is not an SVG.")
    _clean(root)
    return etree.tostring(root, encoding="unicode")


def _clean(element: etree._Element) -> None:
    """Removes disallowed children and attributes below (and on) `element`, recursively."""
    for child in list(element):
        tag = child.tag
        if not isinstance(tag, str) or etree.QName(tag).namespace != SVG_NS or _local(tag) not in _ELEMENTS:
            element.remove(child)  # comments and processing instructions were removed by the parser
            continue
        _clean(child)
    for name in list(element.attrib):
        local = _local(name)
        namespace = etree.QName(name).namespace
        value = str(element.attrib[name])
        allowed = namespace in (None, XLINK_NS) and local in _ATTRIBUTES and not local.lower().startswith("on")
        if allowed and local == "href":
            allowed = value.startswith("#")
        if allowed and local == "style":
            allowed = bool(_STYLE_VALUE.match(value))
        if allowed and (_EXTERNAL_URL.search(value) or _HARMFUL.search(value)):
            raise UnsafeSvgError("The SVG holds a script, a data URI or an external reference.")
        if not allowed:
            del element.attrib[name]
        elif namespace == XLINK_NS:  # keep the plain name so renderers that only know `href` still resolve it
            del element.attrib[name]
            element.attrib[local] = value


def svg_png(svg: str, *, width_px: int = 1200) -> bytes:
    """Rasterises an SVG to PNG with `resvg-py`, drawing text with the bundled font.

    Args:
        svg: SVG markup (sanitised here first).
        width_px: Width of the image in pixels.

    Returns:
        PNG bytes.

    Raises:
        UnsafeSvgError: The markup is not acceptable.
        ValueError: `resvg` could not render it.
    """
    return resvg_py.svg_to_bytes(
        svg_string=sanitize_svg(svg), width=width_px, skip_system_fonts=True, font_dirs=[str(FONT_DIR)],
        font_family="DejaVu Sans", background="#ffffff",
    )


def svg_flowable(svg: str, max_width_pt: float) -> Flowable | None:
    """A ReportLab flowable for an SVG, at most `max_width_pt` wide, or `None` if it cannot be drawn.

    Args:
        svg: SVG markup (sanitised here first).
        max_width_pt: The widest the figure may be, in points.

    Returns:
        A vector `Drawing` through `svglib`; a PNG image if `svglib` raises or draws nothing; `None` if the
        markup is not acceptable or neither path can draw it.
    """
    try:
        clean = sanitize_svg(svg)
    except UnsafeSvgError:
        return None
    try:
        drawing = svg2rlg(io.StringIO(clean))
        if drawing is not None and drawing.width > 0 and drawing.height > 0 and drawing.contents:
            if drawing.width > max_width_pt:
                scale = max_width_pt / drawing.width
                drawing.scale(scale, scale)
                drawing.width *= scale
                drawing.height *= scale
            return drawing
    except Exception:  # noqa: BLE001 - svglib raises many types on exotic markup; the PNG path below is the fallback
        pass
    try:
        image = RlImage(io.BytesIO(svg_png(clean)))
    except Exception:  # noqa: BLE001 - a figure that cannot be drawn must never break report generation
        return None
    if image.imageWidth > max_width_pt:
        image.drawHeight = image.imageHeight * max_width_pt / float(image.imageWidth)
        image.drawWidth = max_width_pt
    return image


__all__ = ["MAX_SVG_CHARS", "UnsafeSvgError", "sanitize_svg", "svg_flowable", "svg_png"]
