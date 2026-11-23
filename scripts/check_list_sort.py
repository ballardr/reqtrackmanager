#!/usr/bin/env python3
"""
Module: check_list_sort

Fails when a frontend list of records has a filter panel with no **Sort by** field (docs/ux-style-guide.md,
"Pattern: list sort"): a person who has just created or changed a record must be able to put it at the top of the
list by creation or modification time, and a list in an order they cannot see or change loses it.

Checks `frontend/src/**/*.tsx`, stories and tests excluded. A file that draws a `FilterPanel` and offers the shared
list Export (`records={{`, `<ListActions` or `exportRecords`, how every list of a registered record type is marked)
must draw a `SortField`, or be listed in `NO_SORT` with the reason. The exemptions are lists whose order is part of
what they show; a new list does not join them.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "frontend" / "src"

# File (relative to frontend/src) -> why the list has no Sort by field (also in docs/decisions.md).
NO_SORT = {
    "modules/compliance/OutstandingPanel.tsx": (
        "the assessments of a standard, listed in the standard's own clause order; the order is the structure it reports on"
    ),
}
PANEL = re.compile(r"<FilterPanel(?![\w-])")
EXPORT = re.compile(r"records=\{\{|<ListActions(?![\w-])|\bexportRecords\b")
SORT_FIELD = re.compile(r"<SortField(?![\w-])")


def violations() -> list[str]:
    """Returns the files that draw a filter panel and the list Export but no `SortField` and are not exempt."""
    found = []
    for path in sorted(SRC.rglob("*.tsx")):
        rel = path.relative_to(SRC).as_posix()
        if rel.endswith((".stories.tsx", ".test.tsx")) or rel in NO_SORT:
            continue
        text = path.read_text(encoding="utf-8")
        if PANEL.search(text) and EXPORT.search(text) and not SORT_FIELD.search(text):
            found.append(rel)
    return found


def stale_exemptions() -> list[str]:
    """Returns the exempt files that do not exist, draw no filter panel and list Export, or draw a `SortField`
    (their entry should go)."""
    stale = []
    for rel in sorted(NO_SORT):
        path = SRC / rel
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
        if not (PANEL.search(text) and EXPORT.search(text)) or SORT_FIELD.search(text):
            stale.append(rel)
    return stale


def main() -> int:
    """Prints each problem and exits 1 when there is any."""
    problems = [
        f"{rel}: has a filter panel and the list Export but no SortField; add `<SortField>` (components/SortField.tsx) "
        "over `useListSort`, or name the file in NO_SORT with the reason."
        for rel in violations()
    ]
    problems += [
        f"{rel}: listed in NO_SORT but gone, no longer a list with Export, or now has a SortField; remove the entry."
        for rel in stale_exemptions()
    ]
    for problem in problems:
        print(problem)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
