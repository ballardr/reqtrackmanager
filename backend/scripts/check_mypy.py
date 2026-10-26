#!/usr/bin/env python3
"""
Module: check_mypy

Runs mypy (configuration in `pyproject.toml`) and fails on any type error not already recorded in
`mypy_baseline.json`, so the backend's type debt can shrink but not grow.

Design notes:
- A ratchet, like `scripts/check_field_help.py`: the baseline counts findings per
  `(file, error code, message)`. Line numbers are left out so unrelated edits above a finding do not
  invalidate it. A count may fall; it may not rise, and a finding absent from the baseline allows none.
- A finding that is fixed but still listed also fails the check, with the instruction to run
  `--update`, so a freed allowance cannot be spent on a new error elsewhere.
- Findings are never silenced by this script: fix the code. `--update` only ever records the current
  state, and a reviewer sees the baseline diff.
- `--list` prints every current finding grouped by file, for working the baseline down.

Usage (from `backend/`): `python scripts/check_mypy.py [--update | --list]`.
"""

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
BASELINE = BACKEND / "mypy_baseline.json"


def run_mypy() -> list[dict]:
    """Runs mypy and returns its findings (errors only; notes are context for an error).

    Returns:
        One dict per error with `file`, `line`, `code` and `message`.

    Raises:
        SystemExit: mypy crashed or produced no parsable output (a configuration problem, not a finding).
    """
    proc = subprocess.run(
        [sys.executable, "-m", "mypy", "--output", "json", "--no-error-summary"],
        cwd=BACKEND, capture_output=True, text=True, check=False,
    )
    findings = []
    for line in proc.stdout.splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            sys.exit(f"mypy produced output this script cannot read:\n{proc.stdout}\n{proc.stderr}")
        if item.get("severity") == "error":
            findings.append({"file": item["file"], "line": item["line"], "code": item.get("code") or "", "message": item["message"]})
    if proc.returncode not in (0, 1):
        sys.exit(f"mypy failed (exit {proc.returncode}):\n{proc.stdout}\n{proc.stderr}")
    return findings


def keyed(findings: list[dict]) -> Counter:
    """Counts findings per `file|code|message`."""
    return Counter(f"{f['file']}|{f['code']}|{f['message']}" for f in findings)


def main() -> int:
    """Entry point; returns the process exit code."""
    findings = run_mypy()
    current = keyed(findings)
    if "--list" in sys.argv:
        for f in sorted(findings, key=lambda f: (f["file"], f["line"])):
            print(f"{f['file']}:{f['line']}: {f['message']}  [{f['code']}]")
        print(f"\n{len(findings)} findings in {len({f['file'] for f in findings})} files")
        return 0
    if "--update" in sys.argv:
        BASELINE.write_text(json.dumps(dict(sorted(current.items())), indent=1) + "\n")
        print(f"Baseline written: {sum(current.values())} findings.")
        return 0

    baseline = Counter(json.loads(BASELINE.read_text())) if BASELINE.exists() else Counter()
    new = current - baseline
    fixed = baseline - current
    if new:
        print("New type errors (fix them; do not add them to the baseline):")
        by_key = {}
        for f in findings:
            by_key.setdefault(f"{f['file']}|{f['code']}|{f['message']}", []).append(f["line"])
        for key in sorted(new):
            file, code, message = key.split("|", 2)
            lines = ", ".join(str(n) for n in by_key[key])
            print(f"  {file} (lines {lines}): {message}  [{code}]" + (f"  ({new[key]} more than the baseline)" if baseline[key] else ""))
    if fixed:
        print(f"\n{sum(fixed.values())} baselined finding(s) are fixed. Run `python scripts/check_mypy.py --update` and commit the smaller baseline.")
    if not new and not fixed:
        print(f"mypy: no new type errors ({sum(current.values())} baselined).")
    return 1 if new or fixed else 0


if __name__ == "__main__":
    sys.exit(main())
