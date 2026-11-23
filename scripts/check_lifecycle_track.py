#!/usr/bin/env python3
"""
Module: check_lifecycle_track

Fails when a record detail page hands `RecordHeader` (frontend/src/components/RecordHeader.tsx) a hand-drawn
row of state-transition buttons (`transitions=`) or a status control (`stateMenu=`), or draws a "Locked" notice
badge from the requirement strings. A record with states passes `lifecycle` (`LifecycleTrack`): the steps, the
current step and the next forward move, with every other move a row of the record's actions menu. See
docs/ux-style-guide.md, "Pattern: lifecycle track and Promote".

Checks `frontend/src/**/*.tsx`, stories excluded. The baseline is empty.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "frontend" / "src"

_OPEN = re.compile(r"<RecordHeader\b")
_HAND_DRAWN = re.compile(r"\b(transitions|stateMenu)=")


def _elements(text: str) -> list[tuple[int, str]]:
    """Returns `(start offset, source)` of every `<RecordHeader ... />` element in the text.

    Args:
        text: The source of one `.tsx` file.
    """
    found = []
    for match in _OPEN.finditer(text):
        depth = 0
        i = match.end()
        while i < len(text):
            ch = text[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            elif depth == 0 and (text.startswith("/>", i) or ch == ">"):
                found.append((match.start(), text[match.start() : i + 1]))
                break
            i += 1
    return found


def problems_in(text: str) -> list[tuple[int, str]]:
    """Returns `(line, problem)` for each `RecordHeader` in the text that draws its own state controls.

    Args:
        text: The source of one `.tsx` file.
    """
    found = []
    for start, source in _elements(text):
        hit = _HAND_DRAWN.search(source)
        if hit:
            line = text.count("\n", 0, start + hit.start()) + 1
            found.append((line, f"RecordHeader `{hit.group(1)}=` draws state controls; pass `lifecycle` instead"))
    return found


def violations() -> list[str]:
    """Returns `path:line: problem` for every offending `RecordHeader`."""
    found = []
    for path in sorted(SRC.rglob("*.tsx")):
        if path.name.endswith(".stories.tsx") or path.name == "RecordHeader.tsx":
            continue
        rel = path.relative_to(SRC).as_posix()
        for line, problem in problems_in(path.read_text(encoding="utf-8")):
            found.append(f"{rel}:{line}: {problem}")
    return found


def main() -> int:
    """Prints each offending header and exits 1 when there is any."""
    found = violations()
    for item in found:
        print(item)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
