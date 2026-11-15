#!/usr/bin/env python3
"""
Module: check_architecture_term_help

Fails when a System Architecture notation or domain term (`ARCHITECTURE_TERMS` in
`frontend/src/modules/architecture/help.ts`) is drawn as a card heading, section title, column header or
Selection card label with no help, or when a listed term is used by no surface. A term's help is the one
text every surface for it shows (docs/ux-style-guide.md, "Pattern: field help"); a term added later joins
the list with its help in the same change. The baseline is empty.

Checks `frontend/src/modules/architecture/*.tsx` (stories and tests excluded). A bare label is a violation
when it is: a `<th>` with the term as its only text, a `<dt>` with the term as its only text, a `DetailCard`
`heading` or `CollapsibleSection` `title` with no `help` in the same opening tag, or a field or record group
with `label` equal to the term and `helpNotNeeded`.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "frontend" / "src" / "modules" / "architecture"
HELP_FILE = "help.ts"

TERM = re.compile(r'\{ label: "([^"]+)", help: ARCHITECTURE_HELP\.(\w+) \}')
# How many lines of an opening tag are read for a `help` prop.
OPENING_LINES = 4


def terms() -> dict[str, str]:
    """Returns the listed terms as `{label: help key}`, read from `help.ts`."""
    return {label: key for label, key in TERM.findall((MODULE / HELP_FILE).read_text(encoding="utf-8"))}


def _sources() -> list[Path]:
    """Returns the module's surface files: every `.tsx` that is not a story or a test."""
    return sorted(p for p in MODULE.glob("*.tsx") if not p.name.endswith((".stories.tsx", ".test.tsx")))


def _opening(lines: list[str], index: int) -> str:
    """Returns the text of the tag opening at `lines[index]`, up to the line that closes it."""
    parts = []
    for line in lines[index:index + OPENING_LINES]:
        parts.append(line.strip())
        if line.rstrip().endswith(">"):
            break
    return " ".join(parts)


def violations() -> list[str]:
    """Returns `path:line: message` for every listed term drawn without help."""
    found = []
    listed = terms()
    for path in _sources():
        lines = path.read_text(encoding="utf-8").splitlines()
        for number, line in enumerate(lines):
            for label in listed:
                quoted = re.escape(label)
                bare = (
                    re.search(rf"<th(?: scope=\"col\")?>{quoted}</th>", line)
                    or re.search(rf"<dt(?: className=\"[^\"]*\")?>{quoted}</dt>", line)
                )
                heading = re.search(rf"(?:DetailCard heading|CollapsibleSection[^\n]*? title)=\"{quoted}\"", line)
                if heading and "help=" not in _opening(lines, number) and "help=" not in line:
                    bare = True
                if re.search(rf"label=\"{quoted}\"", line) and "helpNotNeeded" in _opening(lines, number):
                    bare = True
                if bare:
                    where = f"{path.relative_to(MODULE).as_posix()}:{number + 1}"
                    found.append(f"{where}: term \"{label}\" has no help; use its ARCHITECTURE_TERMS text.")
    return found


def unused() -> list[str]:
    """Returns a message for every listed term that no surface uses (by its help key or `TermCaption`)."""
    text = "\n".join(p.read_text(encoding="utf-8") for p in _sources() if p.name != "TermCaption.tsx")
    return [
        f"help.ts: term \"{label}\" is used by no surface; use ARCHITECTURE_HELP.{key} or remove it from the list."
        for label, key in terms().items()
        if f"ARCHITECTURE_HELP.{key}" not in text and f'term="{label}"' not in text
    ]


def main() -> int:
    """Prints each finding and exits 1 when there is any."""
    found = violations() + unused()
    for item in found:
        print(item)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
