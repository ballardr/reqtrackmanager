#!/usr/bin/env python3
"""
Module: check_sortable_columns

Fails when a frontend file renders a `DirectoryTable` without making any column sortable, so every list a person scans
can be ordered with a header click (docs/ux-style-guide.md, "Pattern: sortable column header").

Checks `frontend/src/**/*.tsx` (stories and tests excluded, `DirectoryTable.tsx` itself exempt): a file containing
`<DirectoryTable` must also contain `sortable` (a column marked `sortable: true`). A column with no natural order (an
actions or badge-only column) stays unsortable; a whole list that cannot be ordered needs a reason in
`docs/decisions.md`.

Design notes:
- A baseline, not an empty start: `scripts/sortable_columns_baseline.json` lists the files that still render a table
  with no sortable column. A file may leave it (run with `--update` after fixing one) but never join it, so the list
  only shrinks until it is empty.
- The check is per file, not per table: it cannot see a second, unsortable table in a file that has a sortable one.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "frontend" / "src"
BASELINE = Path(__file__).resolve().parent / "sortable_columns_baseline.json"

EXEMPT = {"components/DirectoryTable.tsx"}
TABLE = re.compile(r"<DirectoryTable(?![\w-])")
SORTABLE = re.compile(r"\bsortable\b")


def unsortable_files() -> list[str]:
    """Returns the relative paths of files that render a `DirectoryTable` with no `sortable` column."""
    found = []
    for path in sorted(SRC.rglob("*.tsx")):
        rel = path.relative_to(SRC).as_posix()
        if rel.endswith((".stories.tsx", ".test.tsx")) or rel in EXEMPT:
            continue
        text = path.read_text(encoding="utf-8")
        if TABLE.search(text) and not SORTABLE.search(text):
            found.append(rel)
    return found


def baseline() -> list[str]:
    """Returns the files the baseline still allows."""
    return json.loads(BASELINE.read_text(encoding="utf-8")) if BASELINE.is_file() else []


def find_problems() -> list[str]:
    """Returns one message per file not in the baseline with no sortable column, and per baseline entry that is fixed."""
    current = set(unsortable_files())
    allowed = set(baseline())
    problems = [
        f"{rel}: renders a DirectoryTable with no sortable column; mark the ordered columns `sortable` "
        "(SortableHeader, useUrlSort; a paged list sorts on the server)."
        for rel in sorted(current - allowed)
    ]
    problems += [
        f"{rel}: now sortable (or removed); run `python3 scripts/check_sortable_columns.py --update` to shrink the baseline."
        for rel in sorted(allowed - current)
    ]
    return problems


def main() -> int:
    """Prints each problem and exits 1 when there is any; `--update` rewrites the baseline to the current files."""
    if "--update" in sys.argv:
        BASELINE.write_text(json.dumps(unsortable_files(), indent=2) + "\n", encoding="utf-8")
        print(f"wrote {BASELINE.relative_to(ROOT)}")
        return 0
    problems = find_problems()
    for problem in problems:
        print(problem)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
