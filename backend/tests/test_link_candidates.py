"""Tests for the Links panel's backend support: the `link-candidates` target search, and the graph's `can_link` / per-edge
`dedicated` flags the panel uses to hide controls that would only answer 403/400.

Each test builds its own organisation (`tests.link_world.World`), so none depends on state
left by another test or run.
"""

from __future__ import annotations

import uuid

import pytest

from app.database import SessionLocal
from app.modules.decisions.models import Decision
from app.modules.decisions.service import create_supersession
from tests.conftest import auth_headers, create_org_user, login
from tests.link_world import ACTION, REQ, World

DEC = "decision"
PAIN = "pain_point"


@pytest.fixture
def world(client, admin_token) -> World:
    return World(client, admin_token, "Candidates Org", decisions=True, context_strategy=True)


def _candidates(world: World, project: dict, artefact: tuple[str, uuid.UUID], token=None, **params):
    return world.client.get(
        f"/api/v1/projects/{project['id']}/artefacts/{artefact[0]}/{artefact[1]}/link-candidates", params=params,
        headers=auth_headers(token or world.token),
    )


def _labels(resp) -> list[str]:
    assert resp.status_code == 200, resp.text
    return [item["label"] for item in resp.json()["items"]]


def test_candidates_cover_core_and_module_types_and_exclude_the_page_artefact(world):
    project = world.project()
    req_a = world.requirement(project, "Alpha need")
    world.requirement(project, "Beta need")
    world.action(project, "Do it")
    pain = world.pain_point(project, "Slow reports")
    dec = world.decision(project)

    # Same type: the page artefact itself is never offered.
    labels = _labels(_candidates(world, project, (REQ, req_a), other_type=REQ))
    assert len(labels) == 1 and "Beta need" in labels[0]
    assert any("Do it" in label for label in _labels(_candidates(world, project, (REQ, req_a), other_type=ACTION)))
    assert _labels(_candidates(world, project, (REQ, req_a), other_type=PAIN)) == ["Slow reports"]
    body = _candidates(world, project, (PAIN, pain), other_type=DEC).json()
    assert [i["id"] for i in body["items"]] == [str(dec)]
    assert body["items"][0]["type"] == DEC and body["items"][0]["type_label"] == "Decision"
    assert body["truncated"] is False
    # An unrelated type with the page artefact as its only member: the page artefact is excluded.
    assert _labels(_candidates(world, project, (PAIN, pain), other_type=PAIN)) == []


def test_candidates_filter_by_text_case_insensitively(world):
    project = world.project()
    page = world.requirement(project, "Page")
    world.requirement(project, "Voltage limit")
    world.requirement(project, "Cable length")
    assert [label.split(" ", 1)[1] for label in _labels(_candidates(world, project, (REQ, page), other_type=REQ, q="VOLT"))] == [
        "Voltage limit"
    ]
    assert _labels(_candidates(world, project, (REQ, page), other_type=REQ, q="no such thing")) == []


def test_candidates_never_offer_archived_records(world):
    project = world.project()
    page, other = world.requirement(project, "Page"), world.requirement(project, "Old")
    resp = world.client.delete(
        f"/api/v1/projects/{project['id']}/requirements/{other}", headers=auth_headers(world.token)
    )
    assert resp.status_code == 204, resp.text
    assert _labels(_candidates(world, project, (REQ, page), other_type=REQ)) == []


def test_candidates_report_truncation(world, monkeypatch):
    project = world.project()
    page = world.requirement(project, "Page")
    for i in range(3):
        world.requirement(project, f"Extra {i}")
    body = _candidates(world, project, (REQ, page), other_type=REQ, limit=2).json()
    assert len(body["items"]) == 2 and body["truncated"] is True


