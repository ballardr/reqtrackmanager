"""Tests for the governance health extension point in core (`modules.seams.HealthProvider`, `services.health_core`,
`modules.registry.get_health_providers`) and the baseline readiness read (`services.baseline.evaluate_checks`), which work
with no Governance module: the core types report, a registration is validated, and no check runs without a policy."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models.project import Project
from app.models.user import User
from app.modules.registry import ModuleDefinition, ModuleSubComponentDefinition, get_health_providers
from app.modules.seams import HealthMeasure, HealthProvider
from app.services import baseline
from app.services.health_core import CORE_HEALTH_PROVIDERS, measure_from_counts
from tests.conftest import create_org_admin_in, create_project


def _provider(key="things", sub_component=None) -> HealthProvider:
    return HealthProvider(
        key=key, label="Things", artefact_type="requirement", kind="completion", measure=lambda db, project_id: HealthMeasure(0, 0),
        sub_component=sub_component,
    )


def _definition(**extra) -> ModuleDefinition:
    return ModuleDefinition(
        key="health_probe", name="Probe", description="Probe", version="1", default_enabled=False, implemented=True,
        get_router=lambda: None, **extra,
    )


def test_the_core_types_report_first_with_an_empty_module_key():
    providers = get_health_providers()
    assert [(key, p.key) for key, p in providers[: len(CORE_HEALTH_PROVIDERS)]] == [
        ("", "requirement"), ("", "change_request"), ("", "project_stage"), ("", "component_stage"),
    ]
    assert {p.artefact_type for _, p in providers} >= {"requirement", "change_request", "project_stage"}


def test_a_measure_counts_only_the_statuses_it_is_given():
    counts = {"draft": 2, "approved": 3, "archived": 7}
    measure = measure_from_counts(counts, {"draft", "approved"}, {"approved"})
    assert (measure.total, measure.done, measure.outstanding) == (5, 3, 2)


def test_a_health_provider_must_name_a_declared_sub_component_and_a_unique_key():
    with pytest.raises(ValueError, match="undeclared sub-component"):
        _definition(health_providers=(_provider(sub_component="missing"),))
    with pytest.raises(ValueError, match="duplicate health provider key"):
        _definition(health_providers=(_provider(), _provider()))
    declared = _definition(
        sub_components=(ModuleSubComponentDefinition(key="part", name="Part"),),
        health_providers=(_provider(sub_component="part"),),
    )
    assert declared.health_providers[0].key == "things"


def test_no_check_runs_for_a_project_with_no_baseline_policy(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "Health Core Org")
    project = create_project(client, token, org["id"], "Core project")
    with SessionLocal() as db:
        row = db.get(Project, uuid.UUID(project["id"]))
        user = db.scalar(select(User).limit(1))
        assert row is not None and user is not None
        evaluation = baseline.evaluate_checks(db, row, user)
    assert evaluation.checks == [] and evaluation.records == {} and evaluation.failures == []
