"""
Module: services.report_folders

The one rule for the folder a report is filed under in the Reports picker. A folder is a path of up to three
levels written `Handover/Quarterly`.

Responsibilities:
- Normalise a path the author typed: each level trimmed with inner whitespace collapsed, empty levels dropped, levels
  joined by `/`. Reject a path that is too deep or too long, or holds control characters. An empty path means "not
  filed": the picker then uses the report's default folder.

Design decisions:
- A folder is a plain label on the row (a layout, a pack) or on a placement override, not a table: renaming a folder
  is editing the label, and nothing else (permissions, bundles, hiding) has to know folders exist.
- The label is shown as text only; it is never used in a file path, a query or markup, so the checks are about size
  and tidiness rather than injection.
"""

from __future__ import annotations

import re

MAX_FOLDER_DEPTH = 3
MAX_FOLDER_LEVEL_CHARS = 40
MAX_FOLDER_CHARS = 120
FOLDER_SEPARATOR = "/"
_WHITESPACE = re.compile(r"\s+")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def clean_folder(value: str | None) -> str:
    """Returns the folder path tidied for storage.

    Args:
        value: What the author typed, or `None`.

    Returns:
        The levels trimmed, whitespace inside a level collapsed to one space and empty levels dropped, joined by `/`;
        `""` for no folder.

    Raises:
        ValueError: A control character (other than ordinary whitespace), more than `MAX_FOLDER_DEPTH` levels, a
            level longer than `MAX_FOLDER_LEVEL_CHARS` or a path longer than `MAX_FOLDER_CHARS`.
    """
    raw = value or ""
    if _CONTROL.search(raw.replace("\t", " ").replace("\n", " ").replace("\r", " ")):
        raise ValueError("A folder name cannot contain control characters.")
    levels = [_WHITESPACE.sub(" ", part).strip() for part in raw.split(FOLDER_SEPARATOR)]
    levels = [level for level in levels if level]
    if len(levels) > MAX_FOLDER_DEPTH:
        raise ValueError(f"A folder is at most {MAX_FOLDER_DEPTH} levels deep.")
    if any(len(level) > MAX_FOLDER_LEVEL_CHARS for level in levels):
        raise ValueError(f"Each level of a folder is at most {MAX_FOLDER_LEVEL_CHARS} characters.")
    path = FOLDER_SEPARATOR.join(levels)
    if len(path) > MAX_FOLDER_CHARS:
        raise ValueError(f"A folder path is at most {MAX_FOLDER_CHARS} characters.")
    return path


def imported_folder(value: object) -> str:
    """The folder of an imported bundle entry, tidied; one a hand-edited file made invalid is dropped (`""`) so the
    record still imports."""
    try:
        return clean_folder(value if isinstance(value, str) else "")
    except ValueError:
        return ""
