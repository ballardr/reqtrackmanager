"""
Module: services.report_font_parts

Writes the font declarations Word and OpenDocument need for an administrator-provided family, and optionally embeds its
font files, into a finished `.docx` or `.odt`.

Responsibilities:
- `embed_in_docx`: add each extra family to `word/fontTable.xml` (alternate name, family kind, pitch) and, when asked, the
  obfuscated `.odttf` parts, their relationships, the content type and `w:embedTrueTypeFonts` in `word/settings.xml`.
- `embed_in_odt`: add a `style:font-face` per extra family to `content.xml` and `styles.xml` and, when asked, the
  `Fonts/` entries, their `svg:font-face-src` and manifest rows.
- `fallback_name`: the common font Word and OpenDocument fall back to for a generic family.

Design decisions:
- These work on finished files, so a renderer needs no knowledge of embedding: it names the family, and the layout setting
  decides whether this runs with `embed=True`.
- Only extra families are touched. The four bundled families are named for Arial, Times New Roman, Courier New and
  DejaVu Sans, which the spike found need no embedding to wrap the same.
- Only faces the family really has a file for and the document uses are embedded, whole: subsetting needs a font library
  the project does not ship, so the file grows by the faces' size (the layout setting's help says so). A face whose
  licence forbids embedding never reaches here (the directory scan refuses it).
- The `.odttf` obfuscation key is derived from the family key and style, so the same document always gives the same bytes.
- Element order follows the Word schema (`w:font` children, and `w:embedTrueTypeFonts` among the settings), as Word is
  stricter about it than LibreOffice.

Dependencies: lxml, `report_fonts`.
"""

from __future__ import annotations

import io
import uuid
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass

from lxml import etree

from app.services.report_fonts import STYLES, FontFamily

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
REL = "http://schemas.openxmlformats.org/package/2006/relationships"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"
_FONT_REL = f"{R}/font"
_ODTTF = "application/vnd.openxmlformats-officedocument.obfuscatedFont"
_NS_STYLE = "urn:oasis:names:tc:opendocument:xmlns:style:1.0"
_NS_SVG = "urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0"
_NS_OFFICE = "urn:oasis:names:tc:opendocument:xmlns:office:1.0"
_NS_XLINK = "http://www.w3.org/1999/xlink"
_NS_MANIFEST = "urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"
_KEY_NAMESPACE = uuid.UUID("6f1c5d2e-3a1b-4c55-9a4e-2f5a7d1c0b11")
_EMBED_TAG = {"regular": "embedRegular", "bold": "embedBold", "italic": "embedItalic", "bolditalic": "embedBoldItalic"}
# Word's schema order of the elements of CT_Settings that precede `embedTrueTypeFonts`.
_SETTINGS_BEFORE = (
    "writeProtection", "view", "zoom", "removePersonalInformation", "removeDateAndTime", "doNotDisplayPageBoundaries",
    "displayBackgroundShape", "printPostScriptOverText", "printFractionalCharacterWidth", "printFormsData",
)
_GENERIC_FALLBACK = {"sans-serif": "Arial", "serif": "Times New Roman", "monospace": "Courier New"}
_WORD_FAMILY = {"sans-serif": "swiss", "serif": "roman", "monospace": "modern"}


@dataclass(frozen=True)
class FontUse:
    """An extra family a document uses.

    Attributes:
        family: The family (its `word_name` and `generic` already include the administrator's settings).
        styles: The styles of it the document draws.
    """

    family: FontFamily
    styles: frozenset[str]


def fallback_name(generic: str) -> str:
    """The common font Word and OpenDocument fall back to for a generic family.

    Args:
        generic: `sans-serif`, `serif` or `monospace`.

    Returns:
        `Arial`, `Times New Roman` or `Courier New`.
    """
    return _GENERIC_FALLBACK[generic]


def _parser() -> etree.XMLParser:
    """A parser that reads our own generated parts and never resolves entities or fetches anything."""
    return etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False)


def _real_faces(use: FontUse) -> list[tuple[str, str]]:
    """The `(style, file path)` pairs to embed: used styles the family has a real file for."""
    return [
        (style, str(use.family.files[style]))
        for style in STYLES if style in use.styles and style in use.family.faces_found
    ]


def _obfuscate(data: bytes, key: uuid.UUID) -> bytes:
    """XORs the first 32 bytes with the key bytes in reverse order, as Word's `.odttf` parts require."""
    mask = bytes.fromhex(key.hex)[::-1]
    head = bytes(b ^ mask[i % 16] for i, b in enumerate(data[:32]))
    return head + data[32:]


def _w(tag: str) -> str:
    """The Clark name of a WordprocessingML element."""
    return f"{{{W}}}{tag}"


