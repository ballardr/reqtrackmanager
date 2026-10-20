"""Pins that the comment typed at a workflow step reaches the record's activity read under one key,
`detail.comment`: Pain Point steps, a Decision step and a change request decision. The Activity tab
shows that key beneath the sentence, so a comment that is stored under another name, or not at all,
is lost from the record's own history.

Each test builds its own organisation (`tests.link_world.World`), so none depends on state left by
another test or run.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from tests.conftest import auth_headers
from tests.link_world import REQ, World

PAIN = "pain_point"


@pytest.fixture
def world(client, admin_token) -> World:
    return World(client, admin_token, "Transition Comment Org", context_strategy=True, decisions=True)


def _activity(world: World, project: dict, artefact: tuple[str, uuid.UUID]) -> list[dict]:
    resp = world.client.get(
        f"/api/v1/projects/{project['id']}/artefacts/{artefact[0]}/{artefact[1]}/activity",
        headers=auth_headers(world.token),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["entries"]


def _comments_by_action(entries: list[dict]) -> dict[str, str | None]:
    return {e["action"]: (e["detail"] or {}).get("comment") for e in entries}


def _step(world: World, project: dict, pain: uuid.UUID, step: str, comment: str) -> None:
    base = f"/api/v1/projects/{project['id']}/modules/context_strategy/pain-points/{pain}"
    resp = world.client.post(f"{base}/{step}", json={"comment": comment}, headers=auth_headers(world.token))
    assert resp.status_code == 200, f"{step}: {resp.text}"


def test_every_pain_point_step_carries_its_comment_into_the_activity(world):
    project = world.project()
    pain = world.pain_point(project)
    for step, text in [
        ("triage", "Looks real"), ("accept", "We will fix it"), ("address", "Shipped in 2.1"), ("close", "Verified"),
    ]:
        _step(world, project, pain, step, text)

    comments = _comments_by_action(_activity(world, project, (PAIN, pain)))
    assert comments["triaged"] == "Looks real"
    assert comments["accepted"] == "We will fix it"
    assert comments["addressed"] == "Shipped in 2.1"
    assert comments["closed"] == "Verified"


@pytest.mark.parametrize("step", ["reject", "mark-duplicate"])
def test_the_mandatory_comment_of_a_pain_point_rejection_or_duplicate_is_in_the_activity(world, step):
    project = world.project()
    pain = world.pain_point(project)
    _step(world, project, pain, "triage", "")
    _step(world, project, pain, step, "Same as PP-001")

    entries = _activity(world, project, (PAIN, pain))
    match = [e for e in entries if e["detail"] and e["detail"].get("comment") == "Same as PP-001"]
    assert len(match) == 1, entries


def test_a_decision_approval_and_rejection_carry_their_comment_into_the_activity(world):
    project = world.project()
    base = f"/api/v1/projects/{project['id']}/modules/decisions"
    approved, rejected = world.decision(project, "DEC-1"), world.decision(project, "DEC-2")
    for decision, step, text in [(approved, "approve", "Agreed in the board meeting"), (rejected, "reject", "Too costly")]:
        for prelim in ("propose", "submit-for-review"):
            resp = world.client.post(f"{base}/{decision}/{prelim}", headers=auth_headers(world.token))
            assert resp.status_code == 200, resp.text
        resp = world.client.post(f"{base}/{decision}/{step}", json={"comment": text}, headers=auth_headers(world.token))
        assert resp.status_code == 200, resp.text

    assert _comments_by_action(_activity(world, project, ("decision", approved)))["approved"] == "Agreed in the board meeting"
    assert _comments_by_action(_activity(world, project, ("decision", rejected)))["rejected"] == "Too costly"


def test_a_change_request_decision_note_is_stored_as_comment(world):
    project = world.project()
    req = world.requirement(project, "Target")
    approve = world.client.post(f"/api/v1/projects/{project['id']}/requirements/{req}/approve", headers=auth_headers(world.token))
    assert approve.status_code == 200, approve.text
    created = world.client.post(
        f"/api/v1/projects/{project['id']}/change-requests",
        json={
            "kind": "modify_requirement", "requirement_id": str(req), "changed_fields": ["name"],
            "proposed_name": "Renamed by request", "reason": "clearer",
        },
        headers=auth_headers(world.token),
    )
    assert created.status_code == 201, created.text
    cr_id = created.json()["id"]
    submitted = world.client.post(f"/api/v1/projects/{project['id']}/change-requests/{cr_id}/submit", headers=auth_headers(world.token))
    assert submitted.status_code == 200, submitted.text
    decided = world.client.post(
        f"/api/v1/projects/{project['id']}/change-requests/{cr_id}/decide",
        json={"approve": False, "note": "Out of scope this quarter"}, headers=auth_headers(world.token),
    )
    assert decided.status_code == 200, decided.text

    entries = _activity(world, project, ("change_request", uuid.UUID(cr_id)))
    rejected = [e for e in entries if e["action"] == "rejected"]
    assert len(rejected) == 1
    assert rejected[0]["detail"].get("comment") == "Out of scope this quarter"
    assert "note" not in rejected[0]["detail"]


def test_a_change_request_decision_with_no_note_adds_no_empty_comment(world):
    project = world.project()
    req = world.requirement(project, "Target")
    world.client.post(f"/api/v1/projects/{project['id']}/requirements/{req}/approve", headers=auth_headers(world.token))
    created = world.client.post(
        f"/api/v1/projects/{project['id']}/change-requests",
        json={
            "kind": "modify_requirement", "requirement_id": str(req), "changed_fields": ["name"],
            "proposed_name": "Renamed again", "reason": "clearer",
        },
        headers=auth_headers(world.token),
    )
    cr_id = created.json()["id"]
    world.client.post(f"/api/v1/projects/{project['id']}/change-requests/{cr_id}/submit", headers=auth_headers(world.token))
    decided = world.client.post(
        f"/api/v1/projects/{project['id']}/change-requests/{cr_id}/decide",
        json={"approve": True, "note": ""}, headers=auth_headers(world.token),
    )
    assert decided.status_code == 200, decided.text
    approved = [e for e in _activity(world, project, ("change_request", uuid.UUID(cr_id))) if e["action"] == "approved"]
    assert approved and "comment" not in (approved[0]["detail"] or {})


def _approve(world: World, project: dict, req: uuid.UUID, **body):
    return world.client.post(
        f"/api/v1/projects/{project['id']}/requirements/{req}/approve",
        headers=auth_headers(world.token), **({"json": body} if body else {}),
    )


def test_requirement_approve_without_a_body_keeps_the_fixed_change_note(world):
    project = world.project()
    req = world.requirement(project, "Direct")
    resp = _approve(world, project, req)
    assert resp.status_code == 200, resp.text
    approved = [e for e in _activity(world, project, (REQ, req)) if e["action"] in ("approved", "updated")]
    assert any((e["detail"] or {}).get("change_note") == "Approved directly." for e in approved)
    assert not any("comment" in (e["detail"] or {}) for e in approved)


def test_requirement_approve_comment_reaches_the_activity_and_the_versions(world):
    project = world.project()
    req = world.requirement(project, "Commented")
    resp = _approve(world, project, req, comment="  Checked against the interface spec  ")
    assert resp.status_code == 200, resp.text

    entries = _activity(world, project, (REQ, req))
    assert [e["detail"]["change_note"] for e in entries if e["action"] == "updated"] == [
        "Approved directly: Checked against the interface spec"
    ]
    versions = world.client.get(
        f"/api/v1/projects/{project['id']}/requirements/{req}/history", headers=auth_headers(world.token)
    ).json()
    assert versions[-1]["change_note"] == "Approved directly: Checked against the interface spec"


def test_requirement_approve_comment_is_recorded_on_the_audit_event(world):
    project = world.project()
    req = world.requirement(project, "Audited")
    assert _approve(world, project, req, comment="Looks right").status_code == 200

    with SessionLocal() as db:
        event = db.scalars(
            select(AuditEvent).where(AuditEvent.entity_id == str(req), AuditEvent.action == "approved")
        ).one()
        assert event.detail == {"comment": "Looks right"}


@pytest.mark.parametrize("blank", ["", "   ", None])
def test_requirement_approve_blank_comment_is_the_same_as_none(world, blank):
    project = world.project()
    req = world.requirement(project, "Blank")
    resp = _approve(world, project, req, comment=blank)
    assert resp.status_code == 200, resp.text
    entries = _activity(world, project, (REQ, req))
    assert [e["detail"]["change_note"] for e in entries if e["action"] == "updated"] == ["Approved directly."]
