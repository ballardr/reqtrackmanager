"""
Module: test_architecture_status_moves

Pins the one status transition map (`transitions.STATUS_MOVES`): the moves the server accepts and refuses for an
element, a connection and a diagram, the `allowed_status_moves` returned with each record (so the "Change state" menu
offers exactly what the server accepts), the `planned` label, and the retire rule for children that are only planned.
"""

from __future__ import annotations

import pytest

from app.modules.architecture.enums import RecordStatus
from app.modules.architecture.labels import RECORD_STATUS_LABEL
from app.modules.architecture.tests._helpers import make_connection, make_diagram, make_element, project_base, setup
from app.modules.architecture.transitions import STATUS_MOVES, allowed_moves, move_refusal
from tests.conftest import auth_headers

#: Every ordered pair of states, split by whether the map allows it.
_ALL = [(a, b) for a in RecordStatus for b in RecordStatus if a is not b]
_ALLOWED = [(a, b) for a in RecordStatus for b in STATUS_MOVES[a]]
_REFUSED = [pair for pair in _ALL if pair not in _ALLOWED]


def _ids(pairs):
    return [f"{a.value}->{b.value}" for a, b in pairs]


def test_the_map_is_the_agreed_one_and_every_state_has_a_label():
    assert {a.value: [b.value for b in moves] for a, moves in STATUS_MOVES.items()} == {
        "draft": ["planned", "active"], "planned": ["active", "draft"], "active": ["retired"], "retired": ["active"],
    }
    assert set(RECORD_STATUS_LABEL) == {s.value for s in RecordStatus}
    assert RECORD_STATUS_LABEL["planned"] == "Planned"
    assert allowed_moves("nonsense") == []
    assert move_refusal("draft", RecordStatus.DRAFT) == "The record already has this status."


def _get_to(client, token, project_id, kind, status):
    """A fresh record of `kind` ("elements", "connections" or "diagrams") brought to `status` along allowed moves."""
    base = project_base(project_id)
    n = len(client.get(f"{base}/{kind}", headers=auth_headers(token)).json())
    if kind == "elements":
        record = make_element(client, token, project_id, f"E{n}")
    elif kind == "diagrams":
        record = make_diagram(client, token, project_id, f"D{n}")
    else:
        a, b = make_element(client, token, project_id, f"A{n}"), make_element(client, token, project_id, f"B{n}")
        record = make_connection(client, token, project_id, a["id"], b["id"])
    path = {RecordStatus.DRAFT: [], RecordStatus.PLANNED: ["planned"], RecordStatus.ACTIVE: ["active"],
            RecordStatus.RETIRED: ["active", "retired"]}[status]
    for step in path:
        resp = client.post(f"{base}/{kind}/{record['id']}/status", json={"version": record["version"], "status": step},
                           headers=auth_headers(token))
        assert resp.status_code == 200, resp.text
        record = resp.json()
    assert record["status"] == status.value
    return record


@pytest.mark.parametrize("kind", ["elements", "connections", "diagrams"])
def test_every_record_returns_the_moves_the_server_accepts(client, admin_token, kind):
    _org, project, token = setup(client, admin_token, f"Arch status moves {kind}")
    base = project_base(project["id"])
    for current in RecordStatus:
        record = _get_to(client, token, project["id"], kind, current)
        assert record["allowed_status_moves"] == [m.value for m in STATUS_MOVES[current]]
        listed = {r["id"]: r for r in client.get(f"{base}/{kind}", headers=auth_headers(token)).json()}
        assert listed[record["id"]]["allowed_status_moves"] == record["allowed_status_moves"]


@pytest.mark.parametrize(("current", "target"), _ALLOWED, ids=_ids(_ALLOWED))
@pytest.mark.parametrize("kind", ["elements", "connections", "diagrams"])
def test_an_allowed_move_is_accepted(client, admin_token, kind, current, target):
    _org, project, token = setup(client, admin_token, f"Arch allowed {kind} {current.value} {target.value}")
    record = _get_to(client, token, project["id"], kind, current)
    resp = client.post(f"{project_base(project['id'])}/{kind}/{record['id']}/status",
                       json={"version": record["version"], "status": target.value}, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == target.value


@pytest.mark.parametrize(("current", "target"), _REFUSED, ids=_ids(_REFUSED))
@pytest.mark.parametrize("kind", ["elements", "connections", "diagrams"])
def test_a_move_outside_the_map_is_refused_and_leaves_the_record_alone(client, admin_token, kind, current, target):
    _org, project, token = setup(client, admin_token, f"Arch refused {kind} {current.value} {target.value}")
    record = _get_to(client, token, project["id"], kind, current)
    base = project_base(project["id"])
    resp = client.post(f"{base}/{kind}/{record['id']}/status",
                       json={"version": record["version"], "status": target.value}, headers=auth_headers(token))
    assert resp.status_code == 409, resp.text
    after = client.get(f"{base}/{kind}/{record['id']}", headers=auth_headers(token)).json()
    assert (after["status"], after["version"]) == (current.value, record["version"])


def test_a_planned_child_still_blocks_retiring_its_parent(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch planned child")
    h, base = auth_headers(token), project_base(project["id"])
    parent = make_element(client, token, project["id"], "Parent", activate=True)
    child = make_element(client, token, project["id"], "Child", parent_id=parent["id"])
    client.post(f"{base}/elements/{child['id']}/status", json={"version": child["version"], "status": "planned"}, headers=h)
    blocked = client.post(f"{base}/elements/{parent['id']}/status", json={"version": parent["version"], "status": "retired"}, headers=h)
    assert blocked.status_code == 409


def test_a_planned_row_in_an_import_is_created_planned(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch planned import")
    h = auth_headers(token)
    type_name = client.get(f"{project_base(project['id'])}/element-types", headers=h).json()[0]["name"]
    csv_text = f"code,name,type,status\n,Planned part,{type_name},Planned\n"
    resp = client.post(
        f"/api/v1/projects/{project['id']}/records/architecture_element/import", params={"dry_run": "false"},
        files={"file": ("elements.csv", csv_text.encode("utf-8"), "text/csv")}, headers=h,
    )
    assert resp.status_code == 200, resp.text
    listed = client.get(f"{project_base(project['id'])}/elements", headers=h).json()
    assert [(e["name"], e["status"]) for e in listed] == [("Planned part", "planned")]
