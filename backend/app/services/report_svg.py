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
  module's own diagram code, so the markup is never trusted. The sanitiser refuses an `ENTITY` declaration and
  any `DOCTYPE` other than the bare reference Illustrator, Affinity and Inkscape write (`<!DOCTYPE svg PUBLIC
  "..." "...">`, no internal subset, so nothing can be declared and expanded), parses with entity resolution,
  DTD loading and network access off, drops every element and attribute outside an allow-list (no `script`,
  `foreignObject`, `style` element, event handler), keeps `href` only when it points at an element of the same
  document (`#id`) and refuses any value with an external `url(...)` or a script. Each renderer calls it again, so a
  figure that skipped one caller's check cannot reach another.
- **A bitmap inside the SVG is kept only as an embedded raster.** Logos from vector editors often carry one. An `image`
  element survives only when its `href` is a `data:image/png|jpeg|gif|webp;base64,...` URI; the bytes are decoded,
  held to the pixel limit and re-encoded without metadata by `report_raster.normalise_raster` (the treatment an
  uploaded picture gets, so it is no riskier than uploading that picture), and the element gets the new URI. An
  `image` that points anywhere else (a URL, a file path, `image/svg+xml`, which could nest another document) or
  cannot be decoded is dropped, so the rest of the figure still prints. Count, pixels and total size are capped.
- **Text needs a font.** `resvg-py` draws no text without fonts, so the bundled DejaVu directory is always
  passed and system fonts are skipped, which also makes the output the same on every host.
- A figure that cannot be drawn is skipped by the renderer, as a bad raster image is: it never fails a report.

Dependencies: `lxml`, `svglib`, `resvg-py`, ReportLab, `report_raster` (embedded bitmaps); the font directory is
`app/assets/fonts`.
"""

from __future__ import annotations

import base64
import binascii
import io
import re
from dataclasses import dataclass
from pathlib import Path

import resvg_py
from lxml import etree
from PIL import Image as PilImage
from reportlab.platypus import Flowable
from reportlab.platypus import Image as RlImage
from svglib.svglib import svg2rlg

from app.services.report_raster import ImageRejectedError, normalise_raster

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
#: Largest SVG source accepted, in characters.
MAX_SVG_CHARS = 1_000_000
#: Embedded bitmaps: how many one SVG may carry, the most pixels of each and of all together, and the most characters
#: of base64 they may add to the source (on top of `MAX_SVG_CHARS` for the markup itself).
MAX_EMBEDDED_IMAGES = 20
MAX_EMBEDDED_PIXELS = 25_000_000
MAX_EMBEDDED_TOTAL_PIXELS = 60_000_000
MAX_EMBEDDED_CHARS = 16_000_000
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
#: The only DOCTYPE accepted: the standard reference every vector editor writes, with no internal subset `[...]`. The
#: parser neither loads nor fetches the DTD it names, and the sanitised copy never carries the DOCTYPE on.
_PLAIN_DOCTYPE = re.compile(r'<!doctype\s+svg(?:\s+public\s+"[^"<>\[\]]*"\s+"[^"<>\[\]]*"|\s+system\s+"[^"<>\[\]]*")?\s*>', re.IGNORECASE)
_KEPT = _ELEMENTS | {"image"}
_RASTER_DATA_URI = re.compile(r"^data:image/(?:png|jpe?g|gif|webp);base64,([A-Za-z0-9+/=\s]+)$", re.IGNORECASE)
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
        UnsafeSvgError: The markup is too large, declares an entity or a DOCTYPE with an internal subset, is not well-formed, is not an
            `svg` document, or an attribute value is harmful (script, data or external `url(...)`).
    """
    if len(source) > MAX_SVG_CHARS + MAX_EMBEDDED_CHARS:
        raise UnsafeSvgError("The SVG is too large.")
    lowered = source.lower()
    if "<!entity" in lowered or lowered.count("<!doctype") != len(_PLAIN_DOCTYPE.findall(source)):
        raise UnsafeSvgError("The SVG may not declare an entity or a DOCTYPE with its own declarations.")
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
    embedded = _Embedded()
    _clean(root, embedded)
    result = etree.tostring(root, encoding="unicode")
    if len(result) - embedded.chars > MAX_SVG_CHARS:
        raise UnsafeSvgError("The SVG is too large.")
    return result


@dataclass
class _Embedded:
    """What the embedded bitmaps of one SVG have used so far (against the caps)."""

    count: int = 0
    pixels: int = 0
    chars: int = 0


