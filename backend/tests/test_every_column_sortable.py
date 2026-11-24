"""
Pins scripts/check_every_column_sortable.py: every `DirectoryColumn` data column is sortable
(docs/ux-style-guide.md, "Pattern: sortable column header").

Skipped when the repository root is not visible (the backend container mounts only backend/).
"""

import importlib.util
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_every_column_sortable.py"


def _load_checker():
    """Imports the checker script as a module; returns None if unavailable."""
    if not SCRIPT.is_file():
        return None
    try:
        subprocess.run(["git", "rev-parse"], cwd=SCRIPT.parent, check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    spec = importlib.util.spec_from_file_location("check_every_column_sortable", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


checker = _load_checker()
pytestmark = pytest.mark.skipif(checker is None or not checker.SRC.is_dir(), reason="frontend sources not available")


def test_every_data_column_is_sortable():
    """No list has a data column without `sortable`, except those named with a reason."""
    assert checker.find_problems() == []


def test_each_exemption_gives_its_reason():
    """Every unsortable column states why."""
    assert all(reason.strip() for reason in checker.UNSORTABLE.values())


def _columns(body: str) -> list[tuple[str, str]]:
    text = f"const columns: DirectoryColumn<Row>[] = [\n{body}\n];"
    match = checker.columns.ARRAY.search(text)
    return [(key, segment) for key, _label, segment in checker.columns.column_segments(text, match.end())]


def test_a_column_without_sortable_is_found():
    """A column that never mentions `sortable`, or says `sortable: false`, is not sortable."""
    found = _columns(
        '{ key: "a", label: "A", sortable: true, render: () => 1 },\n'
        '{ key: "b", label: "B", render: () => 2 },\n'
        '{ key: "c", label: "C", sortable: false, render: () => 3 },'
    )
    unsortable = [key for key, segment in found if not checker.SORTABLE.search(segment)]
    assert unsortable == ["b", "c"]
