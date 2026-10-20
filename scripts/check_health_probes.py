#!/usr/bin/env python3
"""
Module: check_health_probes

Fails when a container health probe addresses the container as `localhost`.

Why: inside a container `localhost` may resolve to `::1` first. BusyBox `wget`
does not fall back to IPv4, so a service bound to IPv4 only (nginx here) is
reported unhealthy for ever on such a host while the app works. `127.0.0.1`
behaves the same everywhere.

Responsibilities:
- Scan every Dockerfile `HEALTHCHECK` and every Compose `healthcheck.test`
  that runs `curl` or `wget`; report any whose URL host is `localhost`.
- Exit non-zero if any is found.

Used by: the `docs` CI job, .githooks/pre-commit and
backend/tests/test_health_probes.py. Standard library only.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {"node_modules", ".git", "build", "graphify-out", "test-results"}
PROBE_TOOL = re.compile(r"\b(curl|wget)\b")
LOCALHOST_URL = re.compile(r"https?://localhost\b")


def probe_files() -> list[Path]:
    """Returns every Dockerfile and Compose file in the repository."""
    found = []
    for path in ROOT.rglob("*"):
        if SKIP_DIRS & set(path.relative_to(ROOT).parts) or not path.is_file():
            continue
        if path.name.startswith("Dockerfile") or re.fullmatch(r"docker-compose[\w.-]*\.ya?ml", path.name):
            found.append(path)
    return sorted(found)


def check_text(text: str) -> list[int]:
    """Returns the 1-based line numbers of probe commands that use `localhost`.

    A Dockerfile probe is the `CMD` continuation after `HEALTHCHECK`; a Compose
    probe is a `test:` line. Comment lines are ignored.
    """
    bad = []
    lines = text.splitlines()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#") or not LOCALHOST_URL.search(line) or not PROBE_TOOL.search(line):
            continue
        in_compose_test = stripped.startswith("test:")
        in_dockerfile_probe = stripped.startswith("CMD") and i > 0 and lines[i - 1].lstrip().startswith("HEALTHCHECK")
        if in_compose_test or in_dockerfile_probe:
            bad.append(i + 1)
    return bad


def find_problems() -> list[str]:
    """Returns one message per offending probe across the repository."""
    problems = []
    for path in probe_files():
        for lineno in check_text(path.read_text()):
            problems.append(f"{path.relative_to(ROOT)}:{lineno}: health probe uses `localhost`; use 127.0.0.1")
    return problems


def main() -> int:
    """Prints problems and returns the process exit code."""
    problems = find_problems()
    for problem in problems:
        print(problem)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
