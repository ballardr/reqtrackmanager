"""
Module: services.report_odf

The shared ODF (OpenDocument) package layer behind the ODT and ODS report renderers (`report_odt`, `report_ods`):
the zip container, the manifest, document metadata, XML text and attribute escaping, and raster image sniffing.

Responsibilities:
- `OdfPackage`: a zip with the `mimetype` entry first and stored (what ODF readers sniff), `meta.xml`, any
  pictures, and a manifest listing every part.
- `xml_text`: model text as ODF paragraph content (tabs, line breaks and runs of spaces kept; characters that
  are invalid in XML 1.0 dropped; everything escaped).
- `xml_attr`, `length_cm`, `colour`: the only ways a value reaches an attribute.
- `raster_info`: the sniffed media type and pixel size of an image's bytes.

Design decisions:
- **Written directly, not through `odfpy`.** A library such as `odfpy` builds the whole document
  as an object tree: 100,000 rows of six cells took 1.1 GB and 45 seconds, and a background run allows five times
  that. The XML an ODT or ODS needs here is small and well defined, so each renderer streams it as text through
  one escaping choke point (`xml_text` for content, `xml_attr` for attributes), which also leaves no dependency.
- **Nothing reaches the XML unescaped.** Every string goes through `xml_text` or `xml_attr`; a colour is checked
  as six hex digits; a length is formatted from a number; an image's media type is sniffed from its bytes, never
  taken from the model. The package holds no macro, script, link, external object or field code.
- **Metadata is fixed**: the title, a fixed generator and creator and the creation time (UTC); never a person.

Dependencies: Pillow (image sniffing), `services.report_docx.clean_text` (the one XML-invalid-character filter).
"""

from __future__ import annotations

import io
import re
import zipfile
from collections.abc import Iterable
from datetime import UTC, datetime
from xml.sax.saxutils import escape, quoteattr

from PIL import Image as PilImage

from app.services.branding import DEFAULT_ACCENT_COLOR_HEX
from app.services.report_docx import DOCX_AUTHOR, clean_text

#: ODF version written. 1.2 is read by every current office suite (LibreOffice, Word, OnlyOffice, Google Docs).
ODF_VERSION = "1.2"
#: Namespaces every part declares (unused ones are harmless).
NAMESPACES = {
    "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
    "style": "urn:oasis:names:tc:opendocument:xmlns:style:1.0",
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
    "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
    "draw": "urn:oasis:names:tc:opendocument:xmlns:drawing:1.0",
    "fo": "urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0",
    "xlink": "http://www.w3.org/1999/xlink",
    "dc": "http://purl.org/dc/elements/1.1/",
    "meta": "urn:oasis:names:tc:opendocument:xmlns:meta:1.0",
    "svg": "urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0",
    "config": "urn:oasis:names:tc:opendocument:xmlns:config:1.0",
    "manifest": "urn:oasis:names:tc:opendocument:xmlns:manifest:1.0",
}
#: The one font face every part declares.
FONT_FACES = (
    '<office:font-face-decls><style:font-face style:name="Arial" svg:font-family="Arial" '
    'style:font-family-generic="swiss"/></office:font-face-decls>'
)
MIME_ODT = "application/vnd.oasis.opendocument.text"
MIME_ODS = "application/vnd.oasis.opendocument.spreadsheet"
XML_DECLARATION = '<?xml version="1.0" encoding="UTF-8"?>\n'

_HEX = re.compile(r"^#?([0-9A-Fa-f]{6})$")
_SPACE_RUN = re.compile(r" {2,}|^ | $")
_IMAGE_TYPES = {"PNG": ("image/png", "png"), "JPEG": ("image/jpeg", "jpg"), "GIF": ("image/gif", "gif")}


def namespace_attrs(*prefixes: str) -> str:
    """The `xmlns:` declarations for `prefixes`, as attribute text for a root element."""
    return " ".join(f'xmlns:{p}="{NAMESPACES[p]}"' for p in prefixes)


def xml_attr(value: str) -> str:
    """`value` as a quoted, escaped attribute value (including the quotes)."""
    return quoteattr(clean_text(value))


def colour(value: str | None, default: str = DEFAULT_ACCENT_COLOR_HEX) -> str:
    """`value` as `#RRGGBB` when it is six hex digits, else `default` (the value ends up in an XML attribute)."""
    match = _HEX.match(value or "") or _HEX.match(default)
    return "#" + match.group(1).upper() if match else "#000000"


def length_cm(value: float) -> str:
    """A length in centimetres, as ODF writes it (`3.5cm`)."""
    return f"{value:.3f}cm"


