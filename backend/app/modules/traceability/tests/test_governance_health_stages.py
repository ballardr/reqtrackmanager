"""Tests for the stage figures in governance health (`services.health_core`'s project stage and component phase providers):
the share of stages and tracks in a Closed phase, On hold left out, component phases off reporting no track figure, the
figures open to every member, a flat statement count as stages and components grow, and a snapshot that predates the
open-to-members flag."""

from __future__ import annotations

import uuid

from sqlalchemy import event

from app.database import SessionLocal, engine
from app.models.project import Project
from app.modules.traceability import health
from app.modules.traceability.tests.test_governance_baseline_policy import _world
from app.modules.traceability.tests.test_governance_health import _category, _get_health
from tests.conftest import auth_headers
from tests.stage_helpers import move_stage

STAGE = "project_stage"
TRACK = "component_stage"


def _headers(token) -> dict[str, str]:
    return auth_headers(token)


def _add_stage(client, token, project_id, name, phase=None) -> dict:
    created = client.post(f"/api/v1/projects/{project_id}/stages", json={"name": name}, headers=_headers(token))
    assert created.status_code == 201, created.text
    stage = created.json()
    if phase is not None:
        moved = move_stage(client, project_id, stage["id"], phase, headers=_headers(token))
        assert moved.status_code == 200, moved.text
    return stage


def _add_component(client, token, project_id, prefix) -> dict:
    created = client.post(
        f"/api/v1/projects/{project_id}/components", json={"name": f"Component {prefix}", "prefix": prefix},
        headers=_headers(token),
    )
    assert created.status_code in (200, 201), created.text
    return created.json()


def _turn_components_on(client, token, project_id) -> None:
    resp = client.put(
        f"/api/v1/projects/{project_id}/component-phases-settings", json={"mode": "on"}, headers=_headers(token),
    )
    assert resp.status_code == 200, resp.text


def _standard_phase_id(client, token, project_id, name) -> str:
    workflows = client.get(f"/api/v1/projects/{project_id}/stage-workflows", headers=_headers(token)).json()
    workflow = next(w for w in workflows if w["name"] == "Standard")
    return next(p["id"] for p in workflow["phases"] if p["name"] == name)


def _move_track(client, token, project_id, component_id, stage_id, phase) -> None:
    resp = client.post(
        f"/api/v1/projects/{project_id}/components/{component_id}/stages/{stage_id}/transition",
        json={"phase_id": _standard_phase_id(client, token, project_id, phase)}, headers=_headers(token),
    )
    assert resp.status_code == 200, resp.text


def test_the_stage_figure_counts_closed_as_done_and_leaves_on_hold_out(client, admin_token):
    org, project, token = _world(client, admin_token, "Health Stage Org")
    pid = project["id"]
    _add_stage(client, token, pid, "In review", "review")
    _add_stage(client, token, pid, "Approved", "approved")
    _add_stage(client, token, pid, "Completed", "completed")
    _add_stage(client, token, pid, "Archived", "archived")
    figure = _category(_get_health(client, token, pid), STAGE)
    assert (figure["label"], figure["kind"], figure["total"], figure["done"]) == ("Project stages", "completion", 4, 1)
    assert figure["percent"] == 25


def test_a_locked_stage_is_not_done(client, admin_token):
    org, project, token = _world(client, admin_token, "Health Stage Locked Org")
    pid = project["id"]
    _add_stage(client, token, pid, "Approved", "approved")
    figure = _category(_get_health(client, token, pid), STAGE)
    assert (figure["total"], figure["done"]) == (2, 0)


def test_component_phases_off_report_no_track_figure(client, admin_token):
    org, project, token = _world(client, admin_token, "Health Track Off Org")
    _add_component(client, token, project["id"], "SW")
    keys = {c["key"] for c in _get_health(client, token, project["id"])["categories"]}
    assert STAGE in keys and TRACK not in keys


