"""Tests for the phase schedules of stages and component tracks on the review engine (`services.stage_phase_plans`'s
`STAGE_PHASE_REVIEW_ADAPTER`) under a governance review policy: the type is listed as a reviewable type, the policy's lead
and default owner apply to its reminders, the stage's owner comes before the default owner, and a track that does not
apply, a phase schedule with component phases off and an archived project are not reminded. The reminders themselves, and
the boundary hours of their dates, are tested in `tests/test_stage_phase_plans.py`."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from app.database import SessionLocal
from app.modules.traceability.tests.test_governance_review_policy import (
    _entry,
    _member,
    _policy,
    _principal,
    _set_project,
    _world,
)
from app.services import review_engine
from tests.conftest import auth_headers

TYPE = "stage_phase"


def _url(project_id, tail="") -> str:
    return f"/api/v1/projects/{project_id}/{tail}"


def _stage(client, token, project_id) -> dict:
    return client.get(_url(project_id, "stages"), headers=auth_headers(token)).json()[0]


def _phase(client, token, project_id, name) -> str:
    workflows = client.get(_url(project_id, "stage-workflows"), headers=auth_headers(token)).json()
    return next(p["id"] for p in next(w for w in workflows if w["name"] == "Standard")["phases"] if p["name"] == name)


def _plan(client, token, project_id, stage_id, phase_id, start=None, end=None, component_id=None) -> None:
    resp = client.put(
        _url(project_id, f"stages/{stage_id}/phase-plan"),
        json={"phase_id": phase_id, "component_id": component_id, "expected_from": start, "expected_to": end},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text


def _sweep() -> int:
    with SessionLocal() as db:
        return review_engine.send_review_reminders(db, now=datetime.now(UTC))


def _inbox(client, token, kind) -> list[dict]:
    return [n for n in client.get("/api/v1/notifications", headers=auth_headers(token)).json() if n["type"] == kind]


def _days(offset: int) -> str:
    return (date.today() + timedelta(days=offset)).isoformat()


def test_the_phase_schedule_is_a_reviewable_type(client, admin_token):
    _, project, token = _world(client, admin_token, "Phase Review Listed Org")
    entry = _entry(_policy(client, token, project["id"]), TYPE)
    assert entry["label"] == "Stage phase"


def test_the_policy_lead_overrides_the_projects_phase_lead(client, admin_token):
    _, project, token = _world(client, admin_token, "Phase Review Lead Org")
    pid = project["id"]
    stage = _stage(client, token, pid)
    _plan(client, token, pid, stage["id"], _phase(client, token, pid, "Review"), _days(12), _days(14))
    assert _sweep() == 0  # twelve days ahead is beyond the project's seven
    assert _inbox(client, token, "stage_phase_upcoming") == []
    _set_project(client, token, pid, TYPE, {"lead_days": 14})
    assert _sweep() == 1
    assert len(_inbox(client, token, "stage_phase_upcoming")) == 1


def test_the_default_owner_is_told_when_the_stage_has_no_owner_and_the_stage_owner_comes_first(client, admin_token):
    org, project, token = _world(client, admin_token, "Phase Review Owner Org")
    pid = project["id"]
    default_id, default_token = _member(client, token, org["id"], pid)
    owner_id, owner_token = _member(client, token, org["id"], pid)
    _set_project(client, token, pid, TYPE, {"default_owner": _principal("user", default_id)})
    stage = _stage(client, token, pid)
    _plan(client, token, pid, stage["id"], _phase(client, token, pid, "Scoping"), None, _days(-5))
    assert _sweep() == 1
    assert len(_inbox(client, default_token, "stage_phase_overdue")) == 1
    assert _inbox(client, token, "stage_phase_overdue") == []  # the managers are the last resort

    owned = client.post(_url(pid, "stages"), json={"name": "Owned"}, headers=auth_headers(token)).json()
    patched = client.patch(
        _url(pid, f"stages/{owned['id']}"), json={"name": "Owned", "owner": _principal("user", owner_id)},
        headers=auth_headers(token),
    )
    assert patched.status_code == 200, patched.text
    _plan(client, token, pid, owned["id"], _phase(client, token, pid, "Scoping"), None, _days(-4))
    assert _sweep() == 1
    assert len(_inbox(client, owner_token, "stage_phase_overdue")) == 1
    assert len(_inbox(client, default_token, "stage_phase_overdue")) == 1  # still only the first stage's


def test_a_track_that_does_not_apply_and_a_schedule_with_component_phases_off_are_not_reminded(client, admin_token):
    _, project, token = _world(client, admin_token, "Phase Review Skip Org")
    pid = project["id"]
    headers = auth_headers(token)
    component = client.post(_url(pid, "components"), json={"name": "Software", "prefix": "SW"}, headers=headers).json()
    stage = _stage(client, token, pid)
    scoping = _phase(client, token, pid, "Scoping")
    assert client.put(_url(pid, "component-phases-settings"), json={"mode": "on"}, headers=headers).status_code == 200
    _plan(client, token, pid, stage["id"], scoping, None, _days(-5), component["id"])
    off = client.put(_url(pid, "component-phases-settings"), json={"mode": "off"}, headers=headers)
    assert off.status_code == 200
    assert _sweep() == 0  # the component's plan is kept and inert while component phases are off

    assert client.put(_url(pid, "component-phases-settings"), json={"mode": "on"}, headers=headers).status_code == 200
    marked = client.patch(
        _url(pid, f"components/{component['id']}/stages/{stage['id']}/track"), json={"not_applicable": True}, headers=headers,
    )
    assert marked.status_code == 200, marked.text
    assert _sweep() == 0
    assert client.patch(
        _url(pid, f"components/{component['id']}/stages/{stage['id']}/track"), json={"not_applicable": False}, headers=headers,
    ).status_code == 200
    assert _sweep() == 1
    assert len(_inbox(client, token, "stage_phase_overdue")) == 1


def test_an_archived_project_is_not_reminded(client, admin_token):
    _, project, token = _world(client, admin_token, "Phase Review Archived Org")
    pid = project["id"]
    stage = _stage(client, token, pid)
    _plan(client, token, pid, stage["id"], _phase(client, token, pid, "Scoping"), None, _days(-5))
    assert client.post(_url(pid, "archive"), headers=auth_headers(token)).status_code == 200
    assert _sweep() == 0
