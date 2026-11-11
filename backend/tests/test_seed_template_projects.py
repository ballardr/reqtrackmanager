"""Tests that the example template projects seed through the real API, differ in shape and arrive as drafts.

The seed script talks HTTP with `httpx`; the test routes those calls to the test client, so the whole seed runs
against the application and its database, and a second run proves it is idempotent.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.conftest import auth_headers, create_org_admin_in

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import seed_demo_data  # noqa: E402
import seed_template_projects  # noqa: E402

TEMPLATE_NAMES = {spec.name for spec in seed_template_projects.SPECS}


@pytest.fixture
def routed(client, monkeypatch):
    """Routes the seed scripts' `httpx` calls to the test client."""
    origin = "http://localhost:8000"

    def route(method: str):
        def call(url: str, **kwargs):
            kwargs.pop("timeout", None)  # the test client has no network to time out on, and warns when given one
            return getattr(client, method)(url.removeprefix(origin), **kwargs)

        return call

    shim = SimpleNamespace(**{method: route(method) for method in ("get", "post", "put", "patch", "delete")})
    shim.HTTPStatusError = Exception
    monkeypatch.setattr(seed_demo_data, "httpx", shim)
    monkeypatch.setattr(seed_template_projects, "httpx", shim)
    return client


@pytest.fixture
def seeded(routed, admin_token):
    org, token = create_org_admin_in(routed, admin_token, "Template Seed Org")
    headers = auth_headers(token)
    owner_id = routed.get("/api/v1/auth/me", headers=headers).json()["id"]
    first = seed_template_projects.seed_template_projects(headers, org, owner_id=owner_id)
    return routed, headers, org, owner_id, first


def _project(client, headers, org_id, name) -> dict:
    found = client.get("/api/v1/projects", params={"organization_id": org_id, "search": name, "include_templates": True}, headers=headers).json()
    return next(p for p in found if p["name"] == name)


def test_every_template_spec_is_consistent():
    names = [spec.name for spec in seed_template_projects.SPECS]
    assert len(names) == len(set(names)) == 4
    for spec in seed_template_projects.SPECS:
        assert spec.name.endswith(" template")
        workflow_kinds = {kind for _, kind in spec.workflow[1]}
        assert {"open", "closed"} <= workflow_kinds
        assert len({phase for phase, _ in spec.workflow[1]}) == len(spec.workflow[1])
        for _, _, prefix, category_key in spec.requirements:
            assert category_key in spec.components[prefix][1]
            assert category_key in seed_demo_data.CATEGORY_DEFS
        assert len({widget["id"] for widget in spec.widgets}) == len(spec.widgets)


def test_the_four_workflows_and_vocabularies_differ():
    specs = seed_template_projects.SPECS
    assert len({tuple(spec.workflow[1]) for spec in specs}) == 4
    assert len({tuple(spec.action_types) for spec in specs}) == 4
    assert len({tuple(spec.pain_point_types) for spec in specs}) == 4


def test_seeding_creates_four_templates_and_a_second_run_changes_nothing(seeded):
    client, headers, org, owner_id, first = seeded
    assert first == {name: True for name in TEMPLATE_NAMES}
    before = {
        p["name"]: p["id"]
        for p in client.get("/api/v1/projects", params={"organization_id": org["id"], "include_templates": True}, headers=headers).json()
    }
    again = seed_template_projects.seed_template_projects(headers, org, owner_id=owner_id)
    assert again == {name: False for name in TEMPLATE_NAMES}
    after = {
        p["name"]: p["id"]
        for p in client.get("/api/v1/projects", params={"organization_id": org["id"], "include_templates": True}, headers=headers).json()
    }
    assert after == before
    assert TEMPLATE_NAMES <= set(after)


