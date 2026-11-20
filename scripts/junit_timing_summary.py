#!/usr/bin/env python3
"""
Module: junit_timing_summary

Writes a suite's duration and its slowest tests, from a JUnit report, as Markdown for a CI job summary, and warns when
the suite is slower than its budget.

Why: a suite that gets slower a little each week is noticed only when a job's ceiling is hit. Printing the total, the
slowest tests and the budget on every run makes a regression visible on the run that causes it.

Responsibilities:
- Sum the `time` of every test case in one or more JUnit files (tests run in parallel, so this is test-seconds, and the
  elapsed time is the report's largest `timestamp`-to-end span when present, otherwise the longest suite `time`).
- Print a Markdown table of the slowest cases and, with `--budget-minutes`, a GitHub `::warning::` when the elapsed
  time exceeds it (the budget is a target, never a failure: a slow run must still report its tests).

Used by: the backend, E2E shard and frontend jobs in `.github/workflows/ci.yml`; `backend/tests/test_junit_timing_summary.py`.
Standard library only.
"""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def read_cases(paths: list[Path]) -> tuple[list[tuple[float, str]], float]:
    """Reads the test cases of JUnit files.

    Args:
        paths: JUnit XML files (pytest, Playwright or Vitest).

    Returns:
        (cases, elapsed): each case as (seconds, "class :: name"), and the largest single-suite `time` among the files, a
        lower bound of the elapsed time of a run whose suites ran in parallel.
    """
    cases: list[tuple[float, str]] = []
    elapsed = 0.0
    for path in paths:
        root = ET.parse(path).getroot()
        suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
        for suite in suites:
            elapsed = max(elapsed, float(suite.get("time", 0) or 0))
        for case in root.iter("testcase"):
            name = f"{case.get('classname', '')} :: {case.get('name', '')}".strip(" :")
            cases.append((float(case.get("time", 0) or 0), name))
    return cases, elapsed


def summary(title: str, cases: list[tuple[float, str]], elapsed: float, budget_minutes: float | None, top: int = 10) -> str:
    """Builds the Markdown summary.

    Args:
        title: Heading, for example "Backend tests".
        cases: (seconds, name) per test, from `read_cases`.
        elapsed: The run's elapsed seconds (0 when the report does not say).
        budget_minutes: The suite's target in minutes, or None.
        top: How many slowest cases to list.

    Returns:
        Markdown text (no trailing newline guarantee).
    """
    total = sum(seconds for seconds, _ in cases)
    counts = f"{len(cases)} tests, {total / 60:.1f} test-minutes"
    if elapsed:
        counts += f", {elapsed / 60:.1f} minutes elapsed"
    lines = [f"## {title}: timing", "", counts]
    if budget_minutes is not None and elapsed:
        verdict = "within" if elapsed / 60 <= budget_minutes else "over"
        lines.append(f"Target {budget_minutes:g} minutes: **{verdict}**.")
    lines += ["", "| Seconds | Slowest tests |", "|---:|---|"]
    lines += [f"| {seconds:.1f} | {name[:140].replace('|', '/')} |" for seconds, name in sorted(cases, reverse=True)[:top]]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Prints the summary; exits 0 whatever the timing (a slow run is reported, not failed).

    Args:
        argv: Command-line arguments (default `sys.argv[1:]`).

    Returns:
        0, or 2 when no JUnit file could be read.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", nargs="+", type=Path)
    parser.add_argument("--title", required=True)
    parser.add_argument("--budget-minutes", type=float, default=None)
    args = parser.parse_args(argv)
    readable = [p for p in args.reports if p.is_file()]
    if not readable:
        print(f"no JUnit report found among {[str(p) for p in args.reports]}", file=sys.stderr)
        return 2
    cases, elapsed = read_cases(readable)
    print(summary(args.title, cases, elapsed, args.budget_minutes))
    if args.budget_minutes is not None and elapsed and elapsed / 60 > args.budget_minutes:
        print(f"::warning::{args.title} took {elapsed / 60:.1f} minutes, over its {args.budget_minutes:g}-minute target", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
