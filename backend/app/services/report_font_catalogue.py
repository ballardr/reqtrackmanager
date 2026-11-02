"""
Module: services.report_font_catalogue

The one lookup for the report fonts on offer: the four bundled families plus the extra families found in the mounted
font directory, with the server administrator's per-family settings laid over them.

Responsibilities:
- Keep this worker's scan of `REPORT_FONTS_DIR` current: scanned at start, forced by `rescan`, and re-read within
  `REFRESH_SECONDS` of the directory changing, so every worker follows a changed mount without a restart.
- `describe_fonts`: every family for the administrator (hidden and missing ones included).
- `author_choices`: what an author's picker lists (bundled, then enabled extras).
- `effective_families`: key to `FontFamily` with the administrator's name and generic applied, for the renderers.
- `family_or_fallback` and `font_problems`: what a layout naming an absent family gets, and the warning it is shown.
- `update_font`: upsert one family's settings.

Design decisions:
- Only settings are in the database; the font files never are. A settings row whose files have gone stays, and the
  family shows as missing to administrators only.
- Hiding a family removes it from pickers but does not break a layout already using it.
- A family that is gone falls back to the bundled family of the same generic kind and a note, never an error.

Dependencies: `report_fonts`, `report_font_directory`, `models.report_font`, `config`.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass, replace
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.report_font import ServerReportFont
from app.services import report_fonts
from app.services.report_font_directory import ScanResult, directory_signature, scan_directory

REFRESH_SECONDS = 30.0
GENERICS = ("sans-serif", "serif", "monospace")
_FALLBACK_KEY = {"sans-serif": "sans", "serif": "serif", "monospace": "mono"}

_lock = threading.Lock()
_scan: ScanResult | None = None
_signature: tuple[tuple[str, int, int], ...] = ()
_checked_at = 0.0


@dataclass(frozen=True)
class FontInfo:
    """One font family as the administrator and the renderers see it.

    Attributes:
        key: The family key.
        label: The family's name.
        bundled: Whether it ships with the application.
        enabled: Whether authors are offered it.
        missing: Whether its settings exist but its files are gone from the directory.
        word_name: The name written to Word, OpenDocument and HTML.
        generic: The generic fallback family.
        family: The drawable family; `None` when missing.
        faces_found: Styles the family has a real file for.
        fs_types: `OS/2 fsType` per real style (empty for a missing family).
    """

    key: str
    label: str
    bundled: bool
    enabled: bool
    missing: bool
    word_name: str
    generic: str
    family: report_fonts.FontFamily | None
    faces_found: tuple[str, ...]
    fs_types: dict[str, int]


def _apply(result: ScanResult) -> None:
    """Makes `result` this worker's current scan."""
    global _scan, _signature, _checked_at
    _scan = result
    _signature = directory_signature(get_settings().report_fonts_dir)
    _checked_at = time.monotonic()
    report_fonts.set_extra_families(result.families)


def rescan() -> ScanResult:
    """Scans the font directory now (this worker; the others follow within `REFRESH_SECONDS`).

    Returns:
        The new scan.
    """
    with _lock:
        result = scan_directory(get_settings().report_fonts_dir)
        _apply(result)
        return result


def current_scan() -> ScanResult:
    """This worker's scan, refreshed when the directory has changed since it was taken.

    Returns:
        The scan.
    """
    with _lock:
        directory = get_settings().report_fonts_dir
        if _scan is None:
            _apply(scan_directory(directory))
        elif time.monotonic() - _checked_at >= REFRESH_SECONDS:
            if directory_signature(directory) != _signature:
                _apply(scan_directory(directory))
            else:
                _set_checked()
        assert _scan is not None
        return _scan


def _set_checked() -> None:
    """Records that the directory was looked at just now."""
    global _checked_at
    _checked_at = time.monotonic()


def reset() -> None:
    """Forgets the scan (tests, and a changed `REPORT_FONTS_DIR`)."""
    global _scan, _signature, _checked_at
    with _lock:
        _scan, _signature, _checked_at = None, (), 0.0
        report_fonts.set_extra_families({})


def _settings(db: Session) -> dict[str, ServerReportFont]:
    """The administrator's per-family settings by key."""
    return {row.font_key: row for row in db.execute(select(ServerReportFont)).scalars()}


