#!/usr/bin/env python3
"""
Module: check_graph_canvas_imports

Fails when React Flow (`@xyflow/react`) is imported anywhere except `components/GraphCanvasView.tsx` and the
stories/tests that exercise it. `GraphCanvas.tsx` loads that view lazily, so the library stays out of the main
bundle and every consumer (architecture diagrams, workflow capture, glossary) draws through one wrapper with one
set of accessibility, theming and sanitising rules; a second direct import would bypass all three.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "frontend" / "src"

ALLOWED = {"GraphCanvasView.tsx"}
IMPORT = re.compile(r"""(?:from\s+|import\s*\(\s*|import\s+)["']@xyflow/""")


def violations() -> list[str]:
    """Returns `path:line: message` for every import of `@xyflow/*` outside the allowed view."""
    found = []
    for path in sorted([*SRC.rglob("*.ts"), *SRC.rglob("*.tsx")]):
        if path.name in ALLOWED or path.name.endswith((".stories.tsx", ".test.tsx", ".test.ts")):
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if IMPORT.search(line):
                where = f"{path.relative_to(SRC).as_posix()}:{number}"
                found.append(f"{where}: imports @xyflow; draw through components/GraphCanvas instead.")
    return found


def main() -> int:
    """Prints each offending line and exits 1 when there is any."""
    found = violations()
    for item in found:
        print(item)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
