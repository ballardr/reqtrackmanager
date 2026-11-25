"""
Pins scripts/check_lifecycle_track.py: no record detail page hands `RecordHeader` hand-drawn transition buttons
(`transitions=`) or a status control (`stateMenu=`); a record with states passes `lifecycle`
(docs/ux-style-guide.md, "Pattern: lifecycle track and Promote").

Skipped when the repository root is not visible (the backend container mounts only backend/); the script can
be run directly from the repository root.
"""

import importlib.util
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_lifecycle_track.py"


def _load_checker():
    """Imports the checker script as a module; returns None if unavailable."""
    if not SCRIPT.is_file():
        return None
    try:
        subprocess.run(["git", "rev-parse"], cwd=SCRIPT.parent, check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    spec = importlib.util.spec_from_file_location("check_lifecycle_track", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


checker = _load_checker()
pytestmark = pytest.mark.skipif(checker is None or not checker.SRC.is_dir(), reason="frontend sources not available")


def test_no_page_draws_its_own_state_controls():
    """The baseline is empty: every page with states passes `lifecycle`."""
    assert checker.violations() == []


def test_the_checker_flags_hand_drawn_state_controls():
    """A `transitions=` or `stateMenu=` prop is reported; a `lifecycle` prop and a nested button are not."""
    transitions = '<RecordHeader recordLabel="Risk" back={b} transitions={<button className="btn">Approve</button>} />'
    state_menu = '<RecordHeader recordLabel="Risk" back={b} stateMenu={<Controls />} />'
    good = '<RecordHeader recordLabel="Risk" back={b} lifecycle={{ steps, current }} />'
    assert len(checker.problems_in(transitions)) == 1
    assert len(checker.problems_in(state_menu)) == 1
    assert checker.problems_in(good) == []
