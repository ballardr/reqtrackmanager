#!/usr/bin/env python3
"""
Module: check_field_help

Fails when a frontend form field has neither `help` nor `helpNotNeeded`, so every non-obvious field
carries its `(?)` help (docs/ux-style-guide.md, "Pattern: field help") and a new field cannot skip the
decision.

Checks, in `frontend/src/**/*.tsx` (stories excluded), every use of the shared field components
(`TextField`, `TextAreaField`, `DateField`, `CheckboxField`, `ToggleField`, `ColorField`, `FileField`,
`UploadField`, `LabeledSelect`, `PrincipalFormField`, `RecordFieldGroup`).

Design notes:
- A ratchet, not a ban: `scripts/field_help_baseline.json` records how many undecided fields a file
  still has (forms not yet swept). A count may fall (then lower the baseline: run with `--update`) but
  not rise, and a file absent from the baseline allows none.
- `--list` prints every undecided field with its label, for the sweep.
- Combining `help` with `helpNotNeeded` is always an error: the opt-out is for fields that explain
  themselves.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "frontend" / "src"
BASELINE = Path(__file__).resolve().parent / "field_help_baseline.json"

FIELD_COMPONENTS = (
    "TextField", "TextAreaField", "DateField", "CheckboxField", "ToggleField", "ColorField", "FileField",
    "UploadField", "LabeledSelect", "PrincipalFormField", "RecordFieldGroup",
)
OPEN_TAG = re.compile(r"<(" + "|".join(FIELD_COMPONENTS) + r")(?=[\s/>])")
HELP = re.compile(r"(?<![\w-])help=")
NOT_NEEDED = re.compile(r"(?<![\w-])helpNotNeeded(?![\w-])")
LABEL = re.compile(r'(?<![\w-])label=(?:"([^"]*)"|\{([^}]*)\})')


def element_end(text: str, start: int) -> int:
    """Returns the index just past the `>` that closes the opening tag beginning at `start`.

    Tracks `{}` depth, string quotes and comments so a `>` inside an attribute expression (an arrow
    function) or an apostrophe in a comment does not end the tag at the wrong place.
    """
    depth = 0
    quote = ""
    i = start
    while i < len(text):
        c = text[i]
        if quote:
            if c == "\\":
                i += 1
            elif c == quote:
                quote = ""
        elif text.startswith("//", i):
            i = text.find("\n", i)
            if i < 0:
                return len(text)
        elif text.startswith("/*", i):
            i = text.find("*/", i) + 1
            if i <= 0:
                return len(text)
        elif c in "\"'`":
            quote = c
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        elif c == ">" and depth == 0:
            return i + 1
        i += 1
    return len(text)


def scan(path: Path) -> list[tuple[int, str, str, str]]:
    """Returns (line, component, label, state) per field in the file; state is `help`, `not-needed`, `both` or `undecided`."""
    text = path.read_text(encoding="utf-8")
    found = []
    for match in OPEN_TAG.finditer(text):
        tag = text[match.start():element_end(text, match.end())]
        label_match = LABEL.search(tag)
        label = (label_match.group(1) or label_match.group(2) or "").strip() if label_match else ""
        has_help, not_needed = bool(HELP.search(tag)), bool(NOT_NEEDED.search(tag))
        state = "both" if has_help and not_needed else "help" if has_help else "not-needed" if not_needed else "undecided"
        found.append((text.count("\n", 0, match.start()) + 1, match.group(1), label, state))
    return found


def source_files() -> list[Path]:
    """Returns the frontend component and page files to check (stories excluded)."""
    return [p for p in sorted(SRC.rglob("*.tsx")) if not p.name.endswith(".stories.tsx")]


def undecided_counts() -> dict[str, int]:
    """Returns {relative path: number of undecided fields} for every file that has any."""
    counts = {}
    for path in source_files():
        n = sum(1 for *_, state in scan(path) if state == "undecided")
        if n:
            counts[path.relative_to(SRC).as_posix()] = n
    return counts


def find_problems() -> list[str]:
    """Returns one message per `help` + `helpNotNeeded` clash and per file whose undecided count exceeds its baseline."""
    baseline = json.loads(BASELINE.read_text(encoding="utf-8")) if BASELINE.is_file() else {}
    problems = []
    for path in source_files():
        rel = path.relative_to(SRC).as_posix()
        for line, component, label, state in scan(path):
            if state == "both":
                problems.append(f"{rel}:{line}: <{component} label={label!r}> has both help and helpNotNeeded")
    for rel, n in undecided_counts().items():
        allowed = baseline.get(rel, 0)
        if n > allowed:
            problems.append(
                f"{rel}: {n} fields with neither `help` nor `helpNotNeeded` (allowed {allowed}); give each "
                "`help` (text from strings.help) or, if it explains itself, `helpNotNeeded`"
            )
    return problems


def main() -> int:
    if "--list" in sys.argv:
        for path in source_files():
            for line, component, label, state in scan(path):
                if state == "undecided":
                    print(f"{path.relative_to(SRC).as_posix()}:{line}\t{component}\t{label}")
        return 0
    if "--update" in sys.argv:
        BASELINE.write_text(json.dumps(undecided_counts(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {BASELINE.relative_to(ROOT)}")
        return 0
    problems = find_problems()
    for problem in problems:
        print(problem)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
