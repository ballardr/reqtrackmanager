"""
Pins scripts/check_markdown_fields.py: a frontend long-text field is Markdown or plain text with a stated reason
(docs/ux-style-guide.md, "Pattern: Markdown fields"), so a field added later cannot be a third, undecided kind.

Skipped when the repository root is not visible (the backend container mounts only backend/); the script can be run
directly from the repository root.
"""

import importlib.util
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_markdown_fields.py"


def _load_checker():
    """Imports the checker script as a module; returns None if unavailable."""
    if not SCRIPT.is_file():
        return None
    try:
        subprocess.run(["git", "rev-parse"], cwd=SCRIPT.parent, check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    spec = importlib.util.spec_from_file_location("check_markdown_fields", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


checker = _load_checker()
pytestmark = pytest.mark.skipif(checker is None or not checker.SRC.is_dir(), reason="frontend sources not available")


def _check(tag: str, element: str, name: str = "Some.tsx") -> list[str]:
    """What the checker says about one element, by running it on a temporary source tree."""
    import tempfile

    with tempfile.TemporaryDirectory() as folder:
        source = Path(folder)
        (source / name).write_text(f"export const x = ({element});\n", encoding="utf-8")
        original = checker.SRC
        checker.SRC = source
        try:
            return checker.violations()
        finally:
            checker.SRC = original


def test_every_long_text_field_is_markdown_or_says_why_not():
    """The baseline is empty."""
    assert checker.violations() == []


@pytest.mark.parametrize("element", [
    "<TextAreaField markdown label='a' />",
    '<TextAreaField markdown="simple" label="a" />',
    '<TextAreaField markdown="math" label="a" />',
    '<TextAreaField plainText="One line" label="a" />',
    "<TextAreaField\n  label={x}\n  plainText={'A reason'}\n  onChange={(v) => set({ a: v })}\n/>",
])
def test_a_decided_text_area_field_passes(element):
    assert _check("TextAreaField", element) == []


@pytest.mark.parametrize("element", [
    "<TextAreaField label='a' />",
    '<TextAreaField plainText="" label="a" />',
    "<TextAreaField plainText label='a' />",
    '<TextAreaField markdown plainText="both" label="a" />',
])
def test_an_undecided_or_unreasoned_text_area_field_is_caught(element):
    assert len(_check("TextAreaField", element)) == 1


def test_a_raw_growing_textarea_needs_a_reason_outside_the_editor_components():
    assert len(_check("AutoGrowTextarea", "<AutoGrowTextarea rows={2} value={v} onChange={set} />")) == 1
    assert _check("AutoGrowTextarea", '<AutoGrowTextarea plainText="Layout source" value={v} onChange={set} />') == []
    assert _check("AutoGrowTextarea", "<AutoGrowTextarea value={v} onChange={set} />", name="MarkdownEditor.tsx") == []
