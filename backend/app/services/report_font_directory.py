"""
Module: services.report_font_directory

Reads the directory of extra `.ttf` fonts the server administrator mounts and groups the files into families.

Responsibilities:
- `scan_directory`: list the files, reject the unusable ones with a reason, and group the rest by the font's own
  family name into `FontFamily` objects keyed `x-<slug>`.
- `directory_signature`: a cheap fingerprint of the directory, so a worker notices a changed mount.

Design decisions:
- The directory is administrator-trusted (set by `REPORT_FONTS_DIR`, mounted read-only, never user-supplied), but each file
  is still parsed defensively: a bad file is skipped with a reason, never a startup failure, and nothing outside the
  directory is followed (symbolic links are refused, subdirectories are not entered).
- TrueType (`.ttf`) only: the PDF library cannot draw CFF (`.otf`) outlines, and a collection (`.ttc`) holds several fonts.
- A face whose `OS/2 fsType` forbids embedding (restricted licence) or subsetting is refused outright: the PDF library
  embeds a subset of every face it draws, and the same licence bits govern copying the file into a Word or OpenDocument
  file. So an unusable face is never drawn or embedded anywhere; the administrator sees why.
- A family needs a regular face. A missing bold, italic or bold italic face reuses the nearest one (`faces_found` says
  which are real), so a PDF never fakes a slant.
- Logs and reasons carry file names and counts only, never file contents.

Dependencies: ReportLab's TrueType reader (it also validates the file), `report_fonts`.
"""

from __future__ import annotations

import logging
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path

from reportlab.pdfbase.ttfonts import FF_FORCEBOLD, FF_ITALIC, TTFont

from app.services.report_fonts import STYLES, FontFamily

logger = logging.getLogger(__name__)

MAX_FONT_BYTES = 10 * 1024 * 1024
_MAX_FILES = 500
_TRUETYPE_MAGICS = (b"\x00\x01\x00\x00", b"true")
_UNSUPPORTED = {
    ".otf": "OpenType (CFF) fonts are not supported; provide a TrueType .ttf",
    ".ttc": "font collections are not supported; provide separate .ttf files",
}
FS_TYPE_LABELS = {0: "Installable", 4: "Preview and print", 8: "Editable"}
_NEAREST = {"bold": ("regular",), "italic": ("regular",), "bolditalic": ("bold", "italic", "regular")}


@dataclass(frozen=True)
class ScannedFace:
    """One usable font file.

    Attributes:
        style: One of `STYLES`.
        path: The file.
        fs_type: The font's `OS/2 fsType` embedding permission bits.
    """

    style: str
    path: Path
    fs_type: int


@dataclass(frozen=True)
class SkippedFile:
    """A file that was not used, and why."""

    file_name: str
    reason: str


@dataclass
class ScanResult:
    """What a scan found.

    Attributes:
        configured: Whether a directory is configured at all.
        families: Usable families by key.
        faces: Every usable face per family key and style.
        skipped: Files that were not used.
    """

    configured: bool = False
    families: dict[str, FontFamily] = field(default_factory=dict)
    faces: dict[str, dict[str, ScannedFace]] = field(default_factory=dict)
    skipped: list[SkippedFile] = field(default_factory=list)


def slugify(name: str) -> str:
    """The stable family key suffix for a family name: lower case letters and digits joined by hyphens.

    Args:
        name: The font's family name.

    Returns:
        The slug, at most 60 characters; empty when the name has no letter or digit.
    """
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60].strip("-")


def read_fs_type(path: Path) -> int:
    """Reads the `OS/2 fsType` field of a TrueType file.

    Args:
        path: The font file.

    Returns:
        The embedding permission bits; 0 when the font has no OS/2 table.

    Raises:
        ValueError: If the table directory is not readable.
    """
    with path.open("rb") as handle:
        header = handle.read(12)
        if len(header) < 12:
            raise ValueError("file too short")
        (table_count,) = struct.unpack(">H", header[4:6])
        if not 0 < table_count <= 64:
            raise ValueError("bad table count")
        directory = handle.read(16 * table_count)
        for index in range(table_count):
            entry = directory[16 * index:16 * index + 16]
            if len(entry) < 16:
                raise ValueError("truncated table directory")
            tag, _checksum, offset, length = struct.unpack(">4sIII", entry)
            if tag == b"OS/2":
                if length < 10:
                    raise ValueError("OS/2 table too short")
                handle.seek(offset + 8)
                value = handle.read(2)
                if len(value) < 2:
                    raise ValueError("OS/2 table truncated")
                return int(struct.unpack(">H", value)[0])
    return 0


