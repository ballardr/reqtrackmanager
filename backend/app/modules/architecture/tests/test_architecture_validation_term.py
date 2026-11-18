"""Pins the one term for a state machine diagram's modelling checks: **Validation**, with an `error` or `warning` for
each result. "Finding" is the Engagements module's own record, so no text of this module (a docstring, a message, the
API, a frontend label) uses it for a check result; the frontend and the MCP server are checked when the repository root
is visible (the backend container mounts only backend/)."""

import re
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parents[1]
ROOT = MODULE.parents[3]
SELF = Path(__file__).name
WORD = re.compile(r"\bfindings?\b", re.IGNORECASE)


def _hits(directory: Path, suffixes: tuple[str, ...], skip: tuple[str, ...] = ()) -> list[str]:
    """Returns `path:line` for every use of the old term under `directory`."""
    found = []
    for path in sorted(directory.rglob("*")):
        if path.suffix not in suffixes or path.name == SELF or "node_modules" in path.parts:
            continue
        if any(path.name.endswith(s) for s in skip):
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if WORD.search(line):
                found.append(f"{path.relative_to(directory)}:{number}")
    return found


def test_the_backend_module_never_calls_a_check_result_a_finding():
    assert _hits(MODULE, (".py", ".md")) == []


@pytest.mark.skipif(not (ROOT / "frontend" / "src" / "modules" / "architecture").is_dir(), reason="frontend sources not available")
def test_the_frontend_module_never_calls_a_check_result_a_finding():
    assert _hits(ROOT / "frontend" / "src" / "modules" / "architecture", (".ts", ".tsx")) == []
