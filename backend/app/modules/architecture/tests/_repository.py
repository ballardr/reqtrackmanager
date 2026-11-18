"""Where the repository's frontend files are, for the tests that compare a backend rule with the shared cases file the frontend
runs too. The backend image holds only `backend/`, so inside it those files are not there and such a test is skipped; on a
host checkout (the developer's virtual environment) it runs."""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[5]
FRONTEND_SRC = REPO_ROOT / "frontend" / "src"

needs_repository = pytest.mark.skipif(not FRONTEND_SRC.is_dir(), reason="the repository's frontend files are not visible (backend image)")
