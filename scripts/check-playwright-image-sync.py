#!/usr/bin/env python3
"""
Module: check-playwright-image-sync

Fails when a Playwright container image tag in .github/workflows/ci.yml does
not match the `playwright-core` version resolved by the lockfile of the
project that runs in that container.

Why: Playwright requires the npm package and the browser build to be the same
release. A lockfile bump without a matching image bump makes the browser fail
to launch; vitest then runs zero tests and writes a valid, failure-free
report, so the drift is easy to miss (it published a 0% coverage badge once).

Responsibilities:
- Map each `mcr.microsoft.com/playwright:vX.Y.Z-*` tag to its CI job
  (JOB_LOCKFILES) and compare it with that job's lockfile.
- Print an actionable message per mismatch; exit non-zero if any.

Used by: the `frontend` and `e2e-tests` CI jobs (first step) and
.githooks/pre-commit. Standard library only, so it runs in the bare
Playwright container. Run from anywhere: paths resolve from the repo root.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"

# CI job key -> lockfile of the project whose tests run in that job's image.
JOB_LOCKFILES = {
    "frontend": ROOT / "frontend" / "package-lock.json",
    "e2e-tests": ROOT / "tests" / "playwright" / "package-lock.json",
}

IMAGE_TAG = re.compile(r"mcr\.microsoft\.com/playwright:v(\d+\.\d+\.\d+)-\w+")
JOB_KEY = re.compile(r"^  ([A-Za-z0-9_-]+):\s*$")


def locked_version(lockfile: Path) -> str:
    """
    Reads the resolved `playwright-core` version from an npm lockfile.

    Args:
        lockfile: Path to a package-lock.json.

    Returns:
        The resolved version string, e.g. "1.63.0".

    Raises:
        KeyError: If the lockfile has no playwright-core entry.
        FileNotFoundError: If the lockfile does not exist.
    """
    packages = json.loads(lockfile.read_text())["packages"]
    return packages["node_modules/playwright-core"]["version"]


def main() -> int:
    """
    Compares every Playwright image tag in ci.yml with its job's lockfile.

    Returns:
        0 if every tag matches, 1 if any mismatches or sits in an unmapped job.
    """
    problems: list[str] = []
    found = 0
    job = ""
    for number, line in enumerate(WORKFLOW.read_text().splitlines(), start=1):
        key = JOB_KEY.match(line)
        if key:
            job = key.group(1)
        tag = IMAGE_TAG.search(line)
        if not tag or line.lstrip().startswith("#"):
            continue
        found += 1
        lockfile = JOB_LOCKFILES.get(job)
        if lockfile is None:
            problems.append(
                f"ci.yml:{number}: Playwright image in job '{job}' has no lockfile mapped "
                f"in scripts/check-playwright-image-sync.py (JOB_LOCKFILES)."
            )
            continue
        locked = locked_version(lockfile)
        if tag.group(1) != locked:
            problems.append(
                f"ci.yml:{number}: job '{job}' uses Playwright image v{tag.group(1)}, but "
                f"{lockfile.relative_to(ROOT)} resolves playwright-core {locked}. "
                f"Change the image tag to v{locked}-noble (or re-sync the lockfile)."
            )
    if found == 0:
        problems.append("No Playwright image tags found in ci.yml; update this check if the CI layout changed.")
    for problem in problems:
        print(problem, file=sys.stderr)
    if not problems:
        print(f"Playwright image tags match their lockfiles ({found} checked).")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