def test_each_template_has_its_own_shape(seeded):
    client, headers, org, _owner_id, _ = seeded
    for spec in seed_template_projects.SPECS:
        project = _project(client, headers, org["id"], spec.name)
        assert project["is_template"] is True
        pid = project["id"]
        workflows = client.get(f"/api/v1/projects/{pid}/stage-workflows", headers=headers).json()
        mine = next(w for w in workflows if w["name"] == spec.workflow[0])
        assert [(p["name"], p["kind"]) for p in mine["phases"]] == spec.workflow[1]
        stages = client.get(f"/api/v1/projects/{pid}/stages", headers=headers).json()
        assert set(spec.stages) <= {s["name"] for s in stages}
        action_types = {t["name"] for t in client.get(f"/api/v1/projects/{pid}/action-types", headers=headers).json()}
        assert set(spec.action_types) <= action_types
        requirements = client.get(f"/api/v1/projects/{pid}/requirements", headers=headers).json()
        assert len(requirements) == len(spec.requirements)
        assert {r["status"] for r in requirements} == {"draft"}
        components = client.get(f"/api/v1/projects/{pid}/components", headers=headers).json()
        assert {c["prefix"] for c in components} == set(spec.components)
        layout = client.get(f"/api/v1/projects/{pid}/overview-layout", headers=headers).json()
        assert [w["id"] for w in layout["widgets"]] == [w["id"] for w in spec.widgets]


def test_modules_are_switched_per_template(seeded):
    client, headers, org, _owner_id, _ = seeded
    for spec in seed_template_projects.SPECS:
        pid = _project(client, headers, org["id"], spec.name)["id"]
        modules = {m["module_key"]: m for m in client.get(f"/api/v1/projects/{pid}/modules", headers=headers).json()}
        for key in spec.modules_off:
            # A module the organisation has not enabled is omitted from the list, which is also "off".
            assert not modules.get(key, {}).get("effective_enabled", False), (spec.name, key)


def test_a_project_created_from_each_template_receives_its_shape(seeded):
    client, headers, org, _owner_id, _ = seeded
    for spec in seed_template_projects.SPECS:
        template = _project(client, headers, org["id"], spec.name)
        resp = client.post(
            "/api/v1/projects",
            json={"organization_id": org["id"], "name": f"From {spec.name}", "summary": "", "template_project_id": template["id"]},
            headers=headers,
        )
        assert resp.status_code == 201, resp.text
        pid = resp.json()["id"]
        workflows = {w["name"] for w in client.get(f"/api/v1/projects/{pid}/stage-workflows", headers=headers).json()}
        assert spec.workflow[0] in workflows
        requirements = client.get(f"/api/v1/projects/{pid}/requirements", headers=headers).json()
        assert {r["name"] for r in requirements} == {r[0] for r in spec.requirements}
        assert {r["status"] for r in requirements} == {"draft"}
        layout = client.get(f"/api/v1/projects/{pid}/overview-layout", headers=headers).json()
        assert [w["id"] for w in layout["widgets"]] == [w["id"] for w in spec.widgets]


def test_starter_records_arrive_as_drafts(seeded):
    client, headers, org, _owner_id, _ = seeded
    hardware = _project(client, headers, org["id"], seed_template_projects.HARDWARE.name)["id"]
    decisions = client.get(f"/api/v1/projects/{hardware}/modules/decisions", headers=headers).json()
    assert [d["status"] for d in decisions] == ["draft"]
    risks = client.get(f"/api/v1/projects/{hardware}/modules/risk_management/risks", headers=headers).json()
    assert [r["title"] for r in risks] == ["The humidity sensor has one supplier"]
    research = _project(client, headers, org["id"], seed_template_projects.RESEARCH.name)["id"]
    personas = client.get(f"/api/v1/projects/{research}/modules/stakeholders/personas", headers=headers).json()
    assert [p["status"] for p in personas] == ["draft"]
    engagements = client.get(f"/api/v1/projects/{research}/modules/stakeholders/engagements", headers=headers).json()
    assert len(engagements) == 1
    compliance = _project(client, headers, org["id"], seed_template_projects.COMPLIANCE.name)["id"]
    assigned = client.get(f"/api/v1/projects/{compliance}/modules/compliance/project-compliance", headers=headers).json()
    assert len(assigned) == 1
