"""
Pins scripts/check_required_markers.py: a form label never calls itself optional; required fields carry a `*`
through the shared field components' `required` prop and an unmarked field is optional
(docs/ux-style-guide.md, "Pattern: required fields").

Skipped when the repository root is not visible (the backend container mounts only backend/); the script can
be run directly from the repository root.
"""

import importlib.util
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_required_markers.py"


def _load_checker():
    """Imports the checker script as a module; returns None if unavailable."""
    if not SCRIPT.is_file():
        return None
    try:
        subprocess.run(["git", "rev-parse"], cwd=SCRIPT.parent, check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    spec = importlib.util.spec_from_file_location("check_required_markers", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


checker = _load_checker()
pytestmark = pytest.mark.skipif(checker is None or not checker.SRC.is_dir(), reason="frontend sources not available")


def test_no_label_calls_itself_optional():
    """The baseline is empty: no form label carries "(optional)" or an equivalent suffix."""
    assert checker.violations() == []


@pytest.mark.parametrize("label", ['label="Due date (optional)"', "label: 'Comment (optional)'", 'label="Recurs (days, optional)"'])
def test_the_pattern_catches_the_forms_the_sweep_removed(label, tmp_path):
    """The labels the sweep removed would be caught again."""
    assert checker.OPTIONAL_LABEL.search(label)


@pytest.mark.parametrize("text", ['hint="Optional. Links are added when the record is saved."', 'label="Optionality"'])
def test_prose_that_mentions_optional_is_not_a_label(text):
    """Running hint text may use the word; only a parenthesised suffix in a string is a label."""
    assert not checker.OPTIONAL_LABEL.search(text)
