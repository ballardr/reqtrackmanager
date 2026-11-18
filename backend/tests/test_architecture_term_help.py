"""
Pins scripts/check_architecture_term_help.py: a System Architecture notation or domain term shows its help wherever
it is drawn as a heading, column header or Selection card label (docs/ux-style-guide.md, "Pattern: field help").

Skipped when the repository root is not visible (the backend container mounts only backend/); the script can be run
directly from the repository root.
"""

import importlib.util
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_architecture_term_help.py"
HELP = (
    'export const T = [\n  { label: "Route", help: ARCHITECTURE_HELP.outlineRoute },\n'
    '  { label: "Ports", help: ARCHITECTURE_HELP.elementPorts },\n];\n'
)


def _load_checker():
    """Imports the checker script as a module; returns None if unavailable."""
    if not SCRIPT.is_file():
        return None
    try:
        subprocess.run(["git", "rev-parse"], cwd=SCRIPT.parent, check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    spec = importlib.util.spec_from_file_location("check_architecture_term_help", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


checker = _load_checker()
pytestmark = pytest.mark.skipif(checker is None or not checker.MODULE.is_dir(), reason="frontend sources not available")


def _scan(tmp_path, source: str) -> list[str]:
    """Runs the checker over one temporary `.tsx` file next to a term list and returns its findings."""
    (tmp_path / "help.ts").write_text(HELP, encoding="utf-8")
    (tmp_path / "Sample.tsx").write_text(source, encoding="utf-8")
    original = checker.MODULE
    checker.MODULE = tmp_path
    try:
        return checker.violations()
    finally:
        checker.MODULE = original


def test_the_module_has_no_term_without_help():
    """Every listed term is drawn with help and every listed term is used."""
    assert checker.violations() == []
    assert checker.unused() == []


def test_a_bare_column_header_is_flagged(tmp_path):
    """A `<th>` that holds only a listed term is a violation."""
    assert len(_scan(tmp_path, '<th scope="col">Route</th>\n')) == 1


def test_a_bare_selection_label_is_flagged(tmp_path):
    """A `<dt>` that holds only a listed term is a violation."""
    assert len(_scan(tmp_path, '<dt className="text-muted">Route</dt>\n')) == 1


def test_a_heading_without_help_is_flagged_and_with_help_is_not(tmp_path):
    """A card heading or section title for a listed term needs `help` in the same tag."""
    assert len(_scan(tmp_path, '<DetailCard heading="Ports">\n')) == 1
    assert _scan(tmp_path, '<DetailCard heading="Ports" help={ARCHITECTURE_HELP.elementPorts}>\n') == []
    assert len(_scan(tmp_path, '<CollapsibleSection sectionKey="x" title="Route" variant="plain">\n')) == 1


def test_a_term_field_that_opts_out_of_help_is_flagged(tmp_path):
    """A field whose label is a listed term cannot say `helpNotNeeded`."""
    assert len(_scan(tmp_path, '<RecordFieldGroup helpNotNeeded label="Route">\n')) == 1


def test_a_help_header_is_accepted(tmp_path):
    """The shared `HelpHeader` is the compliant shape for a column."""
    assert _scan(tmp_path, '<HelpHeader label="Route" help={ARCHITECTURE_HELP.outlineRoute} />\n') == []
