#!/usr/bin/env python3
"""
Module: check_every_column_sortable

Fails when a `DirectoryColumn` data column is not sortable, so every column of every list can be ordered with a header
click (docs/ux-style-guide.md, "Pattern: sortable column header").

Checks `frontend/src/**/*.tsx|ts` (stories and tests excluded, `DirectoryTable.tsx` exempt). In each
`DirectoryColumn<...>[] = [` array a column that is not a row-controls column (`actions`, `preview`, `select`, or a label
that is a visually hidden `sr-only` span) must mention `sortable` and not `sortable: false`. A column that cannot be
ordered is named in `UNSORTABLE` with its reason, which is also recorded in `docs/decisions.md`.

Design notes:
- No baseline: every list was converted, so a new column cannot skip the decision unnoticed.
- The column keys are read with the bracket-aware reader of `check_optional_columns`, so a `key:` inside a cell is not a column.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_optional_columns as columns  # noqa: E402

ROOT = columns.ROOT
SRC = columns.SRC

EXEMPT = {"components/DirectoryTable.tsx", "hooks/useOptionalColumns.tsx"}
# (file, column key) of a data column that cannot be ordered, each with the reason.
_HISTORY = (
    "the History page reads a server-paged union of record, change request and audit events that are ordered only by time; "
    "ordering by this column across pages needs a unified query"
)
UNSORTABLE: dict[tuple[str, str], str] = {
    ("hooks/useActivityColumns.tsx", "type"): _HISTORY,
    ("hooks/useActivityColumns.tsx", "event"): _HISTORY + " (the event wording is composed in the browser)",
    ("hooks/useActivityColumns.tsx", "record"): _HISTORY + " (the record label is resolved after the read)",
    ("hooks/useActivityColumns.tsx", "person"): _HISTORY,
}
SORTABLE = re.compile(r"\bsortable\b(?!\s*:\s*false)")


def unsortable_columns() -> list[tuple[str, str]]:
    """Returns the `(relative path, column key)` of each data column that is not sortable and not in `UNSORTABLE`."""
    found = []
    for path in sorted([*SRC.rglob("*.tsx"), *SRC.rglob("*.ts")]):
        rel = path.relative_to(SRC).as_posix()
        if rel.endswith((".stories.tsx", ".test.tsx", ".test.ts", ".stories.ts")) or rel in EXEMPT:
            continue
        text = path.read_text(encoding="utf-8")
        for match in columns.ARRAY.finditer(text):
            entries = columns.column_segments(text, match.end())
            for key, label, segment in entries:
                if key in columns.NOT_DATA or "sr-only" in label or (rel, key) in UNSORTABLE:
                    continue
                if not SORTABLE.search(segment):
                    found.append((rel, key))
    return found


def find_problems() -> list[str]:
    """Returns one message per data column that is not sortable."""
    return [
        f"{rel}: column `{key}` is not sortable; mark it `sortable: true` with a sort value, "
        "or name it in UNSORTABLE with a reason."
        for rel, key in unsortable_columns()
    ]


def main() -> int:
    """Prints each problem and exits 1 when there is any."""
    problems = find_problems()
    for problem in problems:
        print(problem)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
