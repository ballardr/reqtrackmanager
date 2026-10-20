#!/usr/bin/env python3
"""
Module: check_detail_cards

Fails when a `DetailCard` (frontend/src/components/DetailCard.tsx) holds another card in the same file: a
`className="card ..."` element or a second `<DetailCard>` written between its opening and closing tags.
Cards never nest (docs/ux-style-guide.md, "Pattern: detail page content"): a record's fields go in one
`DetailCard` and each panel is its own card beside it, not inside it.

Checks `frontend/src/**/*.tsx`, stories excluded. Only what is written inside the tags in one file is
visible here; a component that draws its own card and is placed inside a `DetailCard` is caught in review
and by that component's story. The baseline of violations is empty.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "frontend" / "src"

_TAG = re.compile(r"</?DetailCard\b[^>]*?(/?)>", re.DOTALL)
# `card` as its own class, not a part of another (`entity-accent-card` is a row with an accent edge, not a card).
_CARD = re.compile(r'className="(?:[^"]*\s)?card(?:\s[^"]*)?"')


def nested_cards(text: str) -> list[int]:
    """Returns the 1-based line numbers inside a `DetailCard` where another card starts.

    Args:
        text: The source of one `.tsx` file.
    """
    found: list[int] = []
    depth = 0
    pos = 0
    for match in _TAG.finditer(text):
        # Anything between the previous tag and this one is inside `depth` open DetailCards.
        if depth > 0:
            for card in _CARD.finditer(text, pos, match.start()):
                found.append(text.count("\n", 0, card.start()) + 1)
        raw = match.group(0)
        if raw.startswith("</"):
            depth = max(0, depth - 1)
        elif not match.group(1):
            if depth > 0:
                found.append(text.count("\n", 0, match.start()) + 1)
            depth += 1
        pos = match.end()
    return sorted(set(found))


def violations() -> list[str]:
    """Returns `path:line` for every card written directly inside a `DetailCard`."""
    found = []
    for path in sorted(SRC.rglob("*.tsx")):
        if path.name.endswith(".stories.tsx") or path.name == "DetailCard.tsx":
            continue
        rel = path.relative_to(SRC).as_posix()
        for line in nested_cards(path.read_text(encoding="utf-8")):
            found.append(f"{rel}:{line}")
    return found


def main() -> int:
    """Prints each nested card and exits 1 when there is any."""
    found = violations()
    for where in found:
        print(f"{where}: a card inside a DetailCard; cards never nest (docs/ux-style-guide.md, \"Pattern: detail page content\").")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