def _insert_font(root: etree._Element, use: FontUse, rels: list[tuple[str, str, uuid.UUID]]) -> None:
    """Replaces/creates the `w:font` entry for a family, with its embed references when `rels` has any."""
    name = use.family.word_name
    for existing in root.findall(_w("font")):
        if existing.get(_w("name")) == name:
            root.remove(existing)
    font = etree.SubElement(root, _w("font"))
    font.set(_w("name"), name)
    etree.SubElement(font, _w("altName")).set(_w("val"), fallback_name(use.family.generic))
    etree.SubElement(font, _w("charset")).set(_w("val"), "00")
    etree.SubElement(font, _w("family")).set(_w("val"), _WORD_FAMILY[use.family.generic])
    etree.SubElement(font, _w("pitch")).set(_w("val"), "fixed" if use.family.generic == "monospace" else "variable")
    for style, rid, key in rels:
        embed = etree.SubElement(font, _w(_EMBED_TAG[style]))
        embed.set(f"{{{R}}}id", rid)
        embed.set(_w("fontKey"), "{" + str(key).upper() + "}")


def _enable_embedding(root: etree._Element) -> None:
    """Adds `w:embedTrueTypeFonts` to the settings root in schema position, once."""
    if root.find(_w("embedTrueTypeFonts")) is not None:
        return
    element = etree.Element(_w("embedTrueTypeFonts"))
    position = 0
    for index, child in enumerate(root):
        if etree.QName(child).localname in _SETTINGS_BEFORE:
            position = index + 1
    root.insert(position, element)


def embed_in_docx(data: bytes, fonts: Sequence[FontUse], *, embed: bool) -> bytes:
    """Declares extra families in a `.docx` and, when `embed` is set, embeds their used faces.

    Args:
        data: The finished `.docx`.
        fonts: The extra families the document uses; empty returns `data` unchanged.
        embed: Whether to embed the font files (the layout's `embed_fonts` setting).

    Returns:
        The new `.docx`.

    Raises:
        ValueError: If `data` is not a Word file with a font table and settings part.
        OSError: If a font file has gone.
    """
    if not fonts:
        return data
    try:
        source = zipfile.ZipFile(io.BytesIO(data))
        names = set(source.namelist())
    except zipfile.BadZipFile as exc:
        raise ValueError("not a .docx file") from exc
    if not {"word/fontTable.xml", "word/settings.xml", "[Content_Types].xml"} <= names:
        raise ValueError("the .docx has no font table or settings part")
    table = etree.fromstring(source.read("word/fontTable.xml"), _parser())
    rel_root = (
        etree.fromstring(source.read("word/_rels/fontTable.xml.rels"), _parser())
        if "word/_rels/fontTable.xml.rels" in names else etree.fromstring(f'<Relationships xmlns="{REL}"/>'.encode(), _parser())
    )
    parts: dict[str, bytes] = {}
    number = len(rel_root) + 1
    for use in fonts:
        rels: list[tuple[str, str, uuid.UUID]] = []
        if embed:
            for style, path in _real_faces(use):
                key = uuid.uuid5(_KEY_NAMESPACE, f"{use.family.key}:{style}")
                rid, target = f"rIdFont{number}", f"fonts/font{number}.odttf"
                parts[f"word/{target}"] = _obfuscate(_read(path), key)
                rel = etree.SubElement(rel_root, f"{{{REL}}}Relationship")
                rel.set("Id", rid)
                rel.set("Type", _FONT_REL)
                rel.set("Target", target)
                rels.append((style, rid, key))
                number += 1
        _insert_font(table, use, rels)
    out: dict[str, bytes] = {
        "word/fontTable.xml": _xml(table),
        "word/_rels/fontTable.xml.rels": _xml(rel_root),
        **parts,
    }
    if embed and parts:
        settings = etree.fromstring(source.read("word/settings.xml"), _parser())
        _enable_embedding(settings)
        out["word/settings.xml"] = _xml(settings)
        content_types = etree.fromstring(source.read("[Content_Types].xml"), _parser())
        if not any(d.get("Extension") == "odttf" for d in content_types.findall(f"{{{CT}}}Default")):
            default = etree.Element(f"{{{CT}}}Default")
            default.set("Extension", "odttf")
            default.set("ContentType", _ODTTF)
            content_types.insert(0, default)
        out["[Content_Types].xml"] = _xml(content_types)
    return _rewrite(source, out, zipfile.ZIP_DEFLATED)


def _face_declaration(use: FontUse, style: str | None, href: str | None) -> etree._Element:
    """A `style:font-face` for a family, for one embedded face when `href` is given."""
    face = etree.Element(f"{{{_NS_STYLE}}}font-face", nsmap={"style": _NS_STYLE, "svg": _NS_SVG, "xlink": _NS_XLINK})
    face.set(f"{{{_NS_STYLE}}}name", use.family.word_name)
    face.set(f"{{{_NS_SVG}}}font-family", f"'{use.family.word_name}'")
    face.set(f"{{{_NS_STYLE}}}font-family-generic", _WORD_FAMILY[use.family.generic])
    face.set(f"{{{_NS_STYLE}}}font-pitch", "fixed" if use.family.generic == "monospace" else "variable")
    if style is not None and href is not None:
        face.set(f"{{{_NS_SVG}}}font-weight", "bold" if "bold" in style else "normal")
        face.set(f"{{{_NS_SVG}}}font-style", "italic" if "italic" in style else "normal")
        source = etree.SubElement(face, f"{{{_NS_SVG}}}font-face-src")
        uri = etree.SubElement(source, f"{{{_NS_SVG}}}font-face-uri")
        uri.set(f"{{{_NS_XLINK}}}href", href)
        uri.set(f"{{{_NS_XLINK}}}type", "simple")
        etree.SubElement(uri, f"{{{_NS_SVG}}}font-face-format").set(f"{{{_NS_SVG}}}string", "truetype")
    return face


