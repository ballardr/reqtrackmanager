"""
Pins scripts/check_comment_style.py: no source comment or docstring in the repository narrates the
conversation or the code's history, and the checker still detects each pattern it claims to.

Skipped when the repository root is not visible (the backend container mounts only backend/); CI's
`docs` job and the pre-commit hook run the script directly.
"""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_comment_style.py"


def _load_checker():
    """Imports the checker script as a module; returns None if unavailable."""
    if not SCRIPT.is_file():
        return None
    try:
        subprocess.run(["git", "rev-parse"], cwd=SCRIPT.parent, check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    spec = importlib.util.spec_from_file_location("check_comment_style", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


checker = _load_checker()
pytestmark = pytest.mark.skipif(checker is None, reason="repository checkout not available")


def _labels(rel: str, text: str) -> list[str]:
    """Returns the finding labels the checker reports for one file's text."""
    return [p.split(": ")[1] for p in checker.check_text(rel, text)]


def test_repository_comments_describe_the_code():
    """Every tracked source file is free of conversational, dated, history and plan-reference comments."""
    assert checker.find_problems() == []


# The fixtures below build each flagged phrase by concatenation so this file does not contain it verbatim.
HISTORY = "previous" + "ly"
LONGER = "no lon" + "ger accepts"
ASKED = "the user " + "asked for this"
DATE = "2026-" + "10-04"
PHASE = "Phas" + "e 12"


def test_python_comment_and_docstring_patterns_are_flagged():
    """A `#` comment and a docstring are both scanned, and each pattern reports its own label."""
    source = (
        f'"""Module docstring, {HISTORY} different."""\n'
        f"# {ASKED}\n"
        f"# raised {DATE}\n"
        f"x = 1  # {LONGER} a role\n"
        f"def f():\n"
        f'    """Does a thing ({PHASE})."""\n'
    )
    labels = _labels("mod.py", source)
    assert "history wording" in labels
    assert "conversational or review wording" in labels
    assert "date" in labels
    assert "plan or phase reference" in labels
    assert labels.count("history wording") == 2


def test_typescript_comments_are_flagged_but_strings_are_not():
    """`//`, `/* */` and JSDoc comments are scanned; the same words in a string, template or URL are code."""
    source = (
        f"// {ASKED}\n"
        f"/** {HISTORY} this took a role. */\n"
        f'const a = "// {ASKED}";\n'
        f"const b = `${{x}} // {ASKED} ${{y}}`;\n"
        f'const url = "https://example.test/{DATE}";\n'
        f"const re = /\\/\\/ {HISTORY}/;\n"
    )
    labels = _labels("a.ts", source)
    assert labels == ["conversational or review wording", "history wording"]


def test_apostrophe_in_jsx_text_does_not_swallow_following_comments():
    """A stray apostrophe in JSX text ends at the line break, so a later comment is still scanned."""
    source = f"const a = <p>Don't</p>;\n// {ASKED}\n"
    assert _labels("a.tsx", source) == ["conversational or review wording"]


def test_hash_files_scan_whole_line_and_trailing_comments_only():
    """YAML and shell comments are scanned; a `#` inside a quoted value is not a comment."""
    source = f'key: "a # {HISTORY} b"\n# {HISTORY} this took a role\nrun: x  # raised {DATE}\n'
    labels = _labels("c.yml", source)
    assert labels == ["history wording", "date"]


def test_domain_wording_is_not_flagged():
    """Everyday words with a runtime meaning are not history: only the story-telling phrases are."""
    source = (
        "# Resolves the projects a scope covers once per request.\n"
        "# A token that is no longer valid is rejected.\n"
        "# Returns the previously issued token.\n"
        "now = datetime.now()  # the current instant in UTC\n"
    )
    assert _labels("ok.py", source) == []


def test_exemption_marker_allows_a_flagged_word_with_a_reason():
    """A comment carrying `comment-style-ok: <reason>` is skipped."""
    source = f"# {HISTORY} stored values are read as-is. comment-style-ok: stored data is described\n"
    assert _labels("ok.py", source) == []


def test_generated_alembic_date_header_is_not_flagged():
    """The `Create Date:` line Alembic writes into a migration docstring is not commentary."""
    source = f'"""Add a column.\n\nRevision ID: 0001\nCreate Date: {DATE}\n"""\n'
    assert _labels("mig.py", source) == []


def test_candidates_report_long_blocks_without_failing_the_text_check():
    """A block over the limit is an advisory candidate; only the candidates mode reports it."""
    block = "".join(f"# line {i} explains a constraint\n" for i in range(checker.BLOCK_LIMIT + 1))
    assert checker.check_text("long.py", block) == []
    assert any("candidate: comment block" in p for p in checker.check_text("long.py", block, candidates=True))


def test_a_named_file_list_scans_only_those_files(tmp_path, monkeypatch):
    """`find_problems(only=...)` reads just the listed files, never the rest of the repository, so a commit stays fast."""
    (tmp_path / "bad.py").write_text(f"# {HISTORY} this took a role\n")
    (tmp_path / "other.py").write_text(f"# {HISTORY} this took a role\n")
    monkeypatch.setattr(checker, "ROOT", tmp_path)
    monkeypatch.setattr(checker, "tracked_files", lambda: pytest.fail("the whole repository was listed"))
    problems = checker.find_problems(["bad.py"])
    assert [p.split(":")[0] for p in problems] == ["bad.py"]
