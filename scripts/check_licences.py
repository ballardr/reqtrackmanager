#!/usr/bin/env python3
"""
Module: check_licences

Fails when a shipped third-party component carries a licence the policy does not allow.

Why: the product may be offered under terms other than the open-source licence it is published under today, which
is only possible while no shipped application dependency is licensed under GPL, AGPL or another licence that would
reach the product itself. A dependency that changes licence, or a new one, must be noticed when it is added.

Responsibilities:
- Offline (default): judge the committed inventory against scripts/licence_policy.json, confirm it matches the
  lockfiles and requirements files, and confirm every operating-system package and base image a Dockerfile uses is
  named in the policy.
- `--live`: also install each Python requirements file freshly and judge the licences of everything that resolves
  now, so a transitive dependency that changed licence fails before an image is built. Needs network access.

Used by: the `licences` CI job, .githooks/pre-commit and backend/tests/test_licence_guard.py. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import licence_inventory as inv  # noqa: E402


def live_problems(policy: dict, inventory: dict) -> list[str]:
    """Resolves every Python requirements file now and returns one message per disallowed licence.

    Packages that resolve now but are absent from the committed inventory are reported as problems only when their
    licence is disallowed; a merely new package is printed as a reminder to regenerate.
    """
    problems = []
    known = {(p["name"], p["version"]) for p in inventory["packages"] if p["ecosystem"] == "python"}
    for component in inv.PYTHON_COMPONENTS:
        for package in inv.collect_python(component, policy):
            verdict = inv.judge_licence(policy, package.key, package.licence)
            if verdict not in ("ok", "notice"):
                problems.append(f"{component}: {package.key}@{package.version}: {verdict} (licence '{package.licence}')")
            elif (package.name, package.version) not in known:
                print(f"note: {component}: {package.key}@{package.version} is new since the inventory was generated (licence {package.licence})")
    return problems


def main(argv: list[str] | None = None) -> int:
    """Entry point; returns 0 when every check passes and 1 otherwise."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--live", action="store_true", help="also resolve the Python requirements now (network)")
    args = parser.parse_args(argv)
    policy = inv.load_policy()
    if not inv.NOTICES_PATH.is_file():
        print(f"{inv.NOTICES_PATH} is missing; run scripts/generate_third_party_notices.py")
        return 1
    inventory = json.loads(inv.NOTICES_PATH.read_text(encoding="utf-8"))
    problems = inv.check_policy(policy, inventory) + inv.check_inventory_current(policy, inventory)
    if args.live:
        problems += live_problems(policy, inventory)
    for problem in problems:
        print(f"licence check: {problem}")
    if problems:
        print(
            "Fix the dependency (replace it, or move to a permissively licensed alternative). Only a reviewed exception goes into "
            "scripts/licence_policy.json, with its evidence; then run scripts/generate_third_party_notices.py."
        )
        return 1
    print(f"licence check: {len(inventory['packages'])} packages and {len(policy['system_components'])} system components pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
