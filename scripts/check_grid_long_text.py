#!/usr/bin/env python3
"""
Module: check_grid_long_text

Fails on the shapes of grid and table code that let long user text decide the layout (docs/ux-style-guide.md,
"Pattern: long text in a grid or table"). A script can see only part of the problem, so it is deliberately narrower
than the Storybook `LongText` stories and `testing/gridStability.ts`, which measure the real layout; the baseline is
empty.

Checks `frontend/src/**/*.{css,ts,tsx}` (stories and `testing/` excluded):
1. A grid column track sized by its content (`max-content`, `min-content` or a bare `auto`) in a
   `grid-template-columns`, `gridTemplateColumns` or a `track:`/`*_TRACKS`/`columns =` string. Such a track takes the
   width of the longest text in it. `auto-fit` and `auto-fill` are not content tracks.
2. A hand-built one-line ellipsis (`text-overflow: ellipsis`, `textOverflow: "ellipsis"`), which `CellText`
   (`components/CellText.tsx`) is the one component for, so a cell's clipping and its full-text tooltip are one
   behaviour.
3. A file that passes `renderExtra` to a `DefinitionList` and neither sets `extraContent="controls"` (a column of
   fixed-size controls) nor uses `CellText` for its text.

A line is exempt when it, or one of the two lines before it, carries `grid-text-ok: <reason>` (in a comment): the
reason says why no user text reaches the track or the clipped element (a column of fixed-size controls, a label the
product writes).
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "frontend" / "src"

TRACK_LINE = re.compile(r"grid-template-columns|gridTemplateColumns|\btrack\s*[:=]|_TRACKS\b|\bcolumns\s*=\s*[\"'`]")
CONTENT_TRACK = re.compile(r"max-content|min-content|(?<![\w-])auto(?![\w-])")
ELLIPSIS = re.compile(r"text-overflow\s*:\s*ellipsis|textOverflow\s*:\s*[\"']ellipsis[\"']")
MARKER = re.compile(r"grid-text-ok:\s*[A-Za-z]")


def _exempt(lines: list[str], index: int) -> bool:
    """Returns whether `lines[index]` or one of the two lines before it carries a reasoned `grid-text-ok:` marker."""
    return any(MARKER.search(lines[i]) for i in range(max(0, index - 2), index + 1))


def _sources() -> list[Path]:
    """Returns the files checked: product styles and sources, not stories, tests or testing helpers."""
    found = []
    for pattern in ("*.css", "*.ts", "*.tsx"):
        for path in SRC.rglob(pattern):
            relative = path.relative_to(SRC).as_posix()
            if relative.startswith("testing/") or ".stories." in path.name or ".test." in path.name:
                continue
            found.append(path)
    return sorted(found)


def violations() -> list[str]:
    """Returns `path:line: message` for every offending line or file."""
    found = []
    for path in _sources():
        relative = path.relative_to(SRC).as_posix()
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        for index, line in enumerate(lines):
            where = f"{relative}:{index + 1}"
            declared = TRACK_LINE.search(line)
            value = line[declared.end():].split(";")[0] if declared else ""
            if declared and CONTENT_TRACK.search(value) and not _exempt(lines, index):
                found.append(f"{where}: a grid track sized by its content; use a bounded track (a fixed width, a `fr` "
                             "share or a clamped `minmax`), or add `grid-text-ok: <reason>` when only controls reach it.")
            if ELLIPSIS.search(line) and relative != "components/CellText.tsx" and not _exempt(lines, index):
                found.append(f"{where}: a hand-built ellipsis; show the text with `CellText`, or add "
                             "`grid-text-ok: <reason>` when it is not user text in a cell.")
        if "renderExtra=" in text and path.suffix == ".tsx":
            if 'extraContent="controls"' not in text and "CellText" not in text:
                found.append(f"{relative}: renderExtra without `extraContent=\"controls\"` or `CellText`; its text would "
                             "set the width of its column.")
    return found


def main() -> int:
    """Prints each offending line and exits 1 when there is any."""
    found = violations()
    for item in found:
        print(item)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
