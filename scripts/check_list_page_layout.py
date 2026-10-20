#!/usr/bin/env python3
"""
Module: check_list_page_layout

Fails when a frontend page that has its own `<h1>` title lays out a list beside a side filter panel with a
hand-written `side-grid` instead of `ListPageLayout` (docs/ux-style-guide.md, "Pattern: filter panel
placement"). The shared layout puts the filter panel's top edge level with the page title and keeps page
settings (a scoring-model switcher, a view tab strip) in the list column, so they cannot push the filter
down; a hand-written grid under a title is how that regressed.

Checks `frontend/src/**/*.tsx`, stories excluded. A file that has both an `<h1` and `className="side-grid"`
must be listed in `EXEMPT` with the reason. The baseline of undecided files is empty.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "frontend" / "src"

# File (relative to frontend/src) -> why a title and a `side-grid` may share it.
EXEMPT = {
    "pages/OrgAdminPage.tsx": "An admin shell: the title belongs to the whole admin page and each `side-grid` is a section inside one of its tabs, not a page list.",
    "pages/ProjectAdminPage.tsx": "An admin shell: the title belongs to the whole admin page and each `side-grid` is a section inside one of its tabs, not a page list.",
}


def violations() -> list[str]:
    """Returns the files that have a page title and a hand-written `side-grid` without being exempt."""
    found = []
    for path in sorted(SRC.rglob("*.tsx")):
        if path.name.endswith(".stories.tsx"):
            continue
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(SRC).as_posix()
        if "<h1" in text and 'className="side-grid"' in text and rel not in EXEMPT:
            found.append(rel)
    return found


def main() -> int:
    """Prints each offending file and exits 1 when there is any."""
    found = violations()
    for rel in found:
        print(f"{rel}: has a page title and a hand-written `side-grid`; use ListPageLayout (components/ListPageLayout.tsx).")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
