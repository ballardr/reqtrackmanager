"""
Pins scripts/check_detail_cards.py: a `DetailCard` never holds another card, so detail pages keep one level of
cards (docs/ux-style-guide.md, "Pattern: detail page content").

Skipped when the repository root is not visible (the backend container mounts only backend/); the script can
be run directly from the repository root.
"""

import importlib.util
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_detail_cards.py"


def _load_checker():
    """Imports the checker script as a module; returns None if unavailable."""
    if not SCRIPT.is_file():
        return None
    try:
        subprocess.run(["git", "rev-parse"], cwd=SCRIPT.parent, check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    spec = importlib.util.spec_from_file_location("check_detail_cards", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


checker = _load_checker()
pytestmark = pytest.mark.skipif(checker is None or not checker.SRC.is_dir(), reason="frontend sources not available")


def test_no_detail_card_holds_another_card():
    """The baseline is empty."""
    assert checker.violations() == []


def test_the_checker_finds_a_card_inside_a_detail_card():
    """A hand-written card, or a second DetailCard, between the tags is reported; siblings are not."""
    nested = (
        '<DetailCard heading="A">\n  <div className="card stack">x</div>\n</DetailCard>\n'
        '<DetailCard>\n  <DetailCard heading="B">y</DetailCard>\n</DetailCard>\n'
    )
    assert checker.nested_cards(nested) == [2, 5]
    siblings = '<DetailCard><p>x</p></DetailCard>\n<div className="card">z</div>\n<DetailCard><p>y</p></DetailCard>\n'
    assert checker.nested_cards(siblings) == []
    assert checker.nested_cards('<DetailCard heading="a" />\n<div className="card" />\n') == []
