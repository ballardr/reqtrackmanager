"""
Module: tests.test_pre_commit_hook

Pins which checks `.githooks/pre-commit` runs for which staged files. The hook is run for real in a throwaway git
repository whose check scripts are stubs that record being called, so a narrowed trigger pattern cannot silently stop a
check from running on the files it guards, and an unrelated file does not pay for a check it cannot break.

Skipped when the repository root is not visible (the backend container mounts only backend/).
"""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / ".githooks" / "pre-commit"
pytestmark = pytest.mark.skipif(
    not HOOK.is_file() or shutil.which("git") is None or shutil.which("bash") is None,
    reason="repository checkout not available",
)

# Each stub script the hook calls, by the name the log records.
STUBS = {
    "scripts/check-playwright-image-sync.py": "playwright-sync",
    "scripts/check_doc_links.py": "doc-links",
    "perf/scrub_check.py": "perf-scrub",
    "scripts/check_licences.py": "licences",
    "scripts/check_cla.py": "cla",
    "scripts/check_health_probes.py": "health-probes",
}


def _run_hook(tmp_path: Path, staged: list[str]) -> list[str]:
    """Stages `staged` in a new repository holding the hook and stub checks; returns the checks the hook ran."""
    repo = tmp_path / "repo"
    (repo / ".githooks").mkdir(parents=True)
    shutil.copy(HOOK, repo / ".githooks" / "pre-commit")
    log = tmp_path / "calls.log"
    for script, name in STUBS.items():
        target = repo / script
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"import sys\nopen({str(log)!r}, 'a').write('{name} ' + ' '.join(sys.argv[1:]) + '\\n')\n")
    git = ["git", "-C", str(repo)]
    subprocess.run([*git, "init", "-q"], check=True)
    for path in staged:
        file = repo / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("x\n")
        subprocess.run([*git, "add", path], check=True)
    subprocess.run(["bash", str(repo / ".githooks" / "pre-commit")], cwd=repo, check=True, capture_output=True)
    return sorted(line.strip() for line in log.read_text().splitlines()) if log.exists() else []


# Assembled, so this file does not itself name a documentation path that the link checker would look for.
DOCS = "do" + "cs/"


@pytest.mark.parametrize(
    ("staged", "expected"),
    [
        (["notes.txt.bin"], []),
        (["image.png"], []),
        (["backend/app/x.py"], ["doc-links --staged"]),
        ([DOCS + "guide.md"], ["doc-links --staged"]),
        (["frontend/src/a.tsx"], ["doc-links --staged"]),
        ([".github/workflows/ci.yml"], ["doc-links --staged", "playwright-sync"]),
        (["perf/results/run.json"], ["perf-scrub --tracked"]),
        (["backend/requirements.txt"], ["doc-links --staged", "licences"]),
        (["backend/Dockerfile"], ["health-probes", "licences"]),
        (["docker-compose.yml"], ["doc-links --staged", "health-probes"]),
        ([".github/cla-signatories.json"], ["cla"]),
        (["CLA.md"], ["cla", "doc-links --staged"]),
        (["scripts/licence_policy.json"], ["licences"]),
        (["frontend/public/licences/third-party-notices.json"], ["licences"]),
    ],
)
def test_each_check_runs_for_the_files_it_guards_and_no_others(tmp_path, staged, expected):
    """The set of checks the hook runs for a commit is exactly the set whose guarded files it stages."""
    assert _run_hook(tmp_path, staged) == sorted(expected)
