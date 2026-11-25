#!/usr/bin/env python3
"""
Module: check_playwright_shards

Fails when the sharded end-to-end run would skip a test or run one twice.

Why: `ci.yml` splits the parallel Playwright project over N jobs with `--shard=i/N` and runs the serial
`global-state-mutators` project once (in shard 1). A change to the shard count, the project names or the config could
leave a test in no shard (it would never run) or in two (it would run twice, possibly against changed deployment
settings). The check lists the tests Playwright would run and compares the union of the shards with the whole suite.

Responsibilities:
- List the `default` project's tests unsharded and for each of the N shards (`playwright test --list`).
- Exit non-zero when a test is in no shard, in more than one, or when the shard count in `ci.yml` differs from the one
  checked.

Used by: the first E2E shard in `.github/workflows/ci.yml`, and by hand (`python scripts/check_playwright_shards.py`
from the repository root, after `npm ci` in `tests/playwright/`). Standard library, Node and `npx` only.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLAYWRIGHT_DIR = ROOT / "tests" / "playwright"
CI_FILE = ROOT / ".github" / "workflows" / "ci.yml"


def listed_tests(shard: tuple[int, int] | None) -> list[tuple[str, str]]:
    """Lists the tests the parallel project would run.

    Args:
        shard: `(index, count)` for `--shard=index/count`, or None for the whole project.

    Returns:
        (file, title) for every test, in listing order; a repeated pair means a test is listed twice.
    """
    command = ["npx", "playwright", "test", "--list", "--reporter=json", "--project=default", "--no-deps"]
    if shard is not None:
        command.append(f"--shard={shard[0]}/{shard[1]}")
    out = subprocess.run(command, cwd=PLAYWRIGHT_DIR, check=True, capture_output=True, text=True).stdout
    found: list[tuple[str, str]] = []

    def walk(suite: dict) -> None:
        for spec in suite.get("specs", []):
            found.extend((suite.get("file", ""), f"{spec['title']}#{index}") for index, _ in enumerate(spec["tests"]))
        for child in suite.get("suites", []):
            walk(child)

    for suite in json.loads(out)["suites"]:
        walk(suite)
    return found


def ci_shard_count() -> int | None:
    """Returns the shard count `ci.yml` passes to `--shard`, or None when it names none."""
    match = re.search(r"--shard=\$\{\{ matrix\.shard \}\}/(\d+)", CI_FILE.read_text(encoding="utf-8"))
    return int(match.group(1)) if match else None


def main(argv: list[str] | None = None) -> int:
    """Checks that the shards partition the suite.

    Args:
        argv: Command-line arguments; `--shards N` overrides the count read from `ci.yml`.

    Returns:
        0 when every test is in exactly one shard, 1 otherwise.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shards", type=int, default=None)
    args = parser.parse_args(argv)
    count = args.shards or ci_shard_count()
    if not count:
        print("ci.yml runs no sharded Playwright step", file=sys.stderr)
        return 1
    whole = listed_tests(None)
    shards = [listed_tests((index, count)) for index in range(1, count + 1)]
    problems: list[str] = []
    combined = [test for shard in shards for test in shard]
    for test in sorted(set(whole) - set(combined)):
        problems.append(f"in no shard: {test[0]} :: {test[1]}")
    for test in sorted({t for t in combined if combined.count(t) > 1}):
        problems.append(f"in more than one shard: {test[0]} :: {test[1]}")
    for test in sorted(set(combined) - set(whole)):
        problems.append(f"in a shard but not in the suite: {test[0]} :: {test[1]}")
    if args.shards is None and ci_shard_count() != count:
        problems.append(f"ci.yml shard count {ci_shard_count()} != checked {count}")
    for problem in problems:
        print(problem)
    if problems:
        return 1
    print(f"{len(whole)} tests: each is in exactly one of {count} shards ({', '.join(str(len(s)) for s in shards)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
