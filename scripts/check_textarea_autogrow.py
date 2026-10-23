#!/usr/bin/env python3
"""
Module: check_textarea_autogrow

Fails when a frontend free-text field is a fixed-height box, so long prose always grows with its content
(docs/ux-style-guide.md, "Pattern: auto-growing textarea"). The baseline is empty.

Checks `frontend/src/**/*.tsx` (stories and tests excluded):
- a raw `<textarea` anywhere except the two components that implement the grow behaviour
  (`AutoGrowTextarea.tsx`, and the fixed-height branch in `FormFields.tsx`, both skipped): use
  `TextAreaField` (labelled form field) or `AutoGrowTextarea` (caption-less inline editor);
- a `TextAreaField` whose `fixedHeight` opt-out has no reason (bare, or an empty string).
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "frontend" / "src"

IMPLEMENTATIONS = {"AutoGrowTextarea.tsx", "FormFields.tsx"}
RAW_TEXTAREA = re.compile(r"<textarea(?![\w-])")
EMPTY_OPT_OUT = re.compile(r"""(?<![\w-])fixedHeight(?:(?![\w=])|=(?:""|''|\{\s*(?:""|'')\s*\}))""")


def violations() -> list[str]:
    """Returns `path:line: message` for every fixed-height textarea without a stated reason."""
    found = []
    for path in sorted(SRC.rglob("*.tsx")):
        if path.name.endswith((".stories.tsx", ".test.tsx")) or path.name in IMPLEMENTATIONS:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if line.lstrip().startswith(("//", "*", "/*")):
                continue
            where = f"{path.relative_to(SRC).as_posix()}:{number}"
            if RAW_TEXTAREA.search(line):
                found.append(f"{where}: raw <textarea>; use TextAreaField or AutoGrowTextarea so the box grows.")
            if EMPTY_OPT_OUT.search(line):
                found.append(f"{where}: fixedHeight needs a reason, e.g. fixedHeight=\"a one-line note\".")
    return found


def main() -> int:
    """Prints each offending line and exits 1 when there is any."""
    found = violations()
    for item in found:
        print(item)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