def test_the_track_figure_counts_each_component_and_stage_and_leaves_out_not_applicable(client, admin_token):
    org, project, token = _world(client, admin_token, "Health Track On Org")
    pid = project["id"]
    first = _add_component(client, token, pid, "SW")
    second = _add_component(client, token, pid, "HW")
    stage_one = client.get(f"/api/v1/projects/{pid}/stages", headers=_headers(token)).json()[0]
    stage_two = _add_stage(client, token, pid, "Release 2")
    _turn_components_on(client, token, pid)

    untouched = _category(_get_health(client, token, pid), TRACK)
    assert (untouched["label"], untouched["total"], untouched["done"]) == ("Component phases", 4, 0)

    _move_track(client, token, pid, first["id"], stage_one["id"], "Completed")
    moved = _category(_get_health(client, token, pid), TRACK)
    assert (moved["total"], moved["done"], moved["percent"]) == (4, 1, 25)

    marked = client.patch(
        f"/api/v1/projects/{pid}/components/{second['id']}/stages/{stage_two['id']}/track",
        json={"not_applicable": True}, headers=_headers(token),
    )
    assert marked.status_code == 200, marked.text
    after = _category(_get_health(client, token, pid), TRACK)
    assert (after["total"], after["done"]) == (3, 1)


def test_a_track_on_hold_is_left_out(client, admin_token):
    org, project, token = _world(client, admin_token, "Health Track Hold Org")
    pid = project["id"]
    component = _add_component(client, token, pid, "SW")
    stage = client.get(f"/api/v1/projects/{pid}/stages", headers=_headers(token)).json()[0]
    _turn_components_on(client, token, pid)
    _move_track(client, token, pid, component["id"], stage["id"], "Archived")
    figure = _category(_get_health(client, token, pid), TRACK)
    assert (figure["total"], figure["done"]) == (0, 0) and figure["percent"] is None


def test_the_stage_figures_are_shown_to_a_member_who_may_read_no_record_type(client, admin_token, monkeypatch):
    org, project, token = _world(client, admin_token, "Health Stage Viewer Org")
    pid = project["id"]
    _add_component(client, token, pid, "SW")
    _turn_components_on(client, token, pid)
    monkeypatch.setattr(health, "readable_provider", lambda db, user, p, t, held=None: None)
    keys = {c["key"] for c in _get_health(client, token, pid)["categories"]}
    assert keys == {STAGE, TRACK}


def _statements(project_id: str) -> int:
    counted: list[int] = []

    def count(*_args) -> None:
        counted.append(1)

    with SessionLocal() as db:
        project = db.get(Project, uuid.UUID(project_id))
        assert project is not None
        event.listen(engine, "before_cursor_execute", count)
        try:
            health.compute_categories(db, project)
        finally:
            event.remove(engine, "before_cursor_execute", count)
    return len(counted)


def test_the_statement_count_does_not_grow_with_stages_or_components(client, admin_token):
    org, project, token = _world(client, admin_token, "Health Stage Flat Org")
    pid = project["id"]
    _add_component(client, token, pid, "C1")
    _turn_components_on(client, token, pid)
    _add_stage(client, token, pid, "Second")
    small = _statements(pid)
    for index in range(2, 7):
        _add_component(client, token, pid, f"C{index}")
        _add_stage(client, token, pid, f"Stage {index}", "review")
    assert _statements(pid) == small


def test_a_snapshot_stored_before_the_flag_existed_still_loads():
    old = {"categories": [{"key": "requirement", "label": "Requirements", "artefact_type": "requirement",
                           "kind": "completion", "total": 2, "done": 1}]}
    figures = health.figures_from_json(old)
    assert figures.categories[0].open_to_members is False
    stored = health.figures_to_json(health.Figures(categories=(
        health.CategoryFigure("project_stage", "Project stages", "project_stage", "completion", 1, 0, True),
    )))
    assert stored["categories"][0]["open_to_members"] is True
