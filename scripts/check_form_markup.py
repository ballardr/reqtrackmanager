#!/usr/bin/env python3
"""
Module: check_form_markup

Fails when a frontend form re-introduces markup the shared form components replace, so the forms sweep
(docs/ux-style-guide.md, "Pattern: forms") cannot be undone one hand-rolled field at a time.

Flags, in `frontend/src/**/*.tsx` (stories excluded), per file:
- `hand-rolled-field`: a `<label className="stack" style={{ gap: "0.25rem" }}>` block, which is what
  `TextField`, `TextAreaField`, `DateField`, `LabeledSelect` and `PrincipalFormField` render.
- `hand-rolled-footer`: a `Cancel` button immediately followed by a primary button in a
  `justifyContent: "flex-end"` row, which is `FormActions`.

Design notes:
- A ratchet, not a ban: `scripts/form_markup_baseline.json` records how many of each a file still has
  (forms not yet migrated). A count may fall (then lower the baseline: run with `--update`) but not rise,
  and a file absent from the baseline allows none.
- The shared components themselves are exempt: they are where the markup lives.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "frontend" / "src"
BASELINE = Path(__file__).resolve().parent / "form_markup_baseline.json"

EXEMPT = {
    "components/FormFields.tsx",
    "components/FieldHelp.tsx",  # `FieldShell` renders the labelled block the field components share
    "components/LabeledSelect.tsx",
    "components/PrincipalFormField.tsx",
    "components/FormActions.tsx",
    "components/FilterPanel.tsx",  # `FilterField` is the filter bar's own labelled field
}

FIELD = re.compile(r'<label className="stack" style=\{\{ gap: "0\.25rem"[^}]*\}\}>')
FOOTER = re.compile(
    r'<button[^>]*className="btn"[^>]*>\s*(?:Cancel|\{strings\.common\.cancel\})\s*</button>\s*<button[^>]*btn btn-primary',
    re.S,
)


def count_markup() -> dict[str, dict[str, int]]:
    """Returns {relative path: {kind: count}} for every frontend file with hand-rolled form markup."""
    found: dict[str, dict[str, int]] = {}
    for path in sorted(SRC.rglob("*.tsx")):
        rel = path.relative_to(SRC).as_posix()
        if rel.endswith(".stories.tsx") or rel in EXEMPT:
            continue
        text = path.read_text(encoding="utf-8")
        counts = {
            "hand-rolled-field": len(FIELD.findall(text)),
            "hand-rolled-footer": len(FOOTER.findall(text)),
        }
        counts = {kind: n for kind, n in counts.items() if n}
        if counts:
            found[rel] = counts
    return found


def find_problems() -> list[str]:
    """Returns one message per file whose count of a kind exceeds its baseline."""
    baseline = json.loads(BASELINE.read_text(encoding="utf-8")) if BASELINE.is_file() else {}
    problems = []
    for rel, counts in count_markup().items():
        for kind, n in counts.items():
            allowed = baseline.get(rel, {}).get(kind, 0)
            if n > allowed:
                problems.append(
                    f"{rel}: {n} {kind} (allowed {allowed}); use the shared component "
                    "(TextField/TextAreaField/DateField/LabeledSelect/PrincipalFormField/FormActions)"
                )
    return problems


def main() -> int:
    if "--update" in sys.argv:
        BASELINE.write_text(json.dumps(count_markup(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {BASELINE.relative_to(ROOT)}")
        return 0
    problems = find_problems()
    for problem in problems:
        print(problem)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
