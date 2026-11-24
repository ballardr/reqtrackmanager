#!/usr/bin/env python3
"""
Module: check_optional_columns

Fails when a frontend file builds a list's `DirectoryColumn` set of five or more data columns and offers no column
chooser, so a list shows the columns most visits need and a person adds or removes the others
(docs/ux-style-guide.md, "Pattern: column chooser").

Checks `frontend/src/**/*.tsx|ts` (stories and tests excluded, `DirectoryTable.tsx` and the hook itself exempt). For each
`DirectoryColumn<...>[] = [` array it counts the data columns (`key: "..."` entries, not an `actions`, `preview` or
`select` column, and not a column whose label is a visually hidden `sr-only` span). A file whose largest array has five
or more data columns must use `useOptionalColumns` (or the lower-level `useColumnChoice`/`ColumnChooser`) or be named in
`NO_CHOOSER` with its reason, which is also recorded in `docs/decisions.md`.

Design notes:
- The check is per file, not per table: a file with a small table and a large one passes when it uses the hook.
- There is no baseline: the sweep converted every list, so a new list cannot skip the decision unnoticed.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "frontend" / "src"

THRESHOLD = 5
EXEMPT = {"components/DirectoryTable.tsx", "hooks/useOptionalColumns.tsx"}
# Files whose columns cannot take the shared hook, each with the reason.
NO_CHOOSER = {
    "modules/product_feedback/requestColumns.tsx": (
        "the Product Feedback list has its own chooser (RequestColumnChooser) because its Score columns follow the "
        "organisation's scoring models"
    ),
}
ARRAY = re.compile(r"DirectoryColumn<[^\n]*?>\[\]\s*=\s*\[")
KEY = re.compile(r"\bkey:\s*[\"'`]([^\"'`$]+)[\"'`](?:,\s*label:\s*([^\n]{0,60}))?")
NOT_DATA = {"actions", "preview", "select"}
OFFERS = re.compile(r"\buseOptionalColumns\(|\buseColumnChoice\(|<ColumnChooser\b")


def _column_keys(text: str, start: int) -> list[tuple[str, str]]:
    """
    Returns the `(key, label)` of each column declared in the array literal whose opening `[` is just before `start`.

    A column is an object at most three brackets deep (an array item, or one inside a conditional spread); a `key:` nested
    deeper belongs to something a cell draws (an actions menu item), not to a column. String literals and comments are
    skipped so a bracket or quote inside one does not shift the depth.
    """
    keys: list[tuple[str, str]] = []
    depth, i, quote = 1, start, ""
    while depth and i < len(text):
        c = text[i]
        if quote:
            i += 2 if c == "\\" else 1
            quote = "" if c == quote else quote
            continue
        if text.startswith("//", i):
            i = text.find("\n", i) if "\n" in text[i:] else len(text)
            continue
        if text.startswith("/*", i):
            i = text.find("*/", i) + 2 if "*/" in text[i:] else len(text)
            continue
        if c in "\"'`":
            quote = c
        elif c in "[{":
            depth += 1
        elif c in "]}":
            depth -= 1
        elif depth <= 3 and text.startswith("key:", i) and not text[i - 1].isalnum():
            found = KEY.match(text, i)
            if found:
                keys.append((found.group(1), found.group(2) or ""))
        i += 1
    return keys


def column_segments(text: str, start: int) -> list[tuple[str, str, str]]:
    """
    Returns `(key, label, source)` for each column of the array whose opening `[` is just before `start`: the source text
    runs from the column's `key:` to the next column's, so a caller can look for a property of the column.
    """
    positions: list[int] = []
    depth, i, quote = 1, start, ""
    while depth and i < len(text):
        c = text[i]
        if quote:
            i += 2 if c == "\\" else 1
            quote = "" if c == quote else quote
            continue
        if text.startswith("//", i):
            i = text.find("\n", i) if "\n" in text[i:] else len(text)
            continue
        if text.startswith("/*", i):
            i = text.find("*/", i) + 2 if "*/" in text[i:] else len(text)
            continue
        if c in "\"'`":
            quote = c
        elif c in "[{":
            depth += 1
        elif c in "]}":
            depth -= 1
        elif depth <= 3 and text.startswith("key:", i) and not text[i - 1].isalnum() and KEY.match(text, i):
            positions.append(i)
        i += 1
    end = i
    out = []
    for n, pos in enumerate(positions):
        found = KEY.match(text, pos)
        assert found is not None
        stop = positions[n + 1] if n + 1 < len(positions) else end
        out.append((found.group(1), found.group(2) or "", text[pos:stop]))
    return out


def data_column_counts(text: str) -> list[int]:
    """Returns, for each `DirectoryColumn` array in `text`, the number of data columns it declares."""
    return [
        len({k for k, label in _column_keys(text, match.end()) if k not in NOT_DATA and "sr-only" not in label})
        for match in ARRAY.finditer(text)
    ]


def lists_without_a_chooser() -> list[tuple[str, int]]:
    """Returns the relative path and largest data column count of each file that needs a chooser and offers none."""
    found = []
    for path in sorted([*SRC.rglob("*.tsx"), *SRC.rglob("*.ts")]):
        rel = path.relative_to(SRC).as_posix()
        if rel.endswith((".stories.tsx", ".test.tsx", ".test.ts", ".stories.ts")) or rel in EXEMPT or rel in NO_CHOOSER:
            continue
        text = path.read_text(encoding="utf-8")
        counts = data_column_counts(text)
        if counts and max(counts) >= THRESHOLD and not OFFERS.search(text):
            found.append((rel, max(counts)))
    return found


def find_problems() -> list[str]:
    """Returns one message per file with a list of five or more data columns and no column chooser."""
    return [
        f"{rel}: a list of {count} data columns offers no column chooser; mark its optional columns `optional` "
        "(and `defaultHidden` for a rarely needed one) and pass the columns through `useOptionalColumns`, "
        "or name the file in NO_CHOOSER with a reason."
        for rel, count in lists_without_a_chooser()
    ]


def main() -> int:
    """Prints each problem and exits 1 when there is any."""
    problems = find_problems()
    for problem in problems:
        print(problem)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
