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


def test_every_list_has_a_sortable_column():
    """No file renders a table with no sortable column, and the baseline is empty (it only ever shrank to here)."""
    assert checker.find_problems() == []
    assert checker.baseline() == []


def test_a_list_with_no_natural_order_gives_its_reason():
    """The only tables left unsortable are named with a reason, and each still renders a table."""
    for rel, reason in checker.NO_NATURAL_ORDER.items():
        assert reason.strip()
        assert checker.TABLE.search((checker.SRC / rel).read_text(encoding="utf-8"))


def test_the_system_architecture_lists_are_sortable():
    """The three lists of the System Architecture page and the organisation panel sort on a header click."""
    for page in ("ProjectElementsPage", "ProjectConnectionsPage", "ProjectDiagramsPage", "OrgElementsPanel"):
        text = (checker.SRC / "modules" / "architecture" / f"{page}.tsx").read_text(encoding="utf-8")
        assert checker.SORTABLE.search(text)


@pytest.mark.parametrize("text", ["<DirectoryTable", "<DirectoryTable\n  ariaLabel", "  <DirectoryTable ariaLabel"])
def test_a_directory_table_is_found(text):
    """A rendered table is recognised however its props are laid out."""
    assert checker.TABLE.search(text)


@pytest.mark.parametrize("text", ["<DirectoryTableFoo", "import { DirectoryTable } from", "<DirectoryTable-x"])
def test_other_mentions_are_not_a_table(text):
    """An import or a longer component name is not a rendered table."""
    assert not checker.TABLE.search(text)


@pytest.mark.parametrize("text", ["{ key: 'name', sortable: true }", "sortable", "onSort={table.onSort}"])
def test_a_sortable_column_is_found(text):
    """A column marked sortable, or a table wired to a sort whose columns are built elsewhere, satisfies the check."""
    assert checker.SORTABLE.search(text)
