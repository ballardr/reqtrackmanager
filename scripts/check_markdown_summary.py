#!/usr/bin/env python3
"""
Module: check_markdown_summary

Fails when a frontend card, cell or title cuts or reads a Markdown value in a way that shows marks or loses an
equation (docs/ux-style-guide.md, "Pattern: Markdown fields"). The baseline is empty.

Checks `frontend/src/**/*.tsx` (stories and tests excluded):
- a hand-written ellipsis cut of text (`${text.slice(0, 140)}…`): clamp with `CellText` or `MarkdownSummary` instead;
  a place that cannot (SVG text) says `ellipsis-ok: <reason>` on the line before;
- `markdownPlainText(x.<field>)` over a math-capable Markdown field without `math: true`, which reads `\\( x \\)` as
  `( x )`: pass `{ math: true }` for a string, or show the field with `MarkdownSummary math` where it is drawn.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "frontend" / "src"

# The math-capable Markdown columns whose names are not shared with a plain-text field of another type.
MATH_FIELDS = (
    "question", "reasoning", "clarification", "proposed_description", "proposed_reasoning", "proposed_clarification",
    "decision_statement",
)
HAND_CUT = re.compile(r"""\.slice\(\s*0\s*,\s*[^)]+\)\s*\}?\s*…""")
PLAIN_CALL = re.compile(r"markdownPlainText\(\s*([\w.?]+\.(?:%s))\s*(?:,([^)]*))?\)" % "|".join(MATH_FIELDS))


def violations() -> list[str]:
    """Returns `path:line: message` for every hand-written ellipsis cut and every math field read without `math: true`."""
    found = []
    for path in sorted(SRC.rglob("*.tsx")):
        if path.name.endswith((".stories.tsx", ".test.tsx")):
            continue
        text = path.read_text(encoding="utf-8")
        where = path.relative_to(SRC).as_posix()
        lines = text.split("\n")
        for match in HAND_CUT.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            if "ellipsis-ok:" in lines[line - 2]:
                continue
            found.append(f"{where}:{line}: a hand-written ellipsis cut; clamp text with CellText or MarkdownSummary.")
        for match in PLAIN_CALL.finditer(text):
            if "math" not in (match.group(2) or ""):
                line = text.count("\n", 0, match.start()) + 1
                found.append(f"{where}:{line}: {match.group(1)} holds equations; pass {{ math: true }} or use MarkdownSummary math.")
    return found


def main() -> int:
    """Prints each offending place and exits 1 when there is any."""
    found = violations()
    for item in found:
        print(item)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
