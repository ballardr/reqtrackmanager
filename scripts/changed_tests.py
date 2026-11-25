#!/usr/bin/env python3
"""
Module: changed_tests

Lists the test files a pull request adds or changes, so CI can run just those several times and fail a test that
passes once and fails on another run.

Why: the suites run once per pull request, so a test that fails one run in a few passes on the pull request and fails
on `main` after the merge (a story measured a box before the view finished moving; a test depended on the order of an
unordered query). A test added or changed by the pull request is the likeliest to be flaky, so it is the one repeated.

Responsibilities:
- Diff the working tree's HEAD against the merge base with a base ref (`git diff --name-only --diff-filter=AMR`).
- `frontend`: the changed Storybook story files, plus the story beside each changed component or hook, as paths
  relative to `frontend/`.
- `backend`: the changed `test_*.py` files under `backend/`, as paths relative to `backend/`.
- Print one path per line, at most `--max-files` of them (the rest are named on stderr), and exit 0 even when none.

Used by: the `frontend` and `backend-tests` jobs in `.github/workflows/ci.yml` (pull requests only);
`backend/tests/test_changed_tests.py`. Standard library only; needs `git` and a checkout deep enough to hold the base.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FRONTEND_SOURCE_SUFFIXES = (".tsx", ".ts")


def changed_files(base: str, repo: Path = REPO) -> list[str]:
    """Reads the files a branch adds, modifies or renames against the merge base with `base`.

    Args:
        base: A git ref (for example `origin/main`).
        repo: The repository root.

    Returns:
        Repository-relative paths, sorted.

    Raises:
        subprocess.CalledProcessError: When git cannot diff against `base`.
    """
    out = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=AMR", f"{base}...HEAD"],
        cwd=repo, check=True, capture_output=True, text=True,
    ).stdout
    return sorted(line for line in out.splitlines() if line)


def frontend_stories(changed: list[str], repo: Path = REPO) -> list[str]:
    """Picks the story files to repeat: changed ones and the story beside each changed source file.

    Args:
        changed: Repository-relative changed paths.
        repo: The repository root, used to see whether a sibling story exists.

    Returns:
        Paths relative to `frontend/`, sorted and without duplicates.
    """
    picked: set[str] = set()
    for path in changed:
        if not path.startswith("frontend/src/") or not path.endswith(FRONTEND_SOURCE_SUFFIXES):
            continue
        if path.endswith(".stories.tsx"):
            candidate = path
        else:
            stem = path.rsplit(".", 1)[0]
            candidate = f"{stem}.stories.tsx"
        if (repo / candidate).is_file():
            picked.add(candidate.removeprefix("frontend/"))
    return sorted(picked)


def backend_tests(changed: list[str], repo: Path = REPO) -> list[str]:
    """Picks the backend test files to repeat: changed `test_*.py` files that still exist.

    Args:
        changed: Repository-relative changed paths.
        repo: The repository root.

    Returns:
        Paths relative to `backend/`, sorted.
    """
    return sorted(
        path.removeprefix("backend/")
        for path in changed
        if path.startswith("backend/") and path.rsplit("/", 1)[-1].startswith("test_") and path.endswith(".py")
        and (repo / path).is_file()
    )


def main(argv: list[str] | None = None) -> int:
    """Prints the changed test files of one suite.

    Args:
        argv: Command-line arguments (defaults to `sys.argv[1:]`).

    Returns:
        0 on success, 2 when git cannot diff against the base.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("suite", choices=("frontend", "backend"))
    parser.add_argument("--base", required=True, help="git ref to compare with, for example origin/main")
    parser.add_argument("--max-files", type=int, default=40, help="most files to print (the rest are named on stderr)")
    args = parser.parse_args(argv)
    try:
        changed = changed_files(args.base)
    except subprocess.CalledProcessError as error:
        print(f"cannot diff against {args.base}: {error.stderr.strip()}", file=sys.stderr)
        return 2
    files = frontend_stories(changed) if args.suite == "frontend" else backend_tests(changed)
    for path in files[: args.max_files]:
        print(path)
    if len(files) > args.max_files:
        print(f"::warning::{len(files) - args.max_files} changed {args.suite} test files were not repeated "
              f"(limit {args.max_files}): {', '.join(files[args.max_files:])}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
