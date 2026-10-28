"""
Module: export_starter_trees

Writes the starter report layouts' trees to `frontend/src/testing/starterLayoutTrees.json`, the fixture the document
view's round-trip test (`utils/reportLayoutDoc.stories.tsx`) reads, so that test covers what the server really ships.

Run from `backend/` with the project virtualenv: `python scripts/export_starter_trees.py`. A backend test
(`tests/test_report_starters.py`) fails when the file is out of date.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.main import app  # noqa: F401  (importing the app registers every module's starter sections)
from app.services.report_starters import STARTERS

TARGET = Path(__file__).resolve().parents[2] / "frontend" / "src" / "testing" / "starterLayoutTrees.json"


def main() -> None:
    """Writes the fixture."""
    TARGET.write_text(
        json.dumps({s.key: s.tree for s in STARTERS}, indent=1, sort_keys=True, ensure_ascii=False), encoding="utf-8",
    )
    print(f"wrote {TARGET}")


if __name__ == "__main__":
    main()
