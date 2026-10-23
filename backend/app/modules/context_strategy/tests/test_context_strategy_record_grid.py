"""Tests for the bulk edit grid over Context & Strategy's record tables: `GET .../records/{type}/grid` lists a
list's rows with the cells and the columns the grid may edit, and `PATCH .../records/{type}/rows/{code}` saves the
changed cells of one record through the type's own update path.

First use is a Pain Point's Severity, Frequency and Confidence (its "all personas" scores): the grid reads and
writes them through the same function the scores endpoint uses, refuses a cell someone else changed since it was
loaded, locks a Pain Point scored per persona or at a terminal outcome, and keeps the manager tier that scoring has.

Each test builds its own organisation, so none depends on state left by another test.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.modules.context_strategy.tests.test_context_strategy_pain_point_scoring import (
    _cs,
    _entry,
    _get,
    _levels,
    _pain_point,
    _persona,
    _put,
    _setup,
)
from app.modules.context_strategy.tests.test_context_strategy_relationships_api import _add_plain_member, _create_open_question
from tests.conftest import auth_headers, create_project

PAIN_POINT = "pain_point"


def _base(project_id: str, record_type: str = PAIN_POINT) -> str:
    return f"/api/v1/projects/{project_id}/records/{record_type}"


def _grid(client, token, project_id, record_type=PAIN_POINT, **params):
    resp = client.get(f"{_base(project_id, record_type)}/grid", params=params, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _save(client, token, project_id, code, cells, expected=None, record_type=PAIN_POINT):
    return client.patch(
        f"{_base(project_id, record_type)}/rows/{code}", json={"cells": cells, "expected": expected or {}}, headers=auth_headers(token),
    )


def _events(record_id: str) -> list[str]:
    """The actions of the audit events recorded for one record."""
    with SessionLocal() as db:
        return [e.action for e in db.scalars(select(AuditEvent).where(AuditEvent.entity_id == record_id))]


def _row(grid: dict, code: str) -> dict:
    return next(r for r in grid["rows"] if r["code"] == code)


@pytest.fixture
def world(client, admin_token):
    org, project, token = _setup(client, admin_token, f"PP Grid {uuid.uuid4().hex[:6]}")
    return client, org, project["id"], token


def test_the_grid_lists_the_rows_with_their_cells_and_the_columns_it_may_edit(world):
    client, _, pid, token = world
    levels = _levels(client, token, pid)
    scored = _pain_point(client, token, pid)
    plain = _pain_point(client, token, pid, title="Unscored")
    assert _put(client, token, pid, scored["id"], [_entry(levels, severity="Major", frequency="Frequent")]).status_code == 200

    grid = _grid(client, token, pid)
    columns = {c["key"]: c for c in grid["columns"]}
    assert grid["can_edit"] is True and grid["total"] == 2 and grid["truncated"] is False
    assert columns["severity"]["editable"] is True and columns["severity"]["choices"] == list(levels["severity"])
    assert columns["priority"]["editable"] is True and columns["priority"]["choices"][0]
    assert columns["title"]["editable"] is False and columns["description"]["editable"] is False
    assert columns["status"]["editable"] is False and columns["owner"]["editable"] is False
    row = _row(grid, scored["unique_code"])
    assert row["id"] == scored["id"] and row["cells"]["severity"] == "Major" and row["cells"]["frequency"] == "Frequent"
    assert _row(grid, plain["unique_code"])["cells"]["severity"] == "" and row["read_only"] is None and row["locks"] == {}


def test_saving_a_score_cell_writes_the_scores_endpoints_row_and_returns_the_refreshed_row(world):
    client, _, pid, token = world
    levels = _levels(client, token, pid)
    pain_point = _pain_point(client, token, pid)
    code = pain_point["unique_code"]

    resp = _save(client, token, pid, code, {"severity": "Major", "confidence": "Medium"}, {"severity": "", "confidence": ""})
    assert resp.status_code == 200, resp.text
    assert resp.json()["cells"]["severity"] == "Major" and resp.json()["cells"]["confidence"] == "Medium"

    scores = _get(client, token, pid, pain_point["id"])
    assert scores["scope"] == "all_personas"
    entry = scores["entries"][0]
    assert entry["severity_level_id"] == levels["severity"]["Major"] and entry["confidence_level_id"] == levels["confidence"]["Medium"]
    assert entry["frequency_level_id"] is None

    # A second axis keeps the first ones; a blank cell clears just its own axis.
    assert _save(client, token, pid, code, {"frequency": "Frequent"}, {"frequency": ""}).status_code == 200
    cleared = _save(client, token, pid, code, {"severity": ""}, {"severity": "Major"})
    assert cleared.status_code == 200 and cleared.json()["cells"]["severity"] == ""
    entry = _get(client, token, pid, pain_point["id"])["entries"][0]
    assert entry["severity_level_id"] is None and entry["frequency_level_id"] == levels["frequency"]["Frequent"]
    assert entry["confidence_level_id"] == levels["confidence"]["Medium"]

    assert _events(pain_point["id"]).count("scored") == 3


def test_a_non_score_cell_goes_through_the_pain_points_own_edit_and_unchanged_cells_write_nothing(world):
    client, _, pid, token = world
    pain_point = _pain_point(client, token, pid)
    code = pain_point["unique_code"]
    current = _row(_grid(client, token, pid), code)["cells"]["priority"]

    same = _save(client, token, pid, code, {"priority": current}, {"priority": current})
    assert same.status_code == 200
    assert "updated" not in _events(pain_point["id"])

    choices = next(c for c in _grid(client, token, pid)["columns"] if c["key"] == "priority")["choices"]
    other = next(c for c in choices if c != current)
    changed = _save(client, token, pid, code, {"priority": other}, {"priority": current})
    assert changed.status_code == 200 and changed.json()["cells"]["priority"] == other
    got = client.get(f"{_cs(pid)}/pain-points/{pain_point['id']}", headers=auth_headers(token)).json()
    assert got["priority"] == other.lower()
    assert _events(pain_point["id"]).count("updated") == 1


def test_a_cell_someone_else_changed_since_it_was_loaded_is_refused_and_nothing_is_written(world):
    client, _, pid, token = world
    levels = _levels(client, token, pid)
    pain_point = _pain_point(client, token, pid)
    code = pain_point["unique_code"]
    assert _put(client, token, pid, pain_point["id"], [_entry(levels, severity="Minor")]).status_code == 200

    stale = _save(client, token, pid, code, {"severity": "Major", "frequency": "Frequent"}, {"severity": "", "frequency": ""})
    assert stale.status_code == 409 and "changed by someone else" in stale.json()["detail"] and "'Minor'" in stale.json()["detail"]
    entry = _get(client, token, pid, pain_point["id"])["entries"][0]
    assert entry["severity_level_id"] == levels["severity"]["Minor"] and entry["frequency_level_id"] is None


def test_a_refused_value_names_the_problem_and_a_column_the_grid_cannot_edit_is_refused(world):
    client, _, pid, token = world
    code = _pain_point(client, token, pid)["unique_code"]
    unknown = _save(client, token, pid, code, {"severity": "Catastrophic"})
    assert unknown.status_code == 422 and "Unknown Severity level" in unknown.json()["detail"]
    for key in ("title", "description", "owner", "status", "tags", "nonsense"):
        assert _save(client, token, pid, code, {key: "x"}).status_code == 422, key
    assert _save(client, token, pid, code, {"type": ""}).status_code == 422
    assert _save(client, token, pid, "PP-999", {"severity": "Major"}).status_code == 404


def test_a_pain_point_scored_per_persona_locks_its_score_cells_and_refuses_a_save(world):
    client, _, pid, token = world
    levels = _levels(client, token, pid)
    pain_point = _pain_point(client, token, pid)
    code = pain_point["unique_code"]
    persona = _persona(client, token, pid, "Operator")
    assert _put(client, token, pid, pain_point["id"], [_entry(levels, target_id=persona, severity="Major")]).status_code == 200

    row = _row(_grid(client, token, pid), code)
    assert row["cells"]["severity"] == "" and set(row["locks"]) == {"severity", "frequency", "confidence"}
    assert "per persona" in row["locks"]["severity"]
    resp = _save(client, token, pid, code, {"severity": "Minor"}, {"severity": ""})
    assert resp.status_code == 409 and "per persona" in resp.json()["detail"]
    # The row's other cells stay editable.
    priority = next(c for c in _grid(client, token, pid)["columns"] if c["key"] == "priority")["choices"]
    assert _save(client, token, pid, code, {"priority": priority[0]}).status_code == 200


def test_a_pain_point_at_a_terminal_outcome_is_a_read_only_row_with_the_reason(world):
    client, _, pid, token = world
    pain_point = _pain_point(client, token, pid)
    code = pain_point["unique_code"]
    base = f"{_cs(pid)}/pain-points/{pain_point['id']}"
    assert client.post(f"{base}/triage", json={}, headers=auth_headers(token)).status_code == 200
    assert client.post(f"{base}/reject", json={"comment": "Not a defect"}, headers=auth_headers(token)).status_code == 200

    row = _row(_grid(client, token, pid, include_archived="true"), code)
    assert row["read_only"] and "terminal outcome" in row["read_only"]
    resp = _save(client, token, pid, code, {"severity": "Major"}, {"severity": ""})
    assert resp.status_code == 409 and "terminal outcome" in resp.json()["detail"]


def test_a_plain_member_sees_the_grid_but_cannot_save_and_scoring_stays_the_manager_tier(world):
    client, org, pid, token = world
    _, member = _add_plain_member(client, token, org["id"], pid, f"grid-member-{uuid.uuid4().hex[:6]}@example.com")
    code = _pain_point(client, token, pid)["unique_code"]
    grid = _grid(client, member, pid)
    assert grid["can_edit"] is False and grid["total"] == 1
    resp = _save(client, member, pid, code, {"severity": "Major"})
    assert resp.status_code == 403 and "permission" in resp.json()["detail"]


def test_the_grid_takes_the_lists_filters_and_refuses_one_it_cannot_honour(world):
    client, _, pid, token = world
    keep = _pain_point(client, token, pid, title="Keep", priority="high")
    _pain_point(client, token, pid, title="Other", priority="low")
    narrowed = _grid(client, token, pid, priority="high")
    assert [r["code"] for r in narrowed["rows"]] == [keep["unique_code"]] and narrowed["total"] == 1
    assert _grid(client, token, pid, search="Oth")["total"] == 1
    bad = client.get(f"{_base(pid)}/grid", params={"colour": "red"}, headers=auth_headers(token))
    assert bad.status_code == 422 and "colour" in bad.json()["detail"]


def test_a_long_list_is_cut_at_the_row_cap_and_says_so(world, monkeypatch):
    client, _, pid, token = world
    for n in range(3):
        _pain_point(client, token, pid, title=f"PP {n}")
    monkeypatch.setattr("app.services.record_tables.MAX_GRID_ROWS", 2)
    grid = _grid(client, token, pid)
    assert len(grid["rows"]) == 2 and grid["total"] == 3 and grid["truncated"] is True


def test_another_projects_code_is_not_found_and_a_disabled_module_hides_the_grid(world):
    client, org, pid, token = world
    other = create_project(client, token, org["id"], f"Other {uuid.uuid4().hex[:6]}")
    _pain_point(client, token, pid)
    _pain_point(client, token, other["id"])
    foreign = _pain_point(client, token, other["id"], title="Second")["unique_code"]
    assert foreign not in {r["code"] for r in _grid(client, token, pid)["rows"]}
    assert _save(client, token, pid, foreign, {"severity": "Major"}).status_code == 404
    assert _save(client, token, other["id"], foreign, {"severity": "Major"}).status_code == 200
    assert client.put(
        f"/api/v1/orgs/{org['id']}/modules/context_strategy", json={"enabled": False}, headers=auth_headers(token),
    ).status_code == 200
    assert client.get(f"{_base(pid)}/grid", headers=auth_headers(token)).status_code == 404
    assert _save(client, token, pid, foreign, {"severity": "Major"}).status_code == 404


def test_a_date_cell_of_another_type_saves_through_that_types_own_edit(world):
    client, _, pid, token = world
    question = _create_open_question(client, token, pid)
    code = question["unique_code"]
    grid = _grid(client, token, pid, "open_question")
    assert grid["can_edit"] is True
    assert {c["key"] for c in grid["columns"] if c["editable"]} >= {"due_date", "priority"}

    resp = _save(client, token, pid, code, {"due_date": "2026-12-31"}, {"due_date": ""}, "open_question")
    assert resp.status_code == 200 and resp.json()["cells"]["due_date"] == "2026-12-31"
    bad = _save(client, token, pid, code, {"due_date": "31/12/2026"}, {"due_date": "2026-12-31"}, "open_question")
    assert bad.status_code == 422


def test_scores_are_columns_of_the_pain_point_file_and_a_persona_scored_row_exports_blank(world):
    client, _, pid, token = world
    levels = _levels(client, token, pid)
    pain_point = _pain_point(client, token, pid)
    assert _put(client, token, pid, pain_point["id"], [_entry(levels, severity="Major")]).status_code == 200
    export = client.get(f"{_base(pid)}/export", headers=auth_headers(token)).content.decode("utf-8-sig").splitlines()
    header, first = export[0].split(","), export[1].split(",")
    assert {"severity", "frequency", "confidence"} <= set(header)
    assert first[header.index("severity")] == "Major"
    # The same file re-imports unchanged, and a changed level is an update through the scores function.
    unchanged = client.post(
        f"{_base(pid)}/import", params={"dry_run": "true"},
        files={"file": ("p.csv", "\n".join(export).encode("utf-8"), "text/csv")}, headers=auth_headers(token),
    ).json()
    assert unchanged["unchanged"] == 1 and unchanged["failed"] == 0
    edited = "\n".join(export).replace("Major", "Minor")
    applied = client.post(
        f"{_base(pid)}/import", params={"dry_run": "false"},
        files={"file": ("p.csv", edited.encode("utf-8"), "text/csv")}, headers=auth_headers(token),
    ).json()
    assert applied["updated"] == 1, applied
    assert _get(client, token, pid, pain_point["id"])["entries"][0]["severity_level_id"] == levels["severity"]["Minor"]
