"""
Pins scripts/check_markdown_summary.py: a card or cell never cuts text by hand with an ellipsis, and a math-capable
Markdown field read as a plain string keeps its equations (docs/ux-style-guide.md, "Pattern: Markdown fields").

Skipped when the repository root is not visible (the backend container mounts only backend/); the script can be run
directly from the repository root.
"""

import importlib.util
import subprocess
import tempfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_markdown_summary.py"


def _load_checker():
    """Imports the checker script as a module; returns None if unavailable."""
    if not SCRIPT.is_file():
        return None
    try:
        subprocess.run(["git", "rev-parse"], cwd=SCRIPT.parent, check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    spec = importlib.util.spec_from_file_location("check_markdown_summary", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


checker = _load_checker()
pytestmark = pytest.mark.skipif(checker is None or not checker.SRC.is_dir(), reason="frontend sources not available")


def _check(source: str) -> list[str]:
    """What the checker says about one source, by running it on a temporary source tree."""
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        (root / "Some.tsx").write_text(source, encoding="utf-8")
        original = checker.SRC
        checker.SRC = root
        try:
            return checker.violations()
        finally:
            checker.SRC = original


def test_no_card_or_cell_cuts_text_by_hand_or_loses_an_equation():
    """The baseline is empty."""
    assert checker.violations() == []


@pytest.mark.parametrize("source", [
    "const a = text.length > 140 ? `${text.slice(0, 140)}…` : text;",
    "const a = `${r.reasoning.slice(0, 140)} …`;",
])
def test_a_hand_written_ellipsis_cut_is_reported(source):
    assert len(_check(source)) == 1


@pytest.mark.parametrize("source", [
    "const a = markdownPlainText(q.question);",
    "const a = markdownPlainText(item.proposed_reasoning, { limit: 80 });",
])
def test_a_math_field_read_without_math_is_reported(source):
    assert len(_check(source)) == 1


@pytest.mark.parametrize("source", [
    "const a = markdownPlainText(q.question, { math: true });",
    "const a = markdownPlainText(note.description);",
    "const a = text.slice(0, 4);",
    "// ellipsis-ok: SVG text\nconst a = `${text.slice(0, 9)}…`;",
])
def test_other_uses_are_not_reported(source):
    assert _check(source) == []
