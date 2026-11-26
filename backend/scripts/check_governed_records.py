#!/usr/bin/env python3
"""
Module: check_governed_records

Fails when a registered record type has neither a lifecycle nor a stated reason for having none (CLAUDE.md "Governed
Records Use the Governance Engine").

Responsibilities:
- Compare every registered artefact type (core and each module's) with `registry.get_lifecycles()` and
  `registry.get_no_lifecycle_types()`: a type with neither, a reason given for a type that has a lifecycle, and a reason
  for a type that is not registered are each a finding.
- `--staged` restricts the check to what a commit touches, for the pre-commit hook: only the modules that own a staged file
  under `backend/app/modules/<package>/`. A staged core registration file, the module registry or the checker itself checks
  every type, as does a run without `--staged` (CI and `backend/tests/test_governed_records.py`).

Design decisions:
- The check reads the live registry rather than parsing source, so a type registered any way is seen. It therefore needs the
  backend dependencies; the staged run in a checkout without them skips with a note and exits 0, because CI runs the full
  check and fails there.
- A package is matched to its module through the package of its `models_import_path`, so a module whose key differs from its
  directory is still found.

Usage (from the repository root): python backend/scripts/check_governed_records.py [--staged]
Dependencies: the backend application package; `git` for `--staged`.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
CORE_TRIGGERS = (
    "backend/app/services/lifecycles_core.py",
    "backend/app/modules/registry.py",
    "backend/scripts/check_governed_records.py",
)


def staged_files() -> list[str]:
    """The paths staged for the next commit, relative to the repository root.

    Returns:
        The staged paths, empty when `git` is unavailable.
    """
    try:
        out = subprocess.run(
            ["git", "diff", "--cached", "--name-only"], cwd=ROOT, check=True, capture_output=True, text=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return []
    return [line for line in out.splitlines() if line]


def findings(staged: list[str] | None = None) -> list[str]:
    """The findings of the check.

    Args:
        staged: The staged paths to restrict the check to, or `None` to check every registered type.

    Returns:
        One message per finding, empty when the registry is consistent.
    """
    sys.path.insert(0, str(BACKEND))
    from app.modules.registry import get_lifecycles, get_module_registry, get_no_lifecycle_types
    from app.services.lifecycles_core import CORE_NO_LIFECYCLE

    lifecycles = get_lifecycles()
    reasons = get_no_lifecycle_types()
    registry = get_module_registry()
    core_types = {"requirement", "requirement_action", "change_request"}

    packages: set[str] | None
    if staged is None or any(path in CORE_TRIGGERS for path in staged):
        packages, check_core = None, True
    else:
        packages = {
            parts[3] for path in staged if (parts := path.split("/")) and len(parts) > 3 and parts[:3] == ["backend", "app", "modules"]
        }
        check_core = False

    problems: list[str] = []
    scopes: list[tuple[str, set[str], dict[str, str]]] = []
    if check_core:
        scopes.append(("core", core_types, dict(CORE_NO_LIFECYCLE)))
    for key, definition in registry.items():
        package = definition.models_import_path.split(".")[2] if definition.models_import_path.count(".") >= 2 else key
        if packages is not None and package not in packages and key not in packages:
            continue
        scopes.append((key, set(definition.artefact_types), dict(definition.no_lifecycle)))

    for owner, types, own_reasons in scopes:
        for artefact_type in sorted(types):
            has = artefact_type in lifecycles
            if not has and artefact_type not in reasons:
                problems.append(
                    f"{owner}: the record type {artefact_type!r} has no lifecycle and no reason; register a LifecycleDefinition "
                    "in ModuleDefinition.lifecycles or give a reason in ModuleDefinition.no_lifecycle."
                )
            if has and artefact_type in reasons:
                problems.append(f"{owner}: {artefact_type!r} has a lifecycle, so its no_lifecycle reason is stale; remove it.")
        for artefact_type in sorted(own_reasons):
            if artefact_type not in types:
                problems.append(f"{owner}: no_lifecycle names {artefact_type!r}, which is not one of its registered types.")
    return problems


def main(argv: list[str]) -> int:
    """Runs the check and prints each finding; returns the exit code (1 on any finding)."""
    staged_mode = "--staged" in argv
    try:
        found = findings(staged_files() if staged_mode else None)
    except ImportError as exc:
        if staged_mode:
            print(f"check_governed_records: skipped, the backend dependencies are not installed here ({exc}); CI runs the full check.")
            return 0
        raise
    for line in found:
        print(line)
    if found:
        print(f"\n{len(found)} governed-record finding(s). See CLAUDE.md, 'Governed Records Use the Governance Engine'.")
        return 1
    print("Every registered record type has a lifecycle or a stated reason.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
