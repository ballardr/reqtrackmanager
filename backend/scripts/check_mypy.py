#!/usr/bin/env python3
"""
Module: check_mypy

Runs mypy (configuration in `pyproject.toml`) over the application package and fails on any finding.

Responsibilities:
- Run mypy with JSON output and print each error as `file:line: message  [code]`.
- Exit non-zero when there is any error, so CI and local runs stop at the first regression.

Design decisions:
- No baseline and no allowance: any finding fails the check. Fix the code
  (narrow the type, correct the annotation); do not add a `# type: ignore` or loosen `pyproject.toml`.
- A mypy crash or unreadable output is a configuration problem, reported as such and not as a finding.

Usage (from `backend/`): `python scripts/check_mypy.py`.
"""

import json
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


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


def main() -> int:
    """Entry point; returns the process exit code (0 when mypy reports nothing)."""
    findings = run_mypy()
    for f in sorted(findings, key=lambda f: (f["file"], f["line"])):
        print(f"{f['file']}:{f['line']}: {f['message']}  [{f['code']}]")
    if findings:
        print(f"\nmypy: {len(findings)} finding(s) in {len({f['file'] for f in findings})} file(s). Fix them in the code.")
        return 1
    print("mypy: no findings.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