def test_candidates_search_an_ancestor_project_only_when_related_and_viewable(world, client):
    parent = world.project("Parent")
    child = world.project("Child", parent=parent)
    sibling = world.project("Sibling", parent=parent)
    page = world.requirement(child, "Child page")
    world.requirement(parent, "Parent need")
    world.requirement(child, "Child only")
    world.requirement(sibling, "Sibling need")

    labels = _labels(_candidates(world, child, (REQ, page), other_type=REQ, other_project_id=parent["id"]))
    assert len(labels) == 1 and "Parent need" in labels[0]
    # Without other_project_id only the page's own project is searched.
    assert all("Parent need" not in label for label in _labels(_candidates(world, child, (REQ, page), other_type=REQ)))
    # A sibling is not a related project: the answer is a plain 404.
    assert _candidates(
        world, child, (REQ, page), other_type=REQ, other_project_id=sibling["id"]
    ).status_code == 404


def test_candidates_reject_unknown_type_and_unseen_page_artefact(world):
    project = world.project()
    page = world.requirement(project)
    assert _candidates(world, project, (REQ, page), other_type="not_a_type").status_code == 404
    assert _candidates(world, project, (REQ, uuid.uuid4()), other_type=REQ).status_code == 404
    # Without other_type the search spans every type and needs a query, so none is an empty answer.
    assert _labels(_candidates(world, project, (REQ, page))) == []


def test_candidates_are_empty_for_a_module_disabled_in_the_project(client, admin_token):
    plain = World(client, admin_token, "No Modules Org")
    project = plain.project()
    page = plain.requirement(project)
    assert _labels(_candidates(plain, project, (REQ, page), other_type=DEC)) == []


def test_non_member_is_refused(world, client, admin_token):
    project = world.project()
    page = world.requirement(project)
    outsider = World(client, admin_token, "Outsider Org")
    assert _candidates(world, project, (REQ, page), token=outsider.token, other_type=REQ).status_code == 403


def test_graph_can_link_reflects_the_link_permission(world, client):
    project = world.project()
    req = world.requirement(project)
    assert world.graph(project, (REQ, req)).json()["can_link"] is True
    email = f"viewer-{uuid.uuid4().hex[:6]}@example.com"
    user_id = create_org_user(client, world.token, world.org["id"], email)
    client.post(
        f"/api/v1/projects/{project['id']}/roles", json={"user_id": user_id, "role": "member"},
        headers=auth_headers(world.token),
    )
    member = login(client, email, "Password123!")
    assert world.graph(project, (REQ, req), token=member).json()["can_link"] is False


def test_graph_edges_flag_dedicated_links(world):
    project = world.project()
    dec_a, dec_b = world.decision(project, "DEC-1"), world.decision(project, "DEC-2")
    related = world.link_types_by_name()["Related to"]["id"]
    req = world.requirement(project)
    world.link((REQ, req), (DEC, dec_a), related)
    db = SessionLocal()
    try:
        create_supersession(db, new_decision=db.get(Decision, dec_b), old_decision=db.get(Decision, dec_a), actor_id=world.user_id)
        db.commit()
    finally:
        db.close()
    edges = {e["to_id"]: e for e in world.graph(project, (DEC, dec_b), depth=1).json()["edges"]}
    assert edges[str(dec_a)]["dedicated"] is True
    plain = world.graph(project, (REQ, req), depth=1).json()["edges"]
    assert [e["dedicated"] for e in plain] == [False]


def test_untyped_structural_links_are_flagged_dedicated_and_cannot_be_deleted_generically(world):
    project = world.project()
    req, action = world.requirement(project), world.action(project)
    resp = world.client.post(
        f"/api/v1/projects/{project['id']}/requirements/{req}/actions", json={"action_id": str(action)},
        headers=auth_headers(world.token),
    )
    assert resp.status_code == 204, resp.text
    edges = world.graph(project, (REQ, req), depth=1).json()["edges"]
    assert [(e["to_type"], e["phrase"], e["dedicated"]) for e in edges] == [(ACTION, None, True)]
    gone = world.client.delete(
        f"/api/v1/projects/{project['id']}/artefacts/{REQ}/{req}/links/{edges[0]['id']}",
        headers=auth_headers(world.token),
    )
    assert gone.status_code == 400 and "structural" in gone.json()["detail"]
