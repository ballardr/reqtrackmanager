#!/usr/bin/env python3
"""
Module: check_select_components

Fails when a frontend single-choice select is written by hand, so every select draws the same caption, "All" entry,
accessible name and chevron (docs/ux-style-guide.md, "Pattern: selects"). The baseline is empty.

Checks `frontend/src/**/*.tsx` (stories and tests excluded): a raw `<select` anywhere except the two files that
implement the shared selects (`FilterSelect.tsx`, and `LabeledSelect.tsx` holding `LabeledSelect` and
`InlineSelect`, both skipped). Use `FilterSelect` in a filter panel, `LabeledSelect` for a form field and
`InlineSelect` for a control in a row with no caption.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "frontend" / "src"

IMPLEMENTATIONS = {"FilterSelect.tsx", "LabeledSelect.tsx"}
RAW_SELECT = re.compile(r"<select(?![\w-])")


def violations() -> list[str]:
    """Returns `path:line: message` for every hand-written `<select` outside the shared select components."""
    found = []
    for path in sorted(SRC.rglob("*.tsx")):
        if path.name.endswith((".stories.tsx", ".test.tsx")) or path.name in IMPLEMENTATIONS:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if line.lstrip().startswith(("//", "*", "/*")):
                continue
            if RAW_SELECT.search(line):
                where = f"{path.relative_to(SRC).as_posix()}:{number}"
                found.append(f"{where}: raw <select>; use FilterSelect, LabeledSelect or InlineSelect.")
    return found


def main() -> int:
    """Prints each offending line and exits 1 when there is any."""
    found = violations()
    for item in found:
        print(item)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