def _declare_odt_fonts(root: etree._Element, faces: list[etree._Element], names: set[str]) -> None:
    """Replaces the root's declarations of `names` with `faces`, creating the declarations element if needed."""
    decls = root.find(f"{{{_NS_OFFICE}}}font-face-decls")
    if decls is None:
        decls = etree.Element(f"{{{_NS_OFFICE}}}font-face-decls")
        scripts = root.find(f"{{{_NS_OFFICE}}}scripts")
        root.insert(0 if scripts is None else list(root).index(scripts) + 1, decls)
    for existing in list(decls):
        if existing.get(f"{{{_NS_STYLE}}}name") in names:
            decls.remove(existing)
    for face in faces:
        decls.append(face)


def embed_in_odt(data: bytes, fonts: Sequence[FontUse], *, embed: bool) -> bytes:
    """Declares extra families in an `.odt` and, when `embed` is set, embeds their used faces.

    Args:
        data: The finished `.odt`.
        fonts: The extra families the document uses; empty returns `data` unchanged.
        embed: Whether to embed the font files (the layout's `embed_fonts` setting).

    Returns:
        The new `.odt`.

    Raises:
        ValueError: If `data` is not an OpenDocument file with the usual parts.
        OSError: If a font file has gone.
    """
    if not fonts:
        return data
    try:
        source = zipfile.ZipFile(io.BytesIO(data))
        names = set(source.namelist())
    except zipfile.BadZipFile as exc:
        raise ValueError("not an .odt file") from exc
    if not {"content.xml", "styles.xml", "META-INF/manifest.xml"} <= names:
        raise ValueError("the .odt is missing content, styles or manifest")
    parts: dict[str, bytes] = {}
    manifest_rows: list[str] = []
    all_faces: list[etree._Element] = []
    for use in fonts:
        embedded = _real_faces(use) if embed else []
        if embedded:
            for style, path in embedded:
                href = f"Fonts/{use.family.key}-{style}.ttf"
                parts[href] = _read(path)
                manifest_rows.append(href)
                all_faces.append(_face_declaration(use, style, href))
        else:
            all_faces.append(_face_declaration(use, None, None))
    family_names = {u.family.word_name for u in fonts}
    out: dict[str, bytes] = dict(parts)
    for part in ("content.xml", "styles.xml"):
        root = etree.fromstring(source.read(part), _parser())
        _declare_odt_fonts(root, [_copy(f) for f in all_faces], family_names)
        out[part] = _xml(root)
    manifest = etree.fromstring(source.read("META-INF/manifest.xml"), _parser())
    for href in manifest_rows:
        row = etree.SubElement(manifest, f"{{{_NS_MANIFEST}}}file-entry")
        row.set(f"{{{_NS_MANIFEST}}}full-path", href)
        row.set(f"{{{_NS_MANIFEST}}}media-type", "application/x-font-ttf")
    out["META-INF/manifest.xml"] = _xml(manifest)
    return _rewrite(source, out, zipfile.ZIP_DEFLATED)


def _copy(element: etree._Element) -> etree._Element:
    """An independent copy of an element (each part gets its own)."""
    return etree.fromstring(etree.tostring(element))


def _read(path: str) -> bytes:
    """Reads a font file."""
    with open(path, "rb") as handle:
        return handle.read()


def _xml(root: etree._Element) -> bytes:
    """Serialises a part with an XML declaration."""
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def _rewrite(source: zipfile.ZipFile, replace: dict[str, bytes], compression: int) -> bytes:
    """Copies a package, replacing/adding parts and keeping the order (the OpenDocument `mimetype` stays first and stored).

    Entries keep the source's timestamps and added parts take the package's first one, never the clock, so the same
    input always gives the same bytes.
    """
    buffer = io.BytesIO()
    items = source.infolist()
    stamp = items[0].date_time if items else (1980, 1, 1, 0, 0, 0)
    with zipfile.ZipFile(buffer, "w") as target:
        for item in items:
            payload = replace.pop(item.filename, None)
            stored = item.filename == "mimetype"
            entry = zipfile.ZipInfo(item.filename, item.date_time)
            entry.external_attr = item.external_attr
            entry.compress_type = zipfile.ZIP_STORED if stored else compression
            target.writestr(entry, source.read(item.filename) if payload is None else payload)
        for name, payload in replace.items():
            entry = zipfile.ZipInfo(name, stamp)
            entry.compress_type = compression
            target.writestr(entry, payload)
    return buffer.getvalue()
