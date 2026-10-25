#!/usr/bin/env python3
"""
Module: perf.scrub_check

Command line for the results anonymisation check (`perf/lib/scrub.py`).

Usage:
    python3 perf/scrub_check.py [PATH ...]      (default: perf/results/)

Exits 0 when clean, 1 with one line per finding (file, line, rule; never the matched text), 2 for a missing path.
Also run by the runner before it writes an archive, by `backend/tests/test_perf_results.py` over the committed
results, and by `.githooks/pre-commit` when `perf/results/` is staged.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from perf.lib import scrub  # noqa: E402

DEFAULT = Path(__file__).resolve().parent / "results"


def main(argv: list) -> int:
    """Scans each path and prints findings; returns the process exit status."""
    roots = [Path(arg) for arg in argv] or [DEFAULT]
    problems = 0
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
