"""
Pins scripts/check_list_sort.py: every frontend list of records that has a filter panel and the shared Export draws a
**Sort by** field (docs/ux-style-guide.md, "Pattern: list sort"), and every exemption is still needed.

Skipped when the repository root is not visible (the backend container mounts only backend/); the script can be run
directly from the repository root.
"""

import importlib.util
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_list_sort.py"


def _load_checker():
    """Imports the checker script as a module; returns None if unavailable."""
    if not SCRIPT.is_file():
        return None
    try:
        subprocess.run(["git", "rev-parse"], cwd=SCRIPT.parent, check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    spec = importlib.util.spec_from_file_location("check_list_sort", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


checker = _load_checker()
pytestmark = pytest.mark.skipif(checker is None or not checker.SRC.is_dir(), reason="frontend sources not available")


def test_every_record_list_has_a_sort_by_field():
    """No list with a filter panel and the list Export lacks a `SortField`, outside the reasoned exemptions."""
    assert checker.violations() == []


def test_every_exemption_is_still_needed():
    assert checker.stale_exemptions() == []


def test_every_exemption_gives_a_reason():
    assert all(reason.strip() for reason in checker.NO_SORT.values())
