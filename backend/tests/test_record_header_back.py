"""
Pins scripts/check_record_header_back.py: every record detail page's `RecordHeader` passes a `back` link
labelled with the destination list's plural name, never a typed arrow, a bare "Back" or the record's singular
name (docs/ux-style-guide.md, "Pattern: record header and object actions").

Skipped when the repository root is not visible (the backend container mounts only backend/); the script can
be run directly from the repository root.
"""

import importlib.util
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_record_header_back.py"


def _load_checker():
    """Imports the checker script as a module; returns None if unavailable."""
    if not SCRIPT.is_file():
        return None
    try:
        subprocess.run(["git", "rev-parse"], cwd=SCRIPT.parent, check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    spec = importlib.util.spec_from_file_location("check_record_header_back", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


checker = _load_checker()
pytestmark = pytest.mark.skipif(checker is None or not checker.SRC.is_dir(), reason="frontend sources not available")


def test_every_record_header_has_a_plural_back_link():
    """The baseline is empty: no detail page lacks a back link or labels it wrongly."""
    assert checker.violations() == []


def test_the_checker_flags_each_kind_of_mistake():
    """A header with no back link, a typed arrow, a bare Back or the singular name is reported."""
    missing = '<RecordHeader recordLabel="Risk" title="x" />'
    arrow = '<RecordHeader recordLabel="Risk" back={{ to: "/r", label: "← Risks" }} />'
    bare = '<RecordHeader recordLabel="Risk" back={{ onClick: f, label: "Back" }} />'
    singular = '<RecordHeader recordLabel="Risk" back={{ to: "/r", label: "Risk" }} />'
    good = '<RecordHeader recordLabel="Risk" back={{ to: "/r", label: strings.risks.title }} />'
    for source in (missing, arrow, bare, singular):
        assert len(checker.problems_in(source)) == 1, source
    assert checker.problems_in(good) == []
