#!/usr/bin/env python3
"""
Module: check_record_header_back

Fails when a record detail page renders `RecordHeader` (frontend/src/components/RecordHeader.tsx) without a
`back` link, or with a label that breaks the rule in docs/ux-style-guide.md, "Pattern: record header and
object actions": the label is the destination list's plural name ("Pain Points"), without a leading arrow
(the header draws it) and never a bare "Back" or the record's own singular name.

Checks `frontend/src/**/*.tsx`, stories excluded. Only string literals are judged for the label; a label that
comes from a variable or the terminology strings is only checked for being present. The baseline is empty.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "frontend" / "src"

# Names whose singular and plural forms are the same word, so a list and its record legitimately share one.
UNCOUNTABLE = {"Evidence"}

_OPEN = re.compile(r"<RecordHeader\b")
_BACK = re.compile(r"\bback=")
_LITERAL = r'"([^"\n]*)"'
_LABEL = re.compile(r"\blabel:\s*" + _LITERAL)
_RECORD_LABEL = re.compile(r"\brecordLabel=\{?" + _LITERAL)


def _elements(text: str) -> list[tuple[int, str]]:
    """Returns `(start offset, source)` of every `<RecordHeader ... />` element in the text.

    Args:
        text: The source of one `.tsx` file.
    """
    found = []
    for match in _OPEN.finditer(text):
        depth = 0
        i = match.end()
        while i < len(text):
            ch = text[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            elif depth == 0 and text.startswith("/>", i):
                found.append((match.start(), text[match.start() : i + 2]))
                break
            elif depth == 0 and ch == ">":
                # Opening tag closed without self-closing: judge the opening tag only.
                found.append((match.start(), text[match.start() : i + 1]))
                break
            i += 1
    return found


def problems_in(text: str) -> list[tuple[int, str]]:
    """Returns `(line, problem)` for each `RecordHeader` in the text that breaks the back-link rule.

    Args:
        text: The source of one `.tsx` file.
    """
    found = []
    for start, source in _elements(text):
        line = text.count("\n", 0, start) + 1
        if not _BACK.search(source):
            found.append((line, "RecordHeader has no `back` link to its list"))
            continue
        label = _LABEL.search(source)
        if not label:
            continue
        name = label.group(1)
        record = _RECORD_LABEL.search(source)
        if name.lstrip().startswith("←"):
            found.append((line, f'back label "{name}" types the arrow; RecordHeader draws it'))
        elif name.strip().lower() == "back":
            found.append((line, 'back label "Back" names no destination; use the list\'s plural name'))
        elif record and name == record.group(1) and name not in UNCOUNTABLE:
            found.append((line, f'back label "{name}" is the record\'s singular name; use the list\'s plural name'))
    return found


def violations() -> list[str]:
    """Returns `path:line: problem` for every offending `RecordHeader`."""
    found = []
    for path in sorted(SRC.rglob("*.tsx")):
        if path.name.endswith(".stories.tsx") or path.name == "RecordHeader.tsx":
            continue
        rel = path.relative_to(SRC).as_posix()
        for line, problem in problems_in(path.read_text(encoding="utf-8")):
            found.append(f"{rel}:{line}: {problem}")
    return found


def main() -> int:
    """Prints each offending header and exits 1 when there is any."""
    found = violations()
    for item in found:
        print(item)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
