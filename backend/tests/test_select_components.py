"""
Pins scripts/check_select_components.py: every single-choice select is `FilterSelect`, `LabeledSelect` or
`InlineSelect`, never a hand-written `<select>` (docs/ux-style-guide.md, "Pattern: selects").

Skipped when the repository root is not visible (the backend container mounts only backend/); the script can
be run directly from the repository root.
"""

import importlib.util
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_select_components.py"


def _load_checker():
    """Imports the checker script as a module; returns None if unavailable."""
    if not SCRIPT.is_file():
        return None
    try:
        subprocess.run(["git", "rev-parse"], cwd=SCRIPT.parent, check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    spec = importlib.util.spec_from_file_location("check_select_components", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


checker = _load_checker()
pytestmark = pytest.mark.skipif(checker is None or not checker.SRC.is_dir(), reason="frontend sources not available")


def test_no_hand_written_select():
    """The baseline is empty: every select goes through a shared component."""
    assert checker.violations() == []


@pytest.mark.parametrize("text", ["<select", "<select\n", '<select className="input"'])
def test_a_raw_select_is_caught(text):
    """A hand-written select outside the implementing files is a violation."""
    assert checker.RAW_SELECT.search(text)


@pytest.mark.parametrize("text", ["<FilterSelect", "<InlineSelect", "<LabeledSelect", "<selected>", "a <select-all> mention"])
def test_the_shared_selects_are_not_raw_selects(text):
    """The shared select components are the sanctioned way to write one."""
    assert not checker.RAW_SELECT.search(text)
