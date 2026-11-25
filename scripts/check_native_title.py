#!/usr/bin/env python3
"""
Module: check_native_title

Fails when a control that opens a list, or a choice inside one, carries a native `title` attribute, so a picker never
shows a browser tooltip over the list a person is choosing from (docs/ux-style-guide.md, "Pattern: help on interactive
elements"). The baseline is empty.

A native `title` is slow, never shows on touch or keyboard focus, is not styled, and appears over an open panel. The
shared `Tooltip` (or `CellText` for clipped text) replaces it. Checked in `frontend/src/**/*.tsx` (stories and tests
excluded), on the opening tag of:
- a `<button>` that has `aria-haspopup` (a menu, picker or dialog trigger);
- a `<button>` or `<input>` of a tree or list choice: the `tree-toggle` chevron, a checkbox or a radio.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "frontend" / "src"

OPENING = re.compile(r"<(button|input)(?![\w-])")
TITLE = re.compile(r"(?<![\w-])title=")


def opening_tag_end(text: str, start: int) -> int:
    """Returns the index just past the `>` that closes the tag opened at `start`, ignoring `>` inside braces or quotes."""
    depth = 0
    quote = ""
    index = start
    while index < len(text):
        char = text[index]
        if quote:
            if char == quote and text[index - 1] != "\\":
                quote = ""
        elif char in "\"'`" and depth >= 0:
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        elif char == ">" and depth == 0 and text[index - 1] != "=":
            return index + 1
        index += 1
    return len(text)


def strip_braced_strings(tag: str) -> str:
    """Removes nested template text so a `title=` inside an expression is not read as an attribute of the tag."""
    out = []
    depth = 0
    for char in tag:
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        elif depth == 0:
            out.append(char)
    return "".join(out)


def is_choice_control(kind: str, attributes: str) -> bool:
    """True for the controls this rule covers: a popup trigger, a tree chevron, a checkbox or a radio."""
    if "aria-haspopup" in attributes:
        return kind == "button"
    if kind == "button":
        return "tree-toggle" in attributes
    return bool(re.search(r"type=\"(checkbox|radio)\"", attributes))


def violations() -> list[str]:
    """Returns `path:line: message` for every covered control with a native `title` attribute."""
    found = []
    for path in sorted(SRC.rglob("*.tsx")):
        if path.name.endswith((".stories.tsx", ".test.tsx")):
            continue
        text = path.read_text(encoding="utf-8")
        for match in OPENING.finditer(text):
            tag = text[match.start():opening_tag_end(text, match.end())]
            if is_choice_control(match.group(1), tag) and TITLE.search(strip_braced_strings(tag)):
                line = text.count("\n", 0, match.start()) + 1
                found.append(
                    f"{path.relative_to(SRC).as_posix()}:{line}: native title on a <{match.group(1)}>; use Tooltip."
                )
    return found


def main() -> int:
    """Prints each offending control and exits 1 when there is any."""
    found = violations()
    for item in found:
        print(item)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
