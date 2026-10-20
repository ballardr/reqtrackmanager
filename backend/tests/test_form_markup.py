"""
Pins scripts/check_form_markup.py: a frontend form must be built from the shared field components
and FormActions, so a hand-written labelled field or Cancel/Save row cannot creep back in after the
forms sweep (docs/ux-style-guide.md, "Building a form").

Skipped when the repository root is not visible (the backend container mounts only backend/); the
script can be run directly from the repository root.
"""

import importlib.util
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_form_markup.py"


def _load_checker():
    """Imports the checker script as a module; returns None if unavailable."""
    if not SCRIPT.is_file():
        return None
    try:
        subprocess.run(["git", "rev-parse"], cwd=SCRIPT.parent, check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    spec = importlib.util.spec_from_file_location("check_form_markup", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


checker = _load_checker()
pytestmark = pytest.mark.skipif(checker is None or not checker.SRC.is_dir(), reason="frontend sources not available")


def test_no_file_exceeds_its_hand_rolled_form_markup_baseline():
    """No file has more hand-written labelled fields or Cancel/Save rows than the recorded baseline."""
    assert checker.find_problems() == []


def test_detects_a_hand_rolled_field_and_footer():
    """The patterns the checker looks for match the markup the shared components replace."""
    field = '<label className="stack" style={{ gap: "0.25rem" }}><span>Name</span><input className="input" /></label>'
    footer = '<button className="btn" onClick={x}>Cancel</button>\n<button className="btn btn-primary" onClick={y}>Save</button>'
    assert checker.FIELD.search(field)
    assert checker.FOOTER.search(footer)
    assert not checker.FIELD.search('<TextField label="Name" value="" onChange={x} />')
