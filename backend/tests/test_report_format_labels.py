"""
Pins scripts/check_report_format_labels.py: a report format control names OpenDocument text and spreadsheet through
the shared `REPORT_FORMAT` map (acronym label, full-name tooltip), never a hand-written full name.

Skipped when the repository root is not visible (the backend container mounts only backend/); the script can
be run directly from the repository root.
"""

import importlib.util
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_report_format_labels.py"


def _load_checker():
    """Imports the checker script as a module; returns None if unavailable."""
    if not SCRIPT.is_file():
        return None
    try:
        subprocess.run(["git", "rev-parse"], cwd=SCRIPT.parent, check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    spec = importlib.util.spec_from_file_location("check_report_format_labels", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


checker = _load_checker()
pytestmark = pytest.mark.skipif(checker is None or not checker.SRC.is_dir(), reason="frontend sources not available")


def test_no_format_label_is_hand_written():
    """The baseline is empty: every OpenDocument format name comes from the shared map."""
    assert checker.violations() == []


@pytest.mark.parametrize("line", ['odt: "OpenDocument text",', "label: `Download OpenDocument spreadsheet report`"])
def test_the_pattern_catches_a_spelled_out_format_name(line):
    """The labels this check replaced would be caught again."""
    assert checker.FULL_NAME.search(line)


@pytest.mark.parametrize("line", ['label: "ODT"', 'label: "Download ODS report"'])
def test_the_acronym_is_fine(line):
    """The acronym is the label."""
    assert not checker.FULL_NAME.search(line)
