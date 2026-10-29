#!/usr/bin/env python3
"""
Module: check_report_format_labels

Fails when frontend code hand-writes the full name of an OpenDocument report format ("OpenDocument text",
"OpenDocument spreadsheet") as a label. Every report format control takes its name from `REPORT_FORMAT` in
`frontend/src/api/reportFormats.ts` (acronym as the label, full name as the tooltip), so a label cannot drift
from one screen to the next or overflow a narrow button (docs/ux-style-guide.md, "Pattern: list actions").

Checks `frontend/src/**/*.ts` and `*.tsx`; the map file itself, stories and tests are excluded, and so are
comments and prose help in `i18n/strings.ts` and module `help.ts` files (running text is not a format control).
A string literal containing "OpenDocument text" or "OpenDocument spreadsheet" elsewhere is reported.
The baseline is empty.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "frontend" / "src"

FULL_NAME = re.compile(r"""(["'`])[^"'`\n]*OpenDocument (?:text|spreadsheet)[^"'`\n]*\1""", re.IGNORECASE)
MAP_FILE = SRC / "api" / "reportFormats.ts"


def violations() -> list[str]:
    """Returns `path:line: text` for every string literal that spells out an OpenDocument format name."""
    found = []
    for path in sorted([*SRC.rglob("*.ts"), *SRC.rglob("*.tsx")]):
        name = path.name
        if path == MAP_FILE or ".stories." in name or ".test." in name or name == "help.ts" or name == "strings.ts":
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            stripped = line.lstrip()
            if stripped.startswith(("*", "//", "/*")):
                continue
            if FULL_NAME.search(line):
                found.append(f"{path.relative_to(ROOT)}:{number}: {stripped.strip()}")
    return found


def main() -> int:
    """Prints each violation and returns a non-zero exit code when there are any."""
    found = violations()
    for item in found:
        print(item)
    if found:
        print(f"\n{len(found)} hand-written report format label(s); use REPORT_FORMAT (frontend/src/api/reportFormats.ts).")
        return 1
    print("Report format labels OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
