"""
Pins scripts/check_native_title.py: a control that opens a list, and a choice inside one, never carries a native `title`
(docs/ux-style-guide.md, "Pattern: help on interactive elements").

Skipped when the repository root is not visible (the backend container mounts only backend/); the script can be run directly
from the repository root.
"""

import importlib.util
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_native_title.py"


def _load_checker():
    """Imports the checker script as a module; returns None if unavailable."""
    if not SCRIPT.is_file():
        return None
    try:
        subprocess.run(["git", "rev-parse"], cwd=SCRIPT.parent, check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    spec = importlib.util.spec_from_file_location("check_native_title", SCRIPT)
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


def test_no_picker_or_choice_has_a_native_title():
    """The baseline is empty: every popup trigger, tree chevron, checkbox and radio uses the shared tooltip."""
    assert checker.violations() == []


@pytest.mark.parametrize(
    "source",
    [
        '<button type="button" aria-haspopup="menu" title="More">x</button>',
        '<button\n  type="button"\n  aria-haspopup="dialog"\n  onClick={() => open(a > b)}\n  title={label}\n>x</button>',
        '<button className="tree-toggle" title={`Collapse ${name}`} onClick={f}>x</button>',
        '<input type="checkbox" checked={c} title={reason} onChange={f} />',
        '<input type="radio" title="Why" />',
    ],
)
def test_a_native_title_on_a_picker_trigger_or_choice_fails(tmp_path, source):
    """A native `title` on a popup trigger, a tree chevron, a checkbox or a radio is reported, however the tag is wrapped."""
    assert len(_scan(tmp_path, f"export const A = () => ({source});\n")) == 1


@pytest.mark.parametrize(
    "source",
    [
        '<button type="button" aria-haspopup="menu" aria-label="More">x</button>',
        '<button type="button" title="Save">x</button>',
        '<input type="text" title="Name" />',
        '<button aria-haspopup="menu" onClick={() => show({ title: "x" })}>x</button>',
        '<Tooltip label="More"><button aria-haspopup="menu">x</button></Tooltip>',
    ],
)
def test_other_controls_and_a_title_inside_an_expression_pass(tmp_path, source):
    """A plain button, a text input, a `title` inside a handler and a tooltip-wrapped trigger are not this rule's business."""
    assert _scan(tmp_path, f"export const A = () => ({source});\n") == []
