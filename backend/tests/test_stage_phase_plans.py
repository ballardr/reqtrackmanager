"""Phase schedule and reminders: setting and clearing a phase's expected range (stage and component track),
the actual dates a move records, the once-per-date upcoming and overdue sweep with its two timezone boundaries,
who is told (owner, group, project managers, never the actor), the lead time and its inheritance, and bundles
and template cloning."""

import io
import uuid
import zipfile
from datetime import UTC, date, datetime, timedelta

from app.database import SessionLocal
from app.services.report_fields import load_records
from app.services.stage_phase_plans import send_phase_reminders
from tests.conftest import auth_headers, create_component_and_category, create_org_user, create_project, create_project_group, login
from tests.stage_helpers import move_stage


def _url(project_id: str, tail: str = "") -> str:
    return f"/api/v1/projects/{project_id}/{tail}"


def _stage(client, token, project_id) -> dict:
    return client.get(_url(project_id, "stages"), headers=auth_headers(token)).json()[0]


def _phase(client, token, project_id, name: str) -> str:
    workflows = client.get(_url(project_id, "stage-workflows"), headers=auth_headers(token)).json()
    standard = next(w for w in workflows if w["name"] == "Standard")
    return next(p["id"] for p in standard["phases"] if p["name"] == name)


def _plan(client, token, project_id, stage_id, phase_id, start=None, end=None, component_id=None):
    return client.put(
        _url(project_id, f"stages/{stage_id}/phase-plan"),
        json={"phase_id": phase_id, "component_id": component_id, "expected_from": start, "expected_to": end},
        headers=auth_headers(token),
    )


def _set_owner(client, token, project_id, stage, owner):
    """Sets (or with None clears) the stage's owner, returning the response."""
    return client.patch(
        _url(project_id, f"stages/{stage['id']}"), json={"name": stage["name"], "owner": owner}, headers=auth_headers(token),
    )


def _plans(client, token, project_id) -> dict:
    return client.get(_url(project_id, "phase-plans"), headers=auth_headers(token)).json()


def _sweep(now: datetime) -> None:
    db = SessionLocal()
    try:
        send_phase_reminders(db, now)
    finally:
        db.close()


def _inbox(client, token, kind: str) -> list[dict]:
    rows = client.get("/api/v1/notifications", headers=auth_headers(token)).json()
    return [n for n in rows if n["type"] == kind]


def _member(client, admin_token, org_id, project_id, email) -> tuple[str, str]:
    user_id = create_org_user(client, admin_token, org_id, email)
    resp = client.post(_url(project_id, "roles"), json={"user_id": user_id, "role": "member"}, headers=auth_headers(admin_token))
    assert resp.status_code in (200, 201, 204), resp.text
    return user_id, login(client, email, "Password123!")


