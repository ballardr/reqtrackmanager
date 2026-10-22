#!/usr/bin/env python3
"""
Module: check_spacing_tokens

Fails when the frontend writes a spacing or radius value that has a named token as a literal
(docs/ux-style-guide.md, "Tokens"). `theme.css` declares `--space-1..6` and `--radius-sm/md/lg/pill`; a
`padding`, `margin` or `gap` on a step of the scale, or a `border-radius` of 4, 6, 8 or 999px, must be
the token, so changing the scale is one edit instead of a repository-wide one.

Checks the stylesheet declarations in `frontend/src/**/*.css` and the inline React `style` strings in
`frontend/src/**/*.tsx`, with the value-to-token tables below. A value between two steps (0.3rem, 0.6rem)
is a deliberate one-off and is not flagged; the scale is not widened to absorb it. The baseline is empty.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "frontend" / "src"

# Literal -> token, for spacing. 0.35rem and 0.4rem round to the 0.375rem step (6px).
SPACE = {
    "0.25rem": "--space-1", "0.35rem": "--space-2", "0.375rem": "--space-2", "0.4rem": "--space-2",
    "0.5rem": "--space-3", "0.75rem": "--space-4", "1rem": "--space-5", "1.5rem": "--space-6",
}
RADIUS = {"4px": "--radius-sm", "5px": "--radius-md", "6px": "--radius-md", "8px": "--radius-lg", "999px": "--radius-pill"}

CSS_SPACE = re.compile(r"^\s*(?:padding|margin|gap|row-gap|column-gap)[a-z-]*:\s*([^;]+);")
CSS_RADIUS = re.compile(r"^\s*border(?:-[a-z]+)*-radius:\s*([^;]+);")
TSX_SPACE = re.compile(r'\b(?:padding|margin|gap|rowGap|columnGap)[A-Za-z]*: *"([^"]*)"')
TSX_RADIUS = re.compile(r'\bborderRadius: *(?:"([^"]*)"|(\d+))')


def _flag(value: str, table: dict[str, str]) -> list[str]:
    """Returns the literals in a (non-`calc`/`var`) value that have a token."""
    if "(" in value:
        return []
    return [p for p in value.split() if p in table]


def violations() -> list[str]:
    """Returns `file:line: literal -> token` for each spacing or radius literal that has a token."""
    found = []
    # Custom-property declarations (`--space-1: 0.25rem`) are skipped: that is where the literals belong.
    for path in sorted(SRC.rglob("*")):
        if path.suffix not in (".css", ".tsx"):
            continue
        rel = path.relative_to(SRC).as_posix()
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if line.lstrip().startswith("--"):
                continue
            hits: list[tuple[str, dict[str, str]]] = []
            if path.suffix == ".css":
                for rx, table in ((CSS_SPACE, SPACE), (CSS_RADIUS, RADIUS)):
                    m = rx.match(line)
                    if m:
                        hits += [(lit, table) for lit in _flag(m.group(1), table)]
            else:
                for m in TSX_SPACE.finditer(line):
                    hits += [(lit, SPACE) for lit in _flag(m.group(1), SPACE)]
                for m in TSX_RADIUS.finditer(line):
                    raw = m.group(1) if m.group(1) is not None else f"{m.group(2)}px"
                    hits += [(lit, RADIUS) for lit in _flag(raw, RADIUS)]
            for literal, table in hits:
                found.append(f"{rel}:{number}: {literal} -> var({table[literal]})")
    return found


def main() -> int:
    """Prints each offending literal and exits 1 when there is any."""
    found = violations()
    for item in found:
        print(item)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