def _embedded_image(image: etree._Element, used: _Embedded) -> bool:
    """Replaces an `image` element's `href` with a clean data URI.

    Args:
        image: An SVG `image` element.
        used: Running totals for the document, updated here.

    Returns:
        `True` when the image was kept; `False` when it must be dropped (no `data:` raster href, an undecodable
        bitmap, or over the count cap).

    Raises:
        UnsafeSvgError: A bitmap has more pixels than allowed, so the whole SVG is refused.
    """
    href = image.get("href") or image.get(f"{{{XLINK_NS}}}href") or ""
    match = _RASTER_DATA_URI.match(href.strip())
    if match is None or used.count >= MAX_EMBEDDED_IMAGES:
        return False
    try:
        raw = base64.b64decode(re.sub(r"\s+", "", match.group(1)), validate=True)
        with PilImage.open(io.BytesIO(raw)) as probe:
            pixels = probe.size[0] * probe.size[1]
        if pixels > MAX_EMBEDDED_PIXELS or used.pixels + pixels > MAX_EMBEDDED_TOTAL_PIXELS:
            raise UnsafeSvgError("The SVG embeds a picture with too many pixels.")
        clean = normalise_raster(raw)
    except UnsafeSvgError:
        raise
    except PilImage.DecompressionBombError:
        raise UnsafeSvgError("The SVG embeds a picture with too many pixels.") from None
    except ImageRejectedError as exc:
        if "too many pixels" in str(exc):
            raise UnsafeSvgError("The SVG embeds a picture with too many pixels.") from None
        return False
    except (binascii.Error, ValueError, OSError):
        return False
    uri = f"data:{clean.content_type};base64,{base64.b64encode(clean.data).decode('ascii')}"
    for name in (f"{{{XLINK_NS}}}href", "href"):
        if name in image.attrib:
            del image.attrib[name]
    image.set("href", uri)
    used.count += 1
    used.pixels += pixels
    used.chars += len(uri)
    return True


def _clean(element: etree._Element, embedded: _Embedded) -> None:
    """Removes disallowed children and attributes below (and on) `element`, recursively.

    Args:
        element: The element to clean in place.
        embedded: Running totals for the embedded bitmaps of the whole document.

    Raises:
        UnsafeSvgError: An attribute is harmful, or an embedded bitmap is over its limits.
    """
    is_image = _local(element.tag) == "image"
    for child in list(element):
        tag = child.tag
        if not isinstance(tag, str) or etree.QName(tag).namespace != SVG_NS or _local(tag) not in _KEPT:
            element.remove(child)  # comments and processing instructions were removed by the parser
            continue
        if _local(tag) == "image" and not _embedded_image(child, embedded):
            element.remove(child)
            continue
        _clean(child, embedded)
    if is_image:
        for child in list(element):  # an image has no children worth keeping
            element.remove(child)
    for name in list(element.attrib):
        local = _local(name)
        namespace = etree.QName(name).namespace
        value = str(element.attrib[name])
        allowed = namespace in (None, XLINK_NS) and local in _ATTRIBUTES and not local.lower().startswith("on")
        own_data = is_image and local == "href" and value.startswith("data:image/")  # set by `_embedded_image`
        if allowed and local == "href":
            allowed = value.startswith("#") or own_data
        if allowed and local == "style":
            allowed = bool(_STYLE_VALUE.match(value))
        if allowed and not own_data and (_EXTERNAL_URL.search(value) or _HARMFUL.search(value)):
            raise UnsafeSvgError("The SVG holds a script, a data URI or an external reference.")
        if not allowed:
            del element.attrib[name]
        elif namespace == XLINK_NS:  # keep the plain name so renderers that only know `href` still resolve it
            del element.attrib[name]
            element.attrib[local] = value


def svg_png(svg: str, *, width_px: int = 1200, zoom: float | None = None, background: str | None = "#ffffff") -> bytes:
    """Rasterises an SVG to PNG with `resvg-py`, drawing text with the bundled font.

    Args:
        svg: SVG markup (sanitised here first).
        width_px: Width of the image in pixels; ignored when `zoom` is given.
        zoom: Pixels per SVG user unit (the SVG's own size scaled), for a figure whose size matters more than a
            fixed pixel width, such as an inline equation.
        background: A CSS colour behind the drawing, or `None` for a transparent PNG.

    Returns:
        PNG bytes.

    Raises:
        UnsafeSvgError: The markup is not acceptable.
        ValueError: `resvg` could not render it.
    """
    clean = sanitize_svg(svg)
    font_dirs = [str(FONT_DIR)]
    if zoom is not None:
        return resvg_py.svg_to_bytes(
            svg_string=clean, zoom=zoom, skip_system_fonts=True, font_dirs=font_dirs, font_family="DejaVu Sans",
            background=background,
        )
    return resvg_py.svg_to_bytes(
        svg_string=clean, width=width_px, skip_system_fonts=True, font_dirs=font_dirs, font_family="DejaVu Sans",
        background=background,
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
