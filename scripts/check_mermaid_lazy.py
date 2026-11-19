#!/usr/bin/env python3
"""
Module: check_mermaid_lazy

Fails when the Mermaid library is part of the files the browser loads for every page, so a page that shows no
diagram never pays for it (docs/modules.md, Markdown and diagrams).

Reads `frontend/dist/index.html` (after `npm run build`), takes the script and module-preload files it names, and
fails when one contains `UnknownDiagramError` (a class only the library defines) or when no
separate Mermaid chunk exists at all (the dynamic import was lost).

Usage: python scripts/check_mermaid_lazy.py [dist-directory]
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARKER = "UnknownDiagramError"


def main(argv: list[str]) -> int:
    """
    Checks the built page's start-up files for the Mermaid library.

    Args:
        argv: Optional first argument, the build directory (default `frontend/dist`).

    Returns:
        0 when Mermaid is only in lazily loaded chunks, 1 otherwise.
    """
    dist = Path(argv[1]) if len(argv) > 1 else ROOT / "frontend" / "dist"
    index = dist / "index.html"
    if not index.is_file():
        print(f"check_mermaid_lazy: {index} not found; run `npm run build` in frontend/ first")
        return 1
    html = index.read_text(encoding="utf-8")
    startup = {m for m in re.findall(r'(?:src|href)="/(assets/[^"]+\.js)"', html)}
    problems = [f"{name} loads on every page and contains the Mermaid library" for name in sorted(startup)
                if MARKER in (dist / name).read_text(encoding="utf-8", errors="ignore")]
    lazy = [p for p in (dist / "assets").glob("*.js") if f"assets/{p.name}" not in startup and MARKER in p.read_text(encoding="utf-8", errors="ignore")]
    if not lazy:
        problems.append("no separate chunk contains Mermaid: the dynamic import was lost")
    for problem in problems:
        print(f"check_mermaid_lazy: {problem}")
    if not problems:
        print(f"check_mermaid_lazy: Mermaid is lazy-loaded ({len(startup)} start-up files checked, {len(lazy)} Mermaid chunk(s))")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
