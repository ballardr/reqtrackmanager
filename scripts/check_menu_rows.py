#!/usr/bin/env python3
"""
Module: check_menu_rows

Fails when a frontend menu or list row is drawn as a standard button, so every menu keeps the shared text-row style
(`.menu-item`, drawn by `ActionMenuList` and reused by link and option lists; docs/ux-style-guide.md, "Pattern: action
menu"). The baseline is empty.

Checks `frontend/src/**/*.tsx` (stories, tests and `ActionMenu.tsx` itself excluded). A line is a violation when:
- an element with `role="menuitem"` or `role="option"` also carries a `btn` class (read over the element's opening lines);
- an element carries both `menu-item` and `btn`; or
- inside a `<Popover ...>` block, a row repeated by a `.map(` callback carries a `btn` class (a stack of bordered buttons
  as a list of choices).

A single button in a popover (Save, Cancel, Done, Reset) is not a list row and is not reported. A row is exempt when its
opening lines carry `data-menu-row-ok` with a reason (for example a row that is itself a control with its own states).
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "frontend" / "src"

BTN_CLASS = re.compile(r"""className=(?:"|\{`?"?)[^"`]*\bbtn\b""")
ROLE_ROW = re.compile(r"""role=["'](?:menuitem|option)["']""")
MENU_ITEM_CLASS = re.compile(r"""className=(?:"|\{`?"?)[^"`]*\bmenu-item\b""")
# How many opening lines of an element are read for its props (an element's props rarely run longer).
OPENING_LINES = 8
EXEMPT = "data-menu-row-ok"


def _indent(line: str) -> int:
    """Returns the number of leading spaces of `line`."""
    return len(line) - len(line.lstrip(" "))


def _element_start(lines: list[str], index: int) -> int:
    """Returns the line where the JSX element whose props contain `lines[index]` opens (the nearest `<tag` above)."""
    for cursor in range(index, max(index - OPENING_LINES, -1), -1):
        if re.match(r"^\s*(?:\{[^}]*&&\s*)?<[A-Za-z]", lines[cursor]):
            return cursor
    return index


def _opening(lines: list[str], start: int) -> str:
    """Returns the opening lines of the element starting at `lines[start]`, up to the line that closes its tag."""
    text = []
    for line in lines[start:start + OPENING_LINES]:
        text.append(line.strip())
        if line.rstrip().endswith(">") and not line.rstrip().endswith("=>"):
            break
    return " ".join(text)


def _popover_map_lines(lines: list[str]) -> set[int]:
    """Returns the lines inside a `.map(` callback that sits inside a `<Popover` block."""
    inside: set[int] = set()
    popover_indent: int | None = None
    map_indent: int | None = None
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        width = _indent(line)
        if popover_indent is None and re.match(r"^\s*(?:\{[^}]*&&\s*)?<Popover\b", line):
            popover_indent = width
            continue
        if popover_indent is not None and width <= popover_indent and re.match(r"^\s*</Popover>|^\s*\)\}", line):
            popover_indent = None
            map_indent = None
            continue
        if popover_indent is None:
            continue
        if map_indent is not None and width <= map_indent:
            map_indent = None
        if map_indent is None and ".map(" in line:
            map_indent = width
        elif map_indent is not None:
            inside.add(index)
    return inside


def violations() -> list[str]:
    """Returns `path:line: message` for every menu or list row drawn with a `btn` class."""
    found = []
    for path in sorted(SRC.rglob("*.tsx")):
        if path.name.endswith((".stories.tsx", ".test.tsx")) or path.name == "ActionMenu.tsx":
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        in_popover_map = _popover_map_lines(lines)
        reported: set[int] = set()
        for index, line in enumerate(lines):
            if not BTN_CLASS.search(line) and not (ROLE_ROW.search(line) or MENU_ITEM_CLASS.search(line)):
                continue
            start = _element_start(lines, index)
            opening = _opening(lines, start)
            if EXEMPT in opening or start in reported:
                continue
            where = f"{path.relative_to(SRC).as_posix()}:{start + 1}"
            if ROLE_ROW.search(opening) and BTN_CLASS.search(opening):
                found.append(f"{where}: a menu item or option is a `btn`; use the shared `menu-item` row.")
            elif MENU_ITEM_CLASS.search(opening) and BTN_CLASS.search(opening):
                found.append(f"{where}: `menu-item` combined with `btn`; a menu row is plain text.")
            elif BTN_CLASS.search(line) and index in in_popover_map:
                found.append(f"{where}: a `btn` repeated as a list row in a Popover; use `ActionMenuList` or `menu-item`.")
            else:
                continue
            reported.add(start)
    return found


def main() -> int:
    """Prints each offending line and exits 1 when there is any."""
    found = violations()
    for item in found:
        print(item)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