def _style(bold: bool, italic: bool) -> str:
    """The `STYLES` name for a bold and italic flag pair."""
    return ("bold" if bold else "") + ("italic" if italic else "") or "regular"


def _read_face(path: Path) -> tuple[str, ScannedFace] | str:
    """Validates one file.

    Args:
        path: A directory entry.

    Returns:
        `(family name, face)` when usable, otherwise the reason it is not (empty: not a font file, ignored silently).
    """
    suffix = path.suffix.lower()
    if suffix in _UNSUPPORTED:
        return _UNSUPPORTED[suffix]
    if suffix != ".ttf":
        return ""
    if path.is_symlink():
        return "symbolic links are not followed"
    if path.stat().st_size > MAX_FONT_BYTES:
        return f"larger than {MAX_FONT_BYTES // (1024 * 1024)} MB"
    with path.open("rb") as handle:
        if handle.read(4) not in _TRUETYPE_MAGICS:
            return "not a TrueType font"
    try:
        fs_type = read_fs_type(path)
    except (ValueError, OSError, struct.error):
        return "could not be read as a TrueType font"
    if fs_type == 2 or fs_type & 0x0300:
        return "its licence forbids embedding or subsetting (OS/2 fsType), so it cannot be drawn or embedded"
    try:
        face = TTFont("scan", str(path)).face
        name = bytes(face.familyName).decode("utf-8", "replace").strip()
        style = _style(bool(face.flags & FF_FORCEBOLD), bool(face.flags & FF_ITALIC))
    except Exception:  # noqa: BLE001 - a malformed font may fail in any way; the file is skipped, never fatal
        return "could not be read as a TrueType font"
    if not slugify(name):
        return "has no usable family name"
    return name, ScannedFace(style, path, fs_type)


def _pick(style: str, faces: dict[str, ScannedFace]) -> str:
    """The style to take the file from: the style itself, else the nearest the family has."""
    if style in faces:
        return style
    return next(s for s in (*_NEAREST[style], "regular") if s in faces)


def scan_directory(directory: str) -> ScanResult:
    """Scans a font directory.

    Args:
        directory: The `REPORT_FONTS_DIR` value; empty means none is configured.

    Returns:
        The usable families and the skipped files. A missing or unreadable directory gives an empty result with
        the reason as a skipped entry; this never raises.
    """
    result = ScanResult(configured=bool(directory))
    if not directory:
        return result
    root = Path(directory)
    try:
        entries = sorted(root.iterdir(), key=lambda p: p.name)
    except OSError:
        result.skipped.append(SkippedFile(root.name or str(root), "the font directory cannot be read"))
        return result
    names: dict[str, str] = {}
    by_key: dict[str, dict[str, ScannedFace]] = {}
    for path in entries[:_MAX_FILES]:
        if not path.is_file() and not path.is_symlink():
            continue
        outcome = _read_face(path)
        if isinstance(outcome, str):
            if outcome:
                result.skipped.append(SkippedFile(path.name, outcome))
            continue
        name, face = outcome
        key = f"x-{slugify(name)}"
        if names.setdefault(key, name) != name:
            result.skipped.append(SkippedFile(path.name, f"its family name collides with '{names[key]}'"))
            continue
        if face.style in by_key.setdefault(key, {}):
            result.skipped.append(SkippedFile(path.name, f"a second {face.style} face of '{name}'"))
            continue
        by_key[key][face.style] = face
    if len(entries) > _MAX_FILES:
        result.skipped.append(SkippedFile("(directory)", f"only the first {_MAX_FILES} files are read"))
    for key, faces in by_key.items():
        if "regular" not in faces:
            result.skipped.extend(SkippedFile(f.path.name, f"'{names[key]}' has no regular face") for f in faces.values())
            continue
        files = {style: faces[_pick(style, faces)].path for style in STYLES}
        result.faces[key] = faces
        result.families[key] = FontFamily(
            key, names[key], files, names[key], "sans-serif", bundled=False,
            faces_found=tuple(s for s in STYLES if s in faces),
        )
    logger.info("report font scan: %d families, %d files skipped", len(result.families), len(result.skipped))
    return result


def directory_signature(directory: str) -> tuple[tuple[str, int, int], ...]:
    """A fingerprint of a font directory's top-level files (name, size, modification time).

    Args:
        directory: The `REPORT_FONTS_DIR` value.

    Returns:
        The fingerprint; empty when unset or unreadable.
    """
    if not directory:
        return ()
    try:
        entries = sorted(Path(directory).iterdir(), key=lambda p: p.name)[:_MAX_FILES]
        return tuple((p.name, p.stat().st_size, p.stat().st_mtime_ns) for p in entries)
    except OSError:
        return ()
