"""
Pins scripts/check_optional_columns.py: every list of five or more data columns offers the column chooser
(docs/ux-style-guide.md, "Pattern: column chooser").

Skipped when the repository root is not visible (the backend container mounts only backend/); the script can
be run directly from the repository root.
"""

import importlib.util
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_optional_columns.py"


def _load_checker():
    """Imports the checker script as a module; returns None if unavailable."""
    if not SCRIPT.is_file():
        return None
    try:
        subprocess.run(["git", "rev-parse"], cwd=SCRIPT.parent, check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    spec = importlib.util.spec_from_file_location("check_optional_columns", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


checker = _load_checker()
pytestmark = pytest.mark.skipif(checker is None or not checker.SRC.is_dir(), reason="frontend sources not available")

FIVE = "const columns: DirectoryColumn<Row>[] = [\n" + "".join(f'  {{ key: "c{i}", label: "C{i}" }},\n' for i in range(5)) + "];"


def test_every_long_list_offers_a_chooser():
    """No file builds a column set of five or more data columns without the chooser."""
    assert checker.find_problems() == []


def test_a_named_exemption_gives_its_reason():
    """Each file exempt from the chooser states why, and still draws a column set."""
    for rel, reason in checker.NO_CHOOSER.items():
        assert reason.strip()
        assert "DirectoryColumn<" in (checker.SRC / rel).read_text(encoding="utf-8")


def test_five_data_columns_are_counted():
    """Five keyed columns count as five."""
    assert checker.data_column_counts(FIVE) == [5]


def test_actions_and_hidden_label_columns_are_not_data_columns():
    """An actions column and a column labelled with a visually hidden span are not counted."""
    text = (
        'const columns: DirectoryColumn<Row>[] = [\n'
        '  { key: "a", label: "A" }, { key: "b", label: "B" }, { key: "actions", label: "" },\n'
        '  { key: "use", label: <span className="sr-only">Use</span> },\n'
        "];"
    )
    assert checker.data_column_counts(text) == [2]


def test_a_key_inside_a_cell_is_not_a_column():
    """A `key:` in a menu item a cell draws is deeper than a column and is not counted."""
    text = (
        'const columns: DirectoryColumn<Row>[] = [\n'
        '  { key: "a", label: "A", render: (r) => <Menu items={[{ key: "x" }, { key: "y" }]} /> },\n'
        "];"
    )
    assert checker.data_column_counts(text) == [1]


def test_a_quote_in_a_comment_does_not_shift_the_count():
    """An apostrophe in a comment is not the start of a string literal."""
    text = FIVE.replace("[\n", "[\n  // the backend's rule\n", 1)
    assert checker.data_column_counts(text) == [5]
