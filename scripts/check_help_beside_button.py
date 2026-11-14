#!/usr/bin/env python3
"""
Module: check_help_beside_button

Fails when a frontend `(?)` help button (`FieldHelp`) is rendered as a sibling of a button, so a control's help
sits on the control itself, as a `Tooltip` (docs/ux-style-guide.md, "Pattern: help on interactive elements").
A `(?)` stays only on the caption of a form field, filter or settings row, which `FieldCaption` and the shared
field components draw. The baseline is empty.

Checks `frontend/src/**/*.tsx` (stories, tests and `FieldHelp.tsx` itself excluded). Each `<FieldHelp` is a
violation when a sibling JSX element at the same indentation inside the same parent is a `<button`, a
`MenuButton`, a `ToggleButton`, a `DiagramExportMenu` or any element whose opening lines name a `btn` class.
A `<FieldHelp` is exempt when the same line carries `data-help-beside-ok` with a reason.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "frontend" / "src"

HELP_LINE = re.compile(r"^(?:\{[^}]*&&\s*)?<FieldHelp\b")
BUTTON_ELEMENTS = re.compile(r"^<(button|MenuButton|ToggleButton|DiagramExportMenu|SplitButton)\b")
BTN_CLASS = re.compile(r"""className=(?:"|\{`?"?)[^"`]*\bbtn\b""")
# How many opening lines of a sibling are read for a `btn` class (an element's props rarely run longer).
OPENING_LINES = 4


def _indent(line: str) -> int:
    """Returns the number of leading spaces of `line`."""
    return len(line) - len(line.lstrip(" "))


def _is_button(lines: list[str], start: int) -> bool:
    """Returns whether the JSX element opening at `lines[start]` is a button (by name or `btn` class)."""
    text = re.sub(r"^\{[^}]*&&\s*", "", lines[start].strip())
    if BUTTON_ELEMENTS.match(text):
        return True
    opening = " ".join(line.strip() for line in lines[start:start + OPENING_LINES])
    return text.startswith("<") and bool(BTN_CLASS.search(opening))


def _siblings(lines: list[str], index: int) -> list[int]:
    """Returns the start lines of the JSX elements at `lines[index]`'s indentation inside its parent."""
    level = _indent(lines[index])
    found = []
    for step in (-1, 1):
        cursor = index + step
        while 0 <= cursor < len(lines):
            line = lines[cursor]
            if line.strip():
                width = _indent(line)
                if width < level:
                    break
                opens = re.sub(r"^\{[^}]*&&\s*", "", line.lstrip())
                if width == level and opens.startswith("<") and not opens.startswith(("</", "<>")):
                    found.append(cursor)
            cursor += step
    return found


def violations() -> list[str]:
    """Returns `path:line: message` for every `FieldHelp` rendered beside a button."""
    found = []
    for path in sorted(SRC.rglob("*.tsx")):
        if path.name.endswith((".stories.tsx", ".test.tsx")) or path.name == "FieldHelp.tsx":
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            if not HELP_LINE.match(line.lstrip()) or "data-help-beside-ok" in line:
                continue
            if any(_is_button(lines, sibling) for sibling in _siblings(lines, index)):
                where = f"{path.relative_to(SRC).as_posix()}:{index + 1}"
                found.append(f"{where}: FieldHelp beside a button; give the button a Tooltip instead.")
    return found


def main() -> int:
    """Prints each offending line and exits 1 when there is any."""
    found = violations()
    for item in found:
        print(item)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
