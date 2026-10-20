#!/usr/bin/env python3
"""
Module: check_required_markers

Fails when a frontend form label says it is optional ("(optional)", "optional)" or an "optional" suffix in a
label), because a required field is marked with a `*` through the shared field components' `required` prop and
an unmarked field is optional (docs/ux-style-guide.md, "Pattern: required fields"). Words such as "Optional"
in running help or hint text are not labels and are not checked.

Checks `frontend/src/**/*.tsx` and `frontend/src/i18n/strings.ts`, stories excluded: a string literal that
ends in "(optional)" or contains "(optional" / ", optional)" is reported. The baseline is empty.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "frontend" / "src"

OPTIONAL_LABEL = re.compile(r"""(["'`])[^"'`\n]*(?:\(optional[^"'`\n]*\)|,\s*optional\))[^"'`\n]*\1""", re.IGNORECASE)


def violations() -> list[str]:
    """Returns `path:line: text` for every label that marks itself optional."""
    found = []
    for path in sorted([*SRC.rglob("*.tsx"), SRC / "i18n" / "strings.ts"]):
        if path.name.endswith(".stories.tsx"):
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            stripped = line.lstrip()
            if stripped.startswith(("//", "*", "/*")):
                continue
            match = OPTIONAL_LABEL.search(line)
            if match:
                found.append(f"{path.relative_to(SRC).as_posix()}:{number}: {match.group(0)}")
    return found


def main() -> int:
    """Prints each offending label and exits 1 when there is any."""
    found = violations()
    for item in found:
        print(f"{item}: mark the other fields required instead of calling this one optional.")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
