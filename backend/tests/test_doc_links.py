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


def test_soc2_documents_may_not_name_plans_or_cite_phases(tmp_path, monkeypatch):
    """Audit evidence states the control and its rationale, never the plan or phase it was built in;
    other documentation under docs/ may still cite plans."""
    (tmp_path / "docs" / "plans").mkdir(parents=True)
    (tmp_path / "docs" / "plans" / "example-plan.md").write_text("# Example\n")
    (tmp_path / "docs" / "soc2" / "policies").mkdir(parents=True)
    (tmp_path / "docs" / "soc2" / "policies" / "p.md").write_text(
        "Added by example-plan and in Phase 4; see docs/" + "plans/example-plan.md.\n"
    )
    (tmp_path / "docs" / "guide.md").write_text("Built under example-plan, Phase 4.\n")
    monkeypatch.setattr(checker, "ROOT", tmp_path)
    problems = checker.check_file("docs/" + "soc2/policies/p.md")
    assert any("names a plan document" in p for p in problems)
    assert any("cites a plan phase" in p for p in problems)
    assert not any("plan" in p for p in checker.check_file("docs/" + "guide.md"))


# A literal plan path in a source file would trip the checker itself, so it is assembled.
PLANS = "do" + "cs/plans/"


def test_staged_scope_scans_only_what_a_commit_can_break():
    """A modified or added file is scanned alone; a removal, rename, added plan or a change to the checker scans all."""
    assert checker.staged_scope([("M", "notes/a.md"), ("A", "backend/app/x.py")]) == ["notes/a.md", "backend/app/x.py"]
    assert checker.staged_scope([("A", PLANS + "new-plan.md")]) is None
    assert checker.staged_scope([("A", PLANS + "completed/new-plan.md")]) is None
    assert checker.staged_scope([("D", "notes/a.md")]) is None
    assert checker.staged_scope([("R", "notes/a.md"), ("R", "notes/b.md")]) is None
    assert checker.staged_scope([("M", "scripts/check_doc_links.py")]) is None
    assert checker.staged_scope([]) == []


def test_scanning_some_files_gives_the_same_verdict_as_the_full_scan_for_them():
    """The fast form is the full check restricted to the named files, so it cannot disagree with it."""
    sample = [f for f in checker.tracked_files() if f.endswith((".md", ".py"))][::97]
    full = checker.find_problems()
    expected = [p for p in full if p.split(":", 1)[0] in set(sample)]
    assert checker.find_problems(sample) == expected


def test_a_broken_reference_in_a_scanned_file_is_found_by_the_fast_form(monkeypatch, tmp_path):
    """A dangling link in one named file is reported, and a clean file is not."""
    monkeypatch.setattr(checker, "ROOT", tmp_path)
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "a.md").write_text("[gone](missing.md)\n")
    (tmp_path / "notes" / "b.md").write_text("[here](a.md)\n")
    monkeypatch.setattr(checker, "tracked_files", lambda: ["notes/a.md", "notes/b.md"])
    assert checker.find_problems(["notes/a.md"]) == ["notes/a.md:1: link target missing: missing.md"]
    assert checker.find_problems(["notes/b.md"]) == []