def _world(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    return project, _stage(client, admin_token, project["id"])


def test_a_manager_sets_and_clears_a_phase_range(client, admin_token, org_id):
    project, stage = _world(client, admin_token, org_id)
    review = _phase(client, admin_token, project["id"], "Review")
    resp = _plan(client, admin_token, project["id"], stage["id"], review, "2026-12-01", "2026-12-10")
    assert resp.status_code == 200, resp.text
    plan = resp.json()["plans"][0]
    assert (plan["phase_id"], plan["component_id"], plan["expected_from"], plan["expected_to"]) == (review, None, "2026-12-01", "2026-12-10")
    assert (plan["started_at"], plan["completed_at"]) == (None, None)
    assert _plan(client, admin_token, project["id"], stage["id"], review).json()["plans"] == []


def test_a_range_must_run_forward_and_belong_to_the_stage_workflow(client, admin_token, org_id):
    project, stage = _world(client, admin_token, org_id)
    review = _phase(client, admin_token, project["id"], "Review")
    assert _plan(client, admin_token, project["id"], stage["id"], review, "2026-12-10", "2026-12-01").status_code == 400
    other = client.post(
        f"/api/v1/orgs/{org_id}/stage-workflows",
        json={"name": "Other", "phases": [{"name": "Draft", "kind": "open"}]}, headers=auth_headers(admin_token),
    ).json()
    assert _plan(client, admin_token, project["id"], stage["id"], other["phases"][0]["id"], "2026-12-01", "2026-12-02").status_code == 400


def test_only_a_manager_may_set_a_range_or_the_lead_time(client, admin_token, org_id):
    project, stage = _world(client, admin_token, org_id)
    _user_id, token = _member(client, admin_token, org_id, project["id"], "viewer@example.com")
    review = _phase(client, admin_token, project["id"], "Review")
    assert _plan(client, token, project["id"], stage["id"], review, "2026-12-01", "2026-12-02").status_code == 403
    assert client.put(_url(project["id"], "phase-reminder-settings"), json={"lead_days": 3}, headers=auth_headers(token)).status_code == 403
    assert client.get(_url(project["id"], "phase-plans"), headers=auth_headers(token)).status_code == 200


def test_moves_record_actual_dates_and_moving_back_reopens(client, admin_token, org_id):
    project, stage = _world(client, admin_token, org_id)
    headers = auth_headers(admin_token)
    scoping, review = (_phase(client, admin_token, project["id"], n) for n in ("Scoping", "Review"))
    assert move_stage(client, project["id"], stage["id"], "review", headers=headers).status_code == 200
    by_phase = {p["phase_id"]: p for p in _plans(client, admin_token, project["id"])["plans"]}
    assert by_phase[scoping]["completed_at"] is not None
    assert by_phase[review]["started_at"] is not None and by_phase[review]["completed_at"] is None

    assert move_stage(client, project["id"], stage["id"], "scoping", headers=headers).status_code == 200
    by_phase = {p["phase_id"]: p for p in _plans(client, admin_token, project["id"])["plans"]}
    assert by_phase[scoping]["completed_at"] is None  # reopened
    assert by_phase[review]["completed_at"] is None  # left backwards, never completed


def test_entering_a_closed_phase_completes_it_and_the_phase_left(client, admin_token, org_id):
    project, stage = _world(client, admin_token, org_id)
    headers = auth_headers(admin_token)
    assert move_stage(client, project["id"], stage["id"], "review", headers=headers).status_code == 200
    assert move_stage(client, project["id"], stage["id"], "approved", headers=headers).status_code == 200
    assert move_stage(client, project["id"], stage["id"], "completed", headers=headers).status_code == 200
    by_phase = {p["phase_id"]: p for p in _plans(client, admin_token, project["id"])["plans"]}
    assert by_phase[_phase(client, admin_token, project["id"], "Approved")]["completed_at"] is not None
    assert by_phase[_phase(client, admin_token, project["id"], "Completed")]["completed_at"] is not None


def test_a_scheduled_phase_completing_tells_the_owner_but_not_the_actor(client, admin_token, org_id):
    project, stage = _world(client, admin_token, org_id)
    headers = auth_headers(admin_token)
    owner_id, owner_token = _member(client, admin_token, org_id, project["id"], "owner@example.com")
    assert client.patch(
        _url(project["id"], f"stages/{stage['id']}"), json={"name": stage["name"], "owner": {"type": "user", "id": owner_id}}, headers=headers,
    ).status_code == 200
    scoping = _phase(client, admin_token, project["id"], "Scoping")
    _plan(client, admin_token, project["id"], stage["id"], scoping, "2026-11-01", "2026-11-10")
    assert move_stage(client, project["id"], stage["id"], "review", headers=headers).status_code == 200
    told = _inbox(client, owner_token, "stage_phase_completed")
    assert len(told) == 1 and "Scoping" in told[0]["title"] and "2026-11-10" in told[0]["body"]
    assert _inbox(client, admin_token, "stage_phase_completed") == []  # the actor is never told


def test_an_unscheduled_phase_completing_sends_no_phase_notification(client, admin_token, org_id):
    project, stage = _world(client, admin_token, org_id)
    manager_id = create_org_user(client, admin_token, org_id, "second.manager@example.com")
    client.post(_url(project["id"], "roles"), json={"user_id": manager_id, "role": "project_manager"}, headers=auth_headers(admin_token))
    manager_token = login(client, "second.manager@example.com", "Password123!")
    assert move_stage(client, project["id"], stage["id"], "review", headers=auth_headers(admin_token)).status_code == 200
    assert _inbox(client, manager_token, "stage_phase_completed") == []


def test_upcoming_is_sent_once_per_date_and_a_new_date_re_arms_it(client, admin_token, org_id):
    project, stage = _world(client, admin_token, org_id)
    review = _phase(client, admin_token, project["id"], "Review")
    _plan(client, admin_token, project["id"], stage["id"], review, "2026-11-17", "2026-11-20")
    now = datetime(2026, 11, 10, 10, 0, tzinfo=UTC)
    _sweep(now)
    _sweep(now + timedelta(hours=1))
    assert len(_inbox(client, admin_token, "stage_phase_upcoming")) == 1  # the manager is told, once
    _plan(client, admin_token, project["id"], stage["id"], review, "2026-11-18", "2026-11-20")
    _sweep(now + timedelta(hours=2))
    assert len(_inbox(client, admin_token, "stage_phase_upcoming")) == 2


def test_upcoming_uses_the_latest_day_anywhere_and_the_lead_time(client, admin_token, org_id):
    project, stage = _world(client, admin_token, org_id)
    review = _phase(client, admin_token, project["id"], "Review")
    _plan(client, admin_token, project["id"], stage["id"], review, "2026-11-18", "2026-11-20")
    # 09:59 UTC is 23:59 on the 10th at UTC+14: the 18th is eight days off, beyond the seven-day default.
    _sweep(datetime(2026, 11, 10, 9, 59, tzinfo=UTC))
    assert _inbox(client, admin_token, "stage_phase_upcoming") == []
    # One minute later it is the 11th there, so the 18th is exactly seven days off.
    _sweep(datetime(2026, 11, 10, 10, 0, tzinfo=UTC))
    assert len(_inbox(client, admin_token, "stage_phase_upcoming")) == 1


def test_a_longer_lead_time_reminds_earlier(client, admin_token, org_id):
    project, stage = _world(client, admin_token, org_id)
    review = _phase(client, admin_token, project["id"], "Review")
    changed = client.put(_url(project["id"], "phase-reminder-settings"), json={"lead_days": 14}, headers=auth_headers(admin_token))
    assert changed.json()["lead_days"] == 14
    _plan(client, admin_token, project["id"], stage["id"], review, "2026-11-20", "2026-11-25")
    _sweep(datetime(2026, 11, 10, 10, 0, tzinfo=UTC))
    assert len(_inbox(client, admin_token, "stage_phase_upcoming")) == 1


def test_a_phase_already_reached_or_behind_the_current_one_is_not_upcoming(client, admin_token, org_id):
    project, stage = _world(client, admin_token, org_id)
    headers = auth_headers(admin_token)
    scoping = _phase(client, admin_token, project["id"], "Scoping")
    _plan(client, admin_token, project["id"], stage["id"], scoping, "2026-11-11", "2026-11-12")
    move_stage(client, project["id"], stage["id"], "review", headers=headers)
    _sweep(datetime(2026, 11, 10, 10, 0, tzinfo=UTC))
    assert _inbox(client, admin_token, "stage_phase_upcoming") == []


def test_overdue_needs_the_date_to_have_passed_everywhere_and_is_sent_once(client, admin_token, org_id):
    project, stage = _world(client, admin_token, org_id)
    scoping = _phase(client, admin_token, project["id"], "Scoping")
    _plan(client, admin_token, project["id"], stage["id"], scoping, None, "2026-11-09")
    # 11:59 UTC is 23:59 on the 9th at UTC-12: the day has not ended everywhere.
    _sweep(datetime(2026, 11, 10, 11, 59, tzinfo=UTC))
    assert _inbox(client, admin_token, "stage_phase_overdue") == []
    _sweep(datetime(2026, 11, 10, 12, 0, tzinfo=UTC))
    _sweep(datetime(2026, 11, 11, 12, 0, tzinfo=UTC))
    told = _inbox(client, admin_token, "stage_phase_overdue")
    assert len(told) == 1 and "2026-11-09" in told[0]["title"]


def test_a_phase_that_was_left_is_not_overdue(client, admin_token, org_id):
    project, stage = _world(client, admin_token, org_id)
    scoping = _phase(client, admin_token, project["id"], "Scoping")
    _plan(client, admin_token, project["id"], stage["id"], scoping, None, "2026-11-09")
    move_stage(client, project["id"], stage["id"], "review", headers=auth_headers(admin_token))
    _sweep(datetime(2026, 11, 12, 12, 0, tzinfo=UTC))
    assert _inbox(client, admin_token, "stage_phase_overdue") == []


def test_reminders_go_to_the_owner_or_a_group_before_the_managers(client, admin_token, org_id):
    project, stage = _world(client, admin_token, org_id)
    headers = auth_headers(admin_token)
    member_id, member_token = _member(client, admin_token, org_id, project["id"], "team@example.com")
    group_id = create_project_group(client, admin_token, project["id"], "Delivery team", users=[member_id])
    assert client.patch(
        _url(project["id"], f"stages/{stage['id']}"),
        json={"name": stage["name"], "owner": {"type": "project_group", "id": group_id}}, headers=headers,
    ).status_code == 200
    scoping = _phase(client, admin_token, project["id"], "Scoping")
    _plan(client, admin_token, project["id"], stage["id"], scoping, None, "2026-11-09")
    _sweep(datetime(2026, 11, 12, 12, 0, tzinfo=UTC))
    assert len(_inbox(client, member_token, "stage_phase_overdue")) == 1
    assert _inbox(client, admin_token, "stage_phase_overdue") == []  # the group, not the managers


def test_the_stage_owner_must_be_a_valid_principal_and_can_be_cleared(client, admin_token, org_id):
    project, stage = _world(client, admin_token, org_id)
    headers = auth_headers(admin_token)
    bad = client.patch(
        _url(project["id"], f"stages/{stage['id']}"),
        json={"name": stage["name"], "owner": {"type": "user", "id": "00000000-0000-0000-0000-000000000000"}}, headers=headers,
    )
    assert bad.status_code == 400
    owner_id, _token = _member(client, admin_token, org_id, project["id"], "owner@example.com")
    assert _set_owner(client, admin_token, project["id"], stage, {"type": "user", "id": owner_id}).json()["owner"]["id"] == owner_id
    kept = client.patch(_url(project["id"], f"stages/{stage['id']}"), json={"name": stage["name"]}, headers=headers)
    assert kept.json()["owner"]["id"] == owner_id  # absent leaves it
    assert _set_owner(client, admin_token, project["id"], stage, None).json()["owner"] is None


def test_a_project_group_that_owns_a_stage_cannot_be_deleted_silently(client, admin_token, org_id):
    project, stage = _world(client, admin_token, org_id)
    headers = auth_headers(admin_token)
    group_id = create_project_group(client, admin_token, project["id"], "Delivery team")
    client.patch(
        _url(project["id"], f"stages/{stage['id']}"),
        json={"name": stage["name"], "owner": {"type": "project_group", "id": group_id}}, headers=headers,
    )
    usage = client.get(_url(project["id"], f"groups/{group_id}/usage"), headers=headers)
    assert any("stage owners" in item["label"] for item in usage.json()["items"])


def test_the_lead_time_inherits_from_an_ancestor_and_is_bounded(client, admin_token, org_id):
    parent = create_project(client, admin_token, org_id, name="Parent", can_be_parent=True)
    child = create_project(client, admin_token, org_id, name="Child", parent_project_id=parent["id"])
    headers = auth_headers(admin_token)
    assert _plans(client, admin_token, child["id"])["lead_days"] == 7
    client.put(_url(parent["id"], "phase-reminder-settings"), json={"lead_days": 3}, headers=headers)
    inherited = _plans(client, admin_token, child["id"])
    assert (inherited["lead_days"], inherited["own_lead_days"], inherited["inherited"]) == (3, None, True)
    own = client.put(_url(child["id"], "phase-reminder-settings"), json={"lead_days": 0}, headers=headers).json()
    assert (own["lead_days"], own["inherited"]) == (0, False)
    assert client.put(_url(child["id"], "phase-reminder-settings"), json={"lead_days": 400}, headers=headers).status_code == 422
    assert client.put(_url(child["id"], "phase-reminder-settings"), json={"lead_days": None}, headers=headers).json()["lead_days"] == 3


def _component(client, token, project_id) -> dict:
    return client.post(_url(project_id, "components"), json={"name": "Software", "prefix": "SW"}, headers=auth_headers(token)).json()


def test_a_component_plan_needs_component_phases_on_and_follows_the_track(client, admin_token, org_id):
    project, stage = _world(client, admin_token, org_id)
    headers = auth_headers(admin_token)
    component = _component(client, admin_token, project["id"])
    review = _phase(client, admin_token, project["id"], "Review")
    assert _plan(client, admin_token, project["id"], stage["id"], review, "2026-11-12", "2026-11-14", component["id"]).status_code == 409
    client.put(_url(project["id"], "component-phases-settings"), json={"mode": "on"}, headers=headers)
    resp = _plan(client, admin_token, project["id"], stage["id"], review, "2026-11-12", "2026-11-14", component["id"])
    assert resp.status_code == 200, resp.text
    assert resp.json()["plans"][0]["component_id"] == component["id"]
    # Switched off, the component plan is inert and nothing is sent; back on, the component's track is told.
    client.put(_url(project["id"], "component-phases-settings"), json={"mode": "off"}, headers=headers)
    _sweep(datetime(2026, 11, 10, 10, 0, tzinfo=UTC))
    assert _inbox(client, admin_token, "stage_phase_upcoming") == []
    client.put(_url(project["id"], "component-phases-settings"), json={"mode": "on"}, headers=headers)
    _sweep(datetime(2026, 11, 10, 10, 0, tzinfo=UTC))
    assert len(_inbox(client, admin_token, "stage_phase_upcoming")) == 1


def test_a_component_track_move_records_its_own_actual_dates(client, admin_token, org_id):
    project, stage = _world(client, admin_token, org_id)
    headers = auth_headers(admin_token)
    component = _component(client, admin_token, project["id"])
    client.put(_url(project["id"], "component-phases-settings"), json={"mode": "on"}, headers=headers)
    scoping, review = (_phase(client, admin_token, project["id"], n) for n in ("Scoping", "Review"))
    _plan(client, admin_token, project["id"], stage["id"], scoping, "2026-11-01", "2026-11-05", component["id"])
    moved = client.post(
        _url(project["id"], f"components/{component['id']}/stages/{stage['id']}/transition"), json={"phase_id": review}, headers=headers,
    )
    assert moved.status_code == 200, moved.text
    plans = _plans(client, admin_token, project["id"])["plans"]
    assert all(p["component_id"] == component["id"] for p in plans)
    by_phase = {p["phase_id"]: p for p in plans}
    assert by_phase[scoping]["completed_at"] is not None and by_phase[review]["started_at"] is not None


def test_the_schedule_round_trips_through_the_project_bundle(client, admin_token, org_id):
    project, stage = _world(client, admin_token, org_id)
    headers = auth_headers(admin_token)
    component = _component(client, admin_token, project["id"])
    client.put(_url(project["id"], "component-phases-settings"), json={"mode": "on"}, headers=headers)
    client.put(_url(project["id"], "phase-reminder-settings"), json={"lead_days": 10}, headers=headers)
    owner_id, _token = _member(client, admin_token, org_id, project["id"], "owner@example.com")
    _set_owner(client, admin_token, project["id"], stage, {"type": "user", "id": owner_id})
    scoping, review = (_phase(client, admin_token, project["id"], n) for n in ("Scoping", "Review"))
    _plan(client, admin_token, project["id"], stage["id"], scoping, "2026-11-01", "2026-11-05")
    _plan(client, admin_token, project["id"], stage["id"], review, "2026-11-06", "2026-11-09", component["id"])
    move_stage(client, project["id"], stage["id"], "review", headers=headers)

    export = client.get(_url(project["id"], "export"), headers=headers)
    assert b"stage_phase_plans" in zipfile.ZipFile(io.BytesIO(export.content)).read("project.json")
    imported = client.post(
        "/api/v1/projects/import", data={"organization_id": org_id, "name": "Schedule copy"},
        files={"file": ("bundle.zip", export.content, "application/zip")}, headers=headers,
    )
    assert imported.status_code == 201, imported.text
    new_id = imported.json()["project"]["id"]
    copy = _plans(client, admin_token, new_id)
    assert (copy["lead_days"], copy["own_lead_days"]) == (10, 10)
    assert _stage(client, admin_token, new_id)["owner"]["id"] == owner_id
    new_scoping, new_review = (_phase(client, admin_token, new_id, n) for n in ("Scoping", "Review"))
    by_phase = {p["phase_id"]: p for p in copy["plans"] if p["component_id"] is None}
    assert (by_phase[new_scoping]["expected_from"], by_phase[new_scoping]["expected_to"]) == ("2026-11-01", "2026-11-05")
    assert by_phase[new_scoping]["completed_at"] is not None  # actual dates are carried as history
    component_plan = next(p for p in copy["plans"] if p["component_id"] is not None)
    assert (component_plan["phase_id"], component_plan["expected_to"]) == (new_review, "2026-11-09")
    # The reminder markers are not carried, so an import re-arms: a sweep after the end date finds the plan fresh.
    _sweep(datetime(2026, 11, 8, 10, 0, tzinfo=UTC))


def test_a_template_clone_copies_the_lead_time_but_no_dates(client, admin_token, org_id):
    template, stage = _world(client, admin_token, org_id)
    headers = auth_headers(admin_token)
    client.put(_url(template["id"], "phase-reminder-settings"), json={"lead_days": 21}, headers=headers)
    _plan(client, admin_token, template["id"], stage["id"], _phase(client, admin_token, template["id"], "Review"), "2026-11-06", "2026-11-09")
    client.patch(_url(template["id"]), json={"is_template": True}, headers=headers)
    resp = client.post(
        "/api/v1/projects", json={"organization_id": org_id, "name": "From template", "summary": "", "template_project_id": template["id"]},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    copy = _plans(client, admin_token, resp.json()["id"])
    assert (copy["lead_days"], copy["plans"]) == (21, [])


def test_the_range_dates_are_plain_dates(client, admin_token, org_id):
    project, stage = _world(client, admin_token, org_id)
    review = _phase(client, admin_token, project["id"], "Review")
    plan = _plan(client, admin_token, project["id"], stage["id"], review, date(2026, 12, 1).isoformat(), date(2026, 12, 1).isoformat())
    assert plan.json()["plans"][0]["expected_from"] == "2026-12-01"


def test_requirements_report_the_expected_end_and_start_of_their_stage_phase(client, admin_token, org_id):
    project, stage = _world(client, admin_token, org_id)
    headers = auth_headers(admin_token)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    requirement = client.post(
        _url(project["id"], "requirements"),
        json={"name": "Reported", "component_id": component_id, "category_id": category_id, "target_stage_id": stage["id"]},
        headers=headers,
    ).json()
    scoping = _phase(client, admin_token, project["id"], "Scoping")
    _plan(client, admin_token, project["id"], stage["id"], scoping, "2026-11-01", "2026-11-09")
    # A range on a phase the stage has left is not the stage's current schedule.
    _plan(client, admin_token, project["id"], stage["id"], _phase(client, admin_token, project["id"], "Review"), "2026-12-01", "2026-12-05")

    def values() -> dict:
        db = SessionLocal()
        try:
            fields = ["target_stage_phase_expected_end", "target_stage_phase_started_at"]
            return load_records(db, "requirement", [uuid.UUID(requirement["id"])], fields)[uuid.UUID(requirement["id"])].values
        finally:
            db.close()

    current = values()
    assert str(current["target_stage_phase_expected_end"]) == "2026-11-09" and current["target_stage_phase_started_at"] is None
    move_stage(client, project["id"], stage["id"], "review", headers=headers)
    moved = values()
    assert str(moved["target_stage_phase_expected_end"]) == "2026-12-05" and moved["target_stage_phase_started_at"] is not None