def describe_fonts(db: Session) -> list[FontInfo]:
    """Every family for the administrator: bundled, found extras, then extras whose files are gone.

    Args:
        db: A database session.

    Returns:
        One `FontInfo` each, hidden and missing included.
    """
    scan = current_scan()
    rows = _settings(db)
    out = [
        FontInfo(f.key, f.label, True, True, False, f.word_name, f.generic, f, report_fonts.STYLES, {})
        for f in report_fonts.FAMILIES.values()
    ]
    for key in sorted(scan.families, key=lambda k: scan.families[k].label.lower()):
        base = scan.families[key]
        row = rows.get(key)
        word_name = (row.word_name if row and row.word_name else None) or base.label
        generic = row.generic if row else base.generic
        family = replace(base, word_name=word_name, generic=generic)
        out.append(FontInfo(
            key, base.label, False, row.enabled if row else True, False, word_name, generic, family,
            base.faces_found, {s: f.fs_type for s, f in scan.faces[key].items()},
        ))
    for key in sorted(k for k in rows if k not in scan.families and k not in report_fonts.FAMILIES):
        row = rows[key]
        out.append(FontInfo(
            key, row.word_name or key.removeprefix("x-"), False, row.enabled, True,
            row.word_name or key.removeprefix("x-"), row.generic, None, (), {},
        ))
    return out


def author_choices(db: Session) -> list[FontInfo]:
    """The families an author's picker offers: the bundled four, then the enabled extras that are present.

    Args:
        db: A database session.

    Returns:
        The families, in that order.
    """
    return [info for info in describe_fonts(db) if info.enabled and not info.missing]


def effective_families(db: Session) -> dict[str, report_fonts.FontFamily]:
    """Every drawable family with the administrator's name and generic applied; hidden ones included.

    Args:
        db: A database session.

    Returns:
        Family by key; the renderers resolve a layout's font key through it.
    """
    return {info.key: info.family for info in describe_fonts(db) if info.family is not None}


def family_or_fallback(db: Session, key: str) -> tuple[report_fonts.FontFamily, str | None]:
    """The family to draw a layout's font key with.

    Args:
        db: A database session.
        key: The key stored in the layout.

    Returns:
        `(family, None)` when it is available, else `(the bundled family of the same generic kind, note)`.
    """
    families = effective_families(db)
    if key in families:
        return families[key], None
    row = _settings(db).get(key)
    generic = row.generic if row else "sans-serif"
    fallback = report_fonts.FAMILIES[_FALLBACK_KEY.get(generic, "sans")]
    return fallback, f"Font '{row.word_name if row and row.word_name else key}' is not available on this server; {fallback.label} was used."


def font_problems(db: Session, keys: Iterable[str]) -> list[str]:
    """Warnings for font keys that no longer resolve.

    Args:
        db: A database session.
        keys: Font keys a layout names.

    Returns:
        One sentence per key that is not available; empty when all resolve.
    """
    families = effective_families(db)
    return sorted({family_or_fallback(db, k)[1] or "" for k in set(keys) if k not in families} - {""})


def update_font(
    db: Session, key: str, *, word_name: str | None, generic: str, enabled: bool, actor_id: UUID | None,
) -> ServerReportFont:
    """Creates or updates one extra family's settings (the caller commits and audits).

    Args:
        db: A database session.
        key: An extra family key, found in the directory or already having settings.
        word_name: The name for Word, OpenDocument and HTML; `None` or empty means the family's own name.
        generic: One of `GENERICS`.
        enabled: Whether authors are offered the family.
        actor_id: The administrator.

    Returns:
        The settings row.

    Raises:
        KeyError: If the key is neither in the directory nor already has settings (or is a bundled family).
        ValueError: If `generic` is not one of `GENERICS`.
    """
    if generic not in GENERICS:
        raise ValueError(f"generic must be one of {', '.join(GENERICS)}")
    row = _settings(db).get(key)
    if key in report_fonts.FAMILIES or (row is None and key not in current_scan().families):
        raise KeyError(key)
    if row is None:
        row = ServerReportFont(font_key=key)
        db.add(row)
    row.word_name = (word_name or "").strip() or None
    row.generic = generic
    row.enabled = enabled
    row.updated_by = actor_id
    return row
