"""
Pins scripts/check_list_page_layout.py: a page with its own title lays a side-filtered list out with
`ListPageLayout`, never a hand-written `side-grid`, so the filter panel stays level with the title and page
settings cannot push it down (docs/ux-style-guide.md, "Pattern: filter panel placement").

Skipped when the repository root is not visible (the backend container mounts only backend/); the script can
be run directly from the repository root.
"""

import importlib.util
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_list_page_layout.py"


def _load_checker():
    """Imports the checker script as a module; returns None if unavailable."""
    if not SCRIPT.is_file():
        return None
    try:
        subprocess.run(["git", "rev-parse"], cwd=SCRIPT.parent, check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    spec = importlib.util.spec_from_file_location("check_list_page_layout", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


checker = _load_checker()
pytestmark = pytest.mark.skipif(checker is None or not checker.SRC.is_dir(), reason="frontend sources not available")


def test_no_titled_page_hand_writes_a_side_grid():
    """The baseline is empty: every titled list page uses ListPageLayout (admin shells are exempt, with a reason)."""
    assert checker.violations() == []


def test_every_exemption_names_a_real_file_and_a_reason():
    """An exemption that no longer matches a file, or has no reason, is dead weight that hides a regression."""
    for rel, reason in checker.EXEMPT.items():
        assert (checker.SRC / rel).is_file(), rel
        assert len(reason) > 20, rel
