"""
Pins scripts/check_help_beside_button.py: a button, toggle or menu trigger shows its help as a tooltip on the control, never
as a `(?)` beside it (docs/ux-style-guide.md, "Pattern: help on interactive elements").

Skipped when the repository root is not visible (the backend container mounts only backend/); the script can be run directly
from the repository root.
"""

import importlib.util
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_help_beside_button.py"


def _load_checker():
    """Imports the checker script as a module; returns None if unavailable."""
    if not SCRIPT.is_file():
        return None
    try:
        subprocess.run(["git", "rev-parse"], cwd=SCRIPT.parent, check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    spec = importlib.util.spec_from_file_location("check_help_beside_button", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


checker = _load_checker()
pytestmark = pytest.mark.skipif(checker is None or not checker.SRC.is_dir(), reason="frontend sources not available")


def _scan(tmp_path, source: str) -> list[str]:
    """Runs the checker over one temporary `.tsx` file and returns its findings."""
    (tmp_path / "Sample.tsx").write_text(source, encoding="utf-8")
    original = checker.SRC
    checker.SRC = tmp_path
    try:
        return checker.violations()
    finally:
        checker.SRC = original


def test_no_help_button_sits_beside_a_button():
    """The product has no `FieldHelp` beside a button (the baseline is empty)."""
    assert checker.violations() == []


def test_a_help_button_beside_a_button_fails(tmp_path):
    """A `FieldHelp` next to a `<button>`, a `MenuButton` or a `ToggleButton` is reported, however it is guarded."""
    source = (
        "export const A = () => (\n"
        "  <span>\n"
        '    <button type="button" className="btn btn-sm">Go</button>\n'
        '    <FieldHelp label="Go" help="x" />\n'
        "  </span>\n"
        ");\n"
        "export const B = () => (\n"
        "  <span>\n"
        '    <MenuButton label="New" items={[]} />\n'
        '    {help && <FieldHelp label="New" help={help} />}\n'
        "  </span>\n"
        ");\n"
    )
    assert len(_scan(tmp_path, source)) == 2


def test_a_caption_help_button_passes(tmp_path):
    """A `FieldHelp` beside a caption or a plain heading is the caption's own help and is allowed."""
    source = (
        "export const A = () => (\n"
        "  <span>\n"
        "    <span>Title</span>\n"
        '    <FieldHelp label="Title" help="x" />\n'
        "  </span>\n"
        ");\n"
    )
    assert _scan(tmp_path, source) == []
