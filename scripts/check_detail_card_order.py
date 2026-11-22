#!/usr/bin/env python3
"""
Module: check_detail_card_order

Fails when a record detail page defeats the default card order (docs/ux-style-guide.md, "Pattern: detail page
card order"). `DetailLayout` sorts its direct children by rank (`frontend/src/components/detailCardOrder.ts`), so a
page keeps the order only when:

- its cards are direct children of `DetailLayout`, not inside a `<div className="stack">` written beside the
  `RecordHeader` (a wrapper hides them from the sort);
- a `DetailCard` that holds a `CommentThread` says `rank="discussion"`, so the comments are the last card;
- every `rank="..."` it writes is a rank that exists.

A page whose person arranges the sections passes `orderCards={false}` and is skipped; it states why beside the prop.
Checks `frontend/src/**/*.tsx`, stories excluded. The baseline of violations is empty.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "frontend" / "src"

RANKS = ("header", "body", "organising", "supporting", "discussion")
_CARD_OPEN = re.compile(r"<DetailCard\b(?P<attrs>[^>]*?)>", re.DOTALL)
_RANK = re.compile(r'\brank="([^"]*)"')
_HEADER = re.compile(r"^(?P<indent> *)<RecordHeader\b", re.M)


def violations_in(text: str) -> list[tuple[int, str]]:
    """Returns `(line, problem)` for each way the file defeats the card order.

    Args:
        text: The source of one `.tsx` file.

    Returns:
        The 1-based line and a short description for each violation; empty for a file that keeps the order or
        is not a detail page.
    """
    if "<DetailLayout" not in text or "<RecordHeader" not in text or "orderCards={false}" in text:
        return []
    found: list[tuple[int, str]] = []

    def line_of(pos: int) -> int:
        return text.count("\n", 0, pos) + 1

    header = _HEADER.search(text)
    if header:
        wrapper = f'{header.group("indent")}<div className="stack">'
        for match in re.finditer(r"^" + re.escape(wrapper) + r"$", text, re.M):
            found.append((line_of(match.start()), "a wrapper beside the RecordHeader hides its cards from the card order"))

    for match in _CARD_OPEN.finditer(text):
        attrs = match.group("attrs")
        rank = _RANK.search(attrs)
        if rank and rank.group(1) not in RANKS:
            found.append((line_of(match.start()), f'unknown rank "{rank.group(1)}"'))
        close = text.find("</DetailCard>", match.end())
        body = text[match.end(): close if close != -1 else len(text)]
        if "<CommentThread" in body and not (rank and rank.group(1) == "discussion"):
            found.append((line_of(match.start()), 'a card with comments needs rank="discussion"'))
    return sorted(found)


def violations() -> list[str]:
    """Returns `path:line: problem` for every violation in the frontend sources."""
    found = []
    for path in sorted(SRC.rglob("*.tsx")):
        if path.name.endswith(".stories.tsx"):
            continue
        rel = path.relative_to(SRC).as_posix()
        for line, problem in violations_in(path.read_text(encoding="utf-8")):
            found.append(f"{rel}:{line}: {problem}")
    return found


def main() -> int:
    """Prints each violation and exits 1 when there is any."""
    found = violations()
    for item in found:
        print(f'{item} (docs/ux-style-guide.md, "Pattern: detail page card order").')
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