def xml_text(value: str) -> str:
    """Model text as the content of an ODF paragraph.

    ODF collapses whitespace, so a tab, a line break and a run of spaces (or a leading or trailing space) are
    written as their elements, which keeps text exactly as the record held it. Characters invalid in XML 1.0 are
    dropped and `& < >` escaped.

    Args:
        value: Untrusted text.

    Returns:
        Markup safe to put between `text:p` tags.
    """
    pieces: list[str] = []
    for line_number, line in enumerate(clean_text(value).replace("\r\n", "\n").replace("\r", "\n").split("\n")):
        if line_number:
            pieces.append("<text:line-break/>")
        for part_number, part in enumerate(line.split("\t")):
            if part_number:
                pieces.append("<text:tab/>")
            pieces.append(_SPACE_RUN.sub(lambda m: f'<text:s text:c="{len(m.group())}"/>', escape(part)))
    return "".join(pieces)


def raster_info(data: bytes) -> tuple[str, str, int, int] | None:
    """The media type, file extension and pixel size of raster bytes this package embeds, sniffed from the bytes.

    Returns:
        `(media_type, extension, width_px, height_px)`, or `None` when the bytes are not a PNG, JPEG or GIF.
    """
    try:
        with PilImage.open(io.BytesIO(data)) as image:
            kind = _IMAGE_TYPES.get(image.format or "")
            width, height = image.size
    except Exception:  # noqa: BLE001 - not an image: skipped, as in the other renderers
        return None
    if kind is None or width <= 0 or height <= 0:
        return None
    return kind[0], kind[1], width, height


class OdfPackage:
    """An ODF zip being written to memory.

    Parts are added with `add`; `finish` writes the manifest and returns the file. The `mimetype` entry is
    written first and stored, as the format requires.
    """

    def __init__(self, mimetype: str, title: str) -> None:
        self._mimetype = mimetype
        self._title = title
        self._buffer = io.BytesIO()
        self._zip = zipfile.ZipFile(self._buffer, "w", zipfile.ZIP_DEFLATED)
        self._zip.writestr(zipfile.ZipInfo("mimetype"), mimetype, compress_type=zipfile.ZIP_STORED)
        self._parts: list[tuple[str, str]] = [("/", mimetype)]
        self._pictures = 0

    def add(self, path: str, media_type: str, content: bytes | str | Iterable[str]) -> None:
        """Adds a part. `content` may be text chunks (written one at a time, so a large part is never held twice)."""
        if isinstance(content, bytes):
            self._zip.writestr(path, content)
        elif isinstance(content, str):
            self._zip.writestr(path, content.encode("utf-8"))
        else:
            with self._zip.open(path, "w") as part:
                for chunk in content:
                    part.write(chunk.encode("utf-8"))
        self._parts.append((path, media_type))

    def add_picture(self, data: bytes, media_type: str, extension: str) -> str:
        """Adds an image under `Pictures/` and returns its path (what `draw:image` links to)."""
        self._pictures += 1
        path = f"Pictures/image{self._pictures}.{extension}"
        self.add(path, media_type, data)
        return path

    def _meta(self) -> str:
        created = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        return (
            f'{XML_DECLARATION}<office:document-meta {namespace_attrs("office", "dc", "meta")} office:version="{ODF_VERSION}">'
            f"<office:meta><dc:title>{escape(clean_text(self._title))}</dc:title>"
            f"<meta:generator>{DOCX_AUTHOR}</meta:generator><meta:initial-creator>{DOCX_AUTHOR}</meta:initial-creator>"
            f"<dc:creator>{DOCX_AUTHOR}</dc:creator><meta:creation-date>{created}</meta:creation-date>"
            f"<dc:date>{created}</dc:date></office:meta></office:document-meta>"
        )

    def finish(self) -> bytes:
        """Writes `meta.xml` and the manifest and returns the finished file."""
        self.add("meta.xml", "text/xml", self._meta())
        entries = "".join(
            f'<manifest:file-entry manifest:full-path={quoteattr(path)} manifest:media-type={quoteattr(media_type)}'
            + (f' manifest:version="{ODF_VERSION}"' if path == "/" else "")
            + "/>"
            for path, media_type in self._parts
        )
        manifest = (
            f'{XML_DECLARATION}<manifest:manifest {namespace_attrs("manifest")} manifest:version="{ODF_VERSION}">'
            f'{entries}<manifest:file-entry manifest:full-path="META-INF/manifest.xml" manifest:media-type="text/xml"/>'
            "</manifest:manifest>"
        )
        self._zip.writestr("META-INF/manifest.xml", manifest.encode("utf-8"))
        self._zip.close()
        return self._buffer.getvalue()


__all__ = [
    "FONT_FACES", "MIME_ODS", "MIME_ODT", "NAMESPACES", "ODF_VERSION", "XML_DECLARATION", "OdfPackage", "colour", "length_cm",
    "namespace_attrs", "raster_info", "xml_attr", "xml_text",
]
