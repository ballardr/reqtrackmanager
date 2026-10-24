"""
Pins scripts/check_textarea_autogrow.py: long free-text fields grow with their content; a fixed-height box is
an explicit opt-out with a stated reason (docs/ux-style-guide.md, "Pattern: auto-growing textarea").

Skipped when the repository root is not visible (the backend container mounts only backend/); the script can
be run directly from the repository root.
"""

import importlib.util
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_textarea_autogrow.py"


def _load_checker():
    """Imports the checker script as a module; returns None if unavailable."""
    if not SCRIPT.is_file():
        return None
    try:
        subprocess.run(["git", "rev-parse"], cwd=SCRIPT.parent, check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    spec = importlib.util.spec_from_file_location("check_textarea_autogrow", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


checker = _load_checker()
pytestmark = pytest.mark.skipif(checker is None or not checker.SRC.is_dir(), reason="frontend sources not available")


def test_no_fixed_height_textarea_without_a_reason():
    """The baseline is empty: every textarea grows, or opts out with a reason."""
    assert checker.violations() == []


@pytest.mark.parametrize("text", ["<textarea", "<textarea\n", '<textarea className="input"'])
def test_a_raw_textarea_is_caught(text):
    """A hand-written textarea outside the two implementing components is a violation."""
    assert checker.RAW_TEXTAREA.search(text)


@pytest.mark.parametrize("text", ["<AutoGrowTextarea", "<TextAreaField", "a <textareas> mention"])
def test_the_shared_components_are_not_raw_textareas(text):
    """The shared growing components are the sanctioned way to write one."""
    assert not checker.RAW_TEXTAREA.search(text)


@pytest.mark.parametrize("text", ["<TextAreaField fixedHeight", 'fixedHeight=""', "fixedHeight={''}", "fixedHeight />"])
def test_an_opt_out_without_a_reason_is_caught(text):
    """`fixedHeight` must say why the box stays short."""
    assert checker.EMPTY_OPT_OUT.search(text)


def test_an_opt_out_with_a_reason_is_allowed():
    """A stated reason is the opt-out."""
    assert not checker.EMPTY_OPT_OUT.search('<TextAreaField fixedHeight="a one-line note" />')
    assert not checker.EMPTY_OPT_OUT.search("fixedHeight={reason}")
