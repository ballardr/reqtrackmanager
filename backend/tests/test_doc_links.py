"""
Pins scripts/check_doc_links.py: every documentation reference in the repository
must resolve, so moving or renaming a doc (for example archiving a closed plan
under docs/plans/completed/) cannot leave dangling references.

Skipped when the repository root is not visible (the backend container mounts
only backend/); CI's `docs` job and the pre-commit hook run the script directly.
"""

import importlib.util
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_doc_links.py"


def _load_checker():
    """Imports the checker script as a module; returns None if unavailable."""
    if not SCRIPT.is_file():
        return None
    try:
        subprocess.run(["git", "rev-parse"], cwd=SCRIPT.parent, check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    spec = importlib.util.spec_from_file_location("check_doc_links", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


checker = _load_checker()
pytestmark = pytest.mark.skipif(checker is None, reason="repository checkout not available")


def test_all_documentation_references_resolve():
    """Every tracked Markdown link and `docs/...md` mention points at an existing file."""
    assert checker.find_problems() == []


def test_checker_flags_a_dangling_mention(tmp_path, monkeypatch):
    """A `docs/` path that does not exist is reported, so the check cannot silently pass."""
    # Built by concatenation so the checker does not flag this test's own fixture text.
    (tmp_path / "note.md").write_text("See docs/" + "does-not-exist.md and [x](missing.md).\n")
    monkeypatch.setattr(checker, "ROOT", tmp_path)
    problems = checker.check_file("note.md")
    assert any("does-not-exist.md" in p for p in problems)
    assert any("missing.md" in p for p in problems)


def test_source_files_may_not_name_plan_documents(tmp_path, monkeypatch):
    """A code comment citing a plan document is reported; plans get archived, so source must not depend on them."""
    (tmp_path / "docs" / "plans").mkdir(parents=True)
    (tmp_path / "docs" / "plans" / "example-plan.md").write_text("# Example\n")
    (tmp_path / "mod.py").write_text('"""Built per example-plan.md Phase 2."""\n')
    (tmp_path / "other.py").write_text("# See docs/plans/" + "anything.md\n")
    monkeypatch.setattr(checker, "ROOT", tmp_path)
    assert any("names a plan document" in p for p in checker.check_file("mod.py"))
    assert any("names a plan document" in p for p in checker.check_file("other.py"))


def test_source_files_may_not_cite_plan_phases(tmp_path, monkeypatch):
    """A "Phase 7" tag in a comment is reported, including one wrapped across a comment line break."""
    (tmp_path / "docs" / "plans").mkdir(parents=True)
    (tmp_path / "a.py").write_text("# Added in Phase 7.\n")
    (tmp_path / "b.py").write_text("# Added in Phase\n# 3b of the work.\n")
    (tmp_path / "c.py").write_text('# A "Phase" label as a stage term is fine.\n')
    monkeypatch.setattr(checker, "ROOT", tmp_path)
    assert any("cites a plan phase" in p for p in checker.check_file("a.py"))
    assert any("cites a plan phase" in p for p in checker.check_file("b.py"))
    assert not any("cites a plan phase" in p for p in checker.check_file("c.py"))
