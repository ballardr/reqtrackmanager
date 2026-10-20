"""
Pins scripts/check_field_help.py: every frontend form field either carries `help` or opts out with
`helpNotNeeded`, so a new field cannot skip the decision about its `(?)` help
(docs/ux-style-guide.md, "Pattern: field help").

Skipped when the repository root is not visible (the backend container mounts only backend/); the
script can be run directly from the repository root.
"""

import importlib.util
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_field_help.py"


def _load_checker():
    """Imports the checker script as a module; returns None if unavailable."""
    if not SCRIPT.is_file():
        return None
    try:
        subprocess.run(["git", "rev-parse"], cwd=SCRIPT.parent, check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    spec = importlib.util.spec_from_file_location("check_field_help", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


checker = _load_checker()
pytestmark = pytest.mark.skipif(checker is None or not checker.SRC.is_dir(), reason="frontend sources not available")


def _states(tmp_path, source):
    """Returns the (component, label, state) of every field in a one-file source snippet."""
    path = tmp_path / "Form.tsx"
    path.write_text(source, encoding="utf-8")
    return [(component, label, state) for _, component, label, state in checker.scan(path)]


def test_no_file_exceeds_its_undecided_field_baseline():
    """Every field has `help` or `helpNotNeeded`, and none has both."""
    assert checker.find_problems() == []


def test_classifies_help_not_needed_and_undecided_fields(tmp_path):
    """A field with neither prop is undecided; `help=` and `helpNotNeeded` each decide it."""
    states = _states(tmp_path, """
        <TextField label="Name" value="" onChange={x} />
        <TextField label="Name" helpNotNeeded value="" onChange={x} />
        <LabeledSelect label="Level" help={strings.help.requirementLevel} value="" onChange={x} options={[]} />
        <TextField label="Both" help="x" helpNotNeeded value="" onChange={x} />
    """)
    assert [s for *_, s in states] == ["undecided", "not-needed", "help", "both"]


def test_an_apostrophe_in_a_comment_does_not_swallow_the_next_attribute(tmp_path):
    """A comment inside an attribute expression is skipped, so its apostrophe cannot hide a later `help`."""
    states = _states(tmp_path, """
        <LabeledSelect
          label="Parent"
          onChange={(next) => {
            // a *different* parent's role-holders
            set(next);
          }}
        />
        <TextField label="Next" help="x" value="" onChange={x} />
    """)
    assert [s for *_, s in states] == ["undecided", "help"]


def test_an_arrow_function_in_an_attribute_does_not_end_the_tag(tmp_path):
    """The `>` of `=>` inside braces is not the end of the opening tag."""
    states = _states(tmp_path, '<DateField label="Due" onChange={(v) => set(v)} helpNotNeeded value="" />')
    assert [s for *_, s in states] == ["not-needed"]
