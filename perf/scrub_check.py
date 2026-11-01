#!/usr/bin/env python3
"""
Module: perf.scrub_check

Command line for the results anonymisation check (`perf/lib/scrub.py`).

Usage:
    python3 perf/scrub_check.py [PATH ...]      (default: perf/results/, every file in it)
    python3 perf/scrub_check.py --tracked [DIR] (only the files git tracks or has staged under perf/results/, or under DIR
                                                 when given: a results directory inside a git repository two levels down)

Exits 0 when clean, 1 with one line per finding (file, line, rule; never the matched text), 2 for a missing path
or when git cannot list the files.
Also run by the runner before it writes an archive (whole bundle), by `backend/tests/test_perf_runner.py` over the
committed results, and by `.githooks/pre-commit` with `--tracked` when `perf/results/` is staged.

Why `--tracked`: `perf/results/` is git-ignored, so on a machine that has run the profile it also holds local bundles
(each already checked by the runner) and whatever a person copied in (an archive, a `.DS_Store`). None of that is
committed, and a hook that scanned it would block an unrelated commit; only what a commit would publish needs the check.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from perf.lib import scrub  # noqa: E402

DEFAULT = Path(__file__).resolve().parent / "results"


def tracked_files(root: Path) -> list:
    """Paths under `root` that git tracks or has staged (relative to `root`).

    Raises:
        OSError: If git is not available or `root` is not in a repository.
        subprocess.CalledProcessError: If git cannot list the files.
    """
    done = subprocess.run(["git", "ls-files", "-z", "--", str(root)], cwd=root.parent.parent, capture_output=True, text=True, check=True, timeout=30)
    return [Path(p).relative_to(root.relative_to(root.parent.parent)) for p in done.stdout.split("\0") if p]


def main(argv: list) -> int:
    """Scans each path (or, with `--tracked`, the tracked files of `perf/results/` or of the one directory named) and prints findings; returns the exit status."""
    problems = 0
    if "--tracked" in argv:
        named = [arg for arg in argv if arg != "--tracked"]
        results = Path(named[0]).resolve() if named else DEFAULT
        try:
            files = tracked_files(results)
        except (OSError, subprocess.SubprocessError) as error:
            print(f"error: git cannot list the tracked result files ({type(error).__name__})", file=sys.stderr)
            return 2
        for finding in scrub.scan_files(results, files):
            print(finding)
            problems += 1
        if problems:
            print(f"{problems} finding(s): results must contain only measurements and generic host characteristics", file=sys.stderr)
            return 1
        return 0
    roots = [Path(arg) for arg in argv] or [DEFAULT]
    for root in roots:
        if not root.is_dir():
            print(f"error: {root} is not a directory", file=sys.stderr)
            return 2
        for finding in scrub.scan_tree(root):
            print(finding)
            problems += 1
    if problems:
        print(f"{problems} finding(s): results must contain only measurements and generic host characteristics", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
