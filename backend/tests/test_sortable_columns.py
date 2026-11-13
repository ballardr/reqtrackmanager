"""
Pins scripts/check_sortable_columns.py: every `DirectoryTable` list makes its naturally ordered columns sortable
(docs/ux-style-guide.md, "Pattern: sortable column header").

Skipped when the repository root is not visible (the backend container mounts only backend/); the script can
be run directly from the repository root.
"""

import importlib.util
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_sortable_columns.py"


def _load_checker():
    """Imports the checker script as a module; returns None if unavailable."""
    if not SCRIPT.is_file():
        return None
    try:
        subprocess.run(["git", "rev-parse"], cwd=SCRIPT.parent, check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    spec = importlib.util.spec_from_file_location("check_sortable_columns", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


checker = _load_checker()
pytestmark = pytest.mark.skipif(checker is None or not checker.SRC.is_dir(), reason="frontend sources not available")


def test_no_list_joins_the_unsortable_baseline():
    """A file with a table and no sortable column is in the baseline, and a baseline file that was fixed has left it."""
    assert checker.find_problems() == []


def test_the_system_architecture_lists_are_sortable():
    """The three lists of the System Architecture page are not in the baseline: each has sortable columns."""
    listed = set(checker.baseline())
    for page in ("ProjectElementsPage", "ProjectConnectionsPage", "ProjectDiagramsPage"):
        assert f"modules/architecture/{page}.tsx" not in listed


@pytest.mark.parametrize("text", ["<DirectoryTable", "<DirectoryTable\n  ariaLabel", "  <DirectoryTable ariaLabel"])
def test_a_directory_table_is_found(text):
    """A rendered table is recognised however its props are laid out."""
    assert checker.TABLE.search(text)


@pytest.mark.parametrize("text", ["<DirectoryTableFoo", "import { DirectoryTable } from", "<DirectoryTable-x"])
def test_other_mentions_are_not_a_table(text):
    """An import or a longer component name is not a rendered table."""
    assert not checker.TABLE.search(text)


@pytest.mark.parametrize("text", ["{ key: 'name', sortable: true }", "sortable"])
def test_a_sortable_column_is_found(text):
    """A column marked sortable satisfies the check."""
    assert checker.SORTABLE.search(text)
