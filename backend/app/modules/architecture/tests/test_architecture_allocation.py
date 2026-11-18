"""Tests for allocation: suggestions computed from an element's placement in the requirement's component, accepting
(one or many pairs, through the generic link path), dismissing and restoring, the dismissal clearing when the element
leaves the component, nested ownership and access, the audit trail and the coverage counts. Every test builds its own
organisation."""

from __future__ import annotations

import uuid

from app.modules.architecture.allocation import dismissal_applies
from app.modules.architecture.tests._helpers import add_member, make_element, project_base
from tests.conftest import auth_headers
from tests.link_world import World

ELEMENT = "architecture_element"


def _world(client, admin_token, name="Alloc"):
    world = World(client, admin_token, name)
    world.enable("architecture")
    return world


def _place(client, world, project, element, component_id, category_id=None, expect=200):
    resp = client.put(
        f"/api/v1/projects/{project['id']}/artefacts/{ELEMENT}/{element['id']}/placements",
        json={"placements": [{"component_id": component_id, "category_id": category_id}] if component_id else []},
        headers=auth_headers(world.token),
    )
    assert resp.status_code == expect, resp.text


def _view(client, world, project, *, requirement=None, element=None, token=None):
    kind, record = ("requirements", requirement) if requirement is not None else ("elements", element["id"])
    resp = client.get(f"{project_base(project['id'])}/{kind}/{record}/allocation", headers=auth_headers(token or world.token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _codes(rows, key="element"):
    return sorted(r[key]["unique_code"] for r in rows)


def _post(client, world, project, action, body, token=None, expect=200):
    resp = client.post(f"{project_base(project['id'])}/allocation/{action}", json=body, headers=auth_headers(token or world.token))
    assert resp.status_code == expect, resp.text
    return resp.json() if resp.content else None


def _setup(client, admin_token):
    world = _world(client, admin_token)
    project = world.project("Alloc project")
    requirement = world.requirement(project)
    element = make_element(client, world.token, project["id"], "Gateway")
    return world, project, requirement, element


def test_an_element_in_the_requirements_component_is_suggested_and_leaving_removes_it(client, admin_token):
    world, project, requirement, element = _setup(client, admin_token)
    assert _view(client, world, project, requirement=requirement)["suggested"] == []

    _place(client, world, project, element, project["component_id"])
    suggested = _view(client, world, project, requirement=requirement)["suggested"]
    assert _codes(suggested) == ["ELM-001"] and suggested[0]["requirement"]["id"] == str(requirement)
    from_element = _view(client, world, project, element=element)["suggested"]
    assert _codes(from_element, "requirement") == [suggested[0]["requirement"]["unique_code"]]

    _place(client, world, project, element, None)
    assert _view(client, world, project, requirement=requirement)["suggested"] == []


def test_a_retired_element_is_not_suggested(client, admin_token):
    world, project, requirement, element = _setup(client, admin_token)
    kept = make_element(client, world.token, project["id"], "Hub")
    for record in (element, kept):
        _place(client, world, project, record, project["component_id"])
    version = element["version"]
    for target in ("active", "retired"):
        resp = client.post(
            f"{project_base(project['id'])}/elements/{element['id']}/status", json={"status": target, "version": version},
            headers=auth_headers(world.token),
        )
        assert resp.status_code == 200, resp.text
        version = resp.json()["version"]
    assert _codes(_view(client, world, project, requirement=requirement)["suggested"]) == ["ELM-002"]


def test_accepting_creates_one_allocated_to_link_and_never_twice(client, admin_token):
    world, project, requirement, element = _setup(client, admin_token)
    _place(client, world, project, element, project["component_id"])
    body = {"pairs": [{"requirement_id": str(requirement), "element_id": element["id"]}]}

    assert _post(client, world, project, "accept", body) == {"accepted": 1, "failed": []}
    view = _view(client, world, project, requirement=requirement)
    assert _codes(view["allocated"]) == ["ELM-001"] and view["suggested"] == []
    assert view["allocated"][0]["link_id"]

    again = _post(client, world, project, "accept", body)
    assert again["accepted"] == 0 and again["failed"][0]["reason"]
    from app.database import SessionLocal
    from app.models.relationship import ArtefactLink

    db = SessionLocal()
    try:
        assert db.query(ArtefactLink).filter(ArtefactLink.source_id == requirement, ArtefactLink.target_id == uuid.UUID(element["id"])).count() == 1
    finally:
        db.close()


def test_a_bulk_accept_applies_the_valid_pairs_and_reports_the_rest(client, admin_token):
    world, project, requirement, element = _setup(client, admin_token)
    other = make_element(client, world.token, project["id"], "Not placed")
    _place(client, world, project, element, project["component_id"])
    result = _post(client, world, project, "accept", {"pairs": [
        {"requirement_id": str(requirement), "element_id": element["id"]},
        {"requirement_id": str(requirement), "element_id": other["id"]},
    ]})
    assert result["accepted"] == 1
    assert [f["element_id"] for f in result["failed"]] == [other["id"]]


def test_dismissing_hides_a_suggestion_and_restoring_brings_it_back(client, admin_token):
    world, project, requirement, element = _setup(client, admin_token)
    _place(client, world, project, element, project["component_id"])
    pair = {"requirement_id": str(requirement), "element_id": element["id"]}

    _post(client, world, project, "dismiss", pair, expect=204)
    view = _view(client, world, project, requirement=requirement)
    assert view["suggested"] == [] and _codes(view["dismissed"]) == ["ELM-001"]
    _post(client, world, project, "dismiss", pair, expect=204)  # idempotent
    assert _codes(_view(client, world, project, element=element)["dismissed"], "requirement")

    _post(client, world, project, "restore", pair, expect=204)
    view = _view(client, world, project, requirement=requirement)
    assert _codes(view["suggested"]) == ["ELM-001"] and view["dismissed"] == []


def test_a_dismissal_is_cleared_when_the_element_leaves_the_component_and_returns(client, admin_token):
    world, project, requirement, element = _setup(client, admin_token)
    _place(client, world, project, element, project["component_id"])
    _post(client, world, project, "dismiss", {"requirement_id": str(requirement), "element_id": element["id"]}, expect=204)

    _place(client, world, project, element, None)
    _place(client, world, project, element, project["component_id"])
    view = _view(client, world, project, requirement=requirement)
    assert _codes(view["suggested"]) == ["ELM-001"] and view["dismissed"] == []


def test_a_category_added_under_the_same_component_keeps_the_dismissal(client, admin_token):
    world, project, requirement, element = _setup(client, admin_token)
    _place(client, world, project, element, project["component_id"])
    _post(client, world, project, "dismiss", {"requirement_id": str(requirement), "element_id": element["id"]}, expect=204)
    resp = client.put(
        f"/api/v1/projects/{project['id']}/artefacts/{ELEMENT}/{element['id']}/placements",
        json={"placements": [
            {"component_id": project["component_id"], "category_id": None},
            {"component_id": project["component_id"], "category_id": project["category_id"]},
        ]},
        headers=auth_headers(world.token),
    )
    assert resp.status_code == 200, resp.text
    assert _view(client, world, project, requirement=requirement)["suggested"] == []


def test_dismissal_applies_rule():
    from datetime import UTC, datetime, timedelta

    at = datetime(2026, 11, 14, tzinfo=UTC)
    assert dismissal_applies(at, [at - timedelta(days=1)])
    assert dismissal_applies(at, [at, at + timedelta(days=1)])  # an added category keeps it
    assert not dismissal_applies(at, [at + timedelta(seconds=1)])
    assert not dismissal_applies(at, [])


def test_dismissing_a_pair_that_is_not_suggested_is_refused(client, admin_token):
    world, project, requirement, element = _setup(client, admin_token)
    _post(client, world, project, "dismiss", {"requirement_id": str(requirement), "element_id": element["id"]}, expect=409)
    _post(client, world, project, "dismiss", {"requirement_id": str(uuid.uuid4()), "element_id": element["id"]}, expect=404)


def test_a_member_without_link_authority_reads_but_cannot_act(client, admin_token):
    world, project, requirement, element = _setup(client, admin_token)
    _place(client, world, project, element, project["component_id"])
    _, token = add_member(client, world.token, world.org["id"], project["id"], f"viewer-{uuid.uuid4().hex[:6]}@example.com")
    view = _view(client, world, project, requirement=requirement, token=token)
    assert _codes(view["suggested"]) == ["ELM-001"]
    pair = {"requirement_id": str(requirement), "element_id": element["id"]}
    if not view["can_manage"]:
        _post(client, world, project, "dismiss", pair, token=token, expect=403)
        _post(client, world, project, "accept", {"pairs": [pair]}, token=token, expect=403)


def test_another_projects_records_look_absent(client, admin_token):
    world, project, requirement, element = _setup(client, admin_token)
    other = world.project("Other project")
    resp = client.get(f"{project_base(other['id'])}/requirements/{requirement}/allocation", headers=auth_headers(world.token))
    assert resp.status_code == 200 and resp.json()["suggested"] == [] and resp.json()["allocated"] == []
    _post(client, world, other, "dismiss", {"requirement_id": str(requirement), "element_id": element["id"]}, expect=404)


def test_each_decision_is_one_audit_event_naming_the_element_by_code(client, admin_token):
    world, project, requirement, element = _setup(client, admin_token)
    _place(client, world, project, element, project["component_id"])
    pair = {"requirement_id": str(requirement), "element_id": element["id"]}
    _post(client, world, project, "dismiss", pair, expect=204)
    _post(client, world, project, "restore", pair, expect=204)
    _post(client, world, project, "accept", {"pairs": [pair]})
    from app.database import SessionLocal
    from app.models.audit import AuditEvent

    db = SessionLocal()
    try:
        events = db.query(AuditEvent).filter(AuditEvent.entity_id == str(requirement), AuditEvent.action.like("allocation_%")).all()
        assert sorted(e.action for e in events) == ["allocation_accepted", "allocation_dismissed", "allocation_restored"]
        assert all(e.detail == {"element": "ELM-001"} for e in events)
    finally:
        db.close()


def test_coverage_counts_follow_allocation_and_suggestions(client, admin_token):
    world, project, requirement, element = _setup(client, admin_token)
    world.requirement(project, "Second")
    make_element(client, world.token, project["id"], "Loose")
    _place(client, world, project, element, project["component_id"])
    url = f"{project_base(project['id'])}/allocation/coverage"
    before = client.get(url, headers=auth_headers(world.token)).json()
    assert before == {"requirements": 2, "allocated_requirements": 0, "elements": 2, "allocated_elements": 0, "suggestions": 2}
    _post(client, world, project, "accept", {"pairs": [{"requirement_id": str(requirement), "element_id": element["id"]}]})
    after = client.get(url, headers=auth_headers(world.token)).json()
    assert after == {"requirements": 2, "allocated_requirements": 1, "elements": 2, "allocated_elements": 1, "suggestions": 1}


def test_the_overview_offers_the_allocation_metrics_and_they_match_the_coverage(client, admin_token):
    world, project, requirement, element = _setup(client, admin_token)
    world.requirement(project, "Second")
    _place(client, world, project, element, project["component_id"])
    _post(client, world, project, "accept", {"pairs": [{"requirement_id": str(requirement), "element_id": element["id"]}]})
    headers = auth_headers(world.token)
    catalogue = client.get(f"/api/v1/projects/{project['id']}/overview-catalogue", headers=headers).json()
    offered = {m["key"] for m in catalogue["metrics"]}
    keys = ["requirements_allocated", "requirements_unallocated", "elements_without_requirement", "suggested_allocations"]
    assert {f"architecture:{k}" for k in keys} <= offered
    resp = client.post(
        f"/api/v1/projects/{project['id']}/overview-metrics",
        json={"metrics": [{"id": k, "metric": f"architecture:{k}", "params": {}, "scope": "this"} for k in keys]}, headers=headers,
    )
    assert resp.status_code == 200, resp.text
    values = {key: result["value"] for key, result in resp.json()["results"].items()}
    assert values == {
        "requirements_allocated": 50.0, "requirements_unallocated": 1.0, "elements_without_requirement": 0.0,
        "suggested_allocations": 1.0,
    }
