"""Pins `scripts/check_governed_records.py`: every registered record type has a lifecycle or a stated reason, a stale or
unknown reason is a finding, and the staged mode checks only the modules a commit touches."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_governed_records.py"


@pytest.fixture(scope="module")
def checker():
    spec = importlib.util.spec_from_file_location("check_governed_records", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_every_registered_record_type_has_a_lifecycle_or_a_reason(checker):
    assert checker.findings() == []


def test_a_type_with_neither_is_a_finding(checker, monkeypatch):
    from app.modules import registry

    real = registry.get_no_lifecycle_types
    monkeypatch.setattr(registry, "get_no_lifecycle_types", lambda: {k: v for k, v in real().items() if k != "engagement"})
    found = checker.findings()
    assert len(found) == 1 and "'engagement' has no lifecycle and no reason" in found[0]


def test_a_reason_for_a_type_that_has_a_lifecycle_is_a_finding(checker, monkeypatch):
    from app.modules import registry

    real = registry.get_no_lifecycle_types
    monkeypatch.setattr(registry, "get_no_lifecycle_types", lambda: {**real(), "persona": "not needed"})
    assert any("'persona' has a lifecycle, so its no_lifecycle reason is stale" in line for line in checker.findings())


def test_the_staged_mode_checks_only_the_modules_a_commit_touches(checker, monkeypatch):
    from app.modules import registry

    real = registry.get_no_lifecycle_types
    monkeypatch.setattr(
        registry, "get_no_lifecycle_types",
        lambda: {k: v for k, v in real().items() if k not in {"engagement", "architecture_state"}},
    )
    assert checker.findings([]) == []
    assert checker.findings(["frontend/src/App.tsx"]) == []
    only_stakeholders = checker.findings(["backend/app/modules/stakeholders/service.py"])
    assert len(only_stakeholders) == 1 and "engagement" in only_stakeholders[0]
    both = checker.findings(["backend/app/modules/stakeholders/service.py", "backend/app/modules/architecture/records.py"])
    assert len(both) == 2
    assert len(checker.findings(["backend/app/modules/registry.py"])) == 2  # the registry is shared, so every type is checked
