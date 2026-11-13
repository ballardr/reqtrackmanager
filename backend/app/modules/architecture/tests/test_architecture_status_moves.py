"""
Module: test_architecture_status_moves

Pins the one status transition map (`transitions.STATUS_MOVES`): the moves the server accepts and refuses for an
element, a connection and a diagram, the `allowed_status_moves` returned with each record (so the "Change state" menu
offers exactly what the server accepts), the `proposed` and `rejected` labels, and how a rejected record is treated as out of use.
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
        "draft": ["proposed", "active", "rejected"], "proposed": ["active", "draft", "rejected"], "active": ["retired"],
        "retired": ["active"], "rejected": ["draft"],
    }
    assert set(RECORD_STATUS_LABEL) == {s.value for s in RecordStatus}
    assert RECORD_STATUS_LABEL["proposed"] == "Proposed"
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
    path = {RecordStatus.DRAFT: [], RecordStatus.PROPOSED: ["proposed"], RecordStatus.ACTIVE: ["active"],
            RecordStatus.RETIRED: ["active", "retired"], RecordStatus.REJECTED: ["rejected"]}[status]
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


def test_a_proposed_child_still_blocks_retiring_its_parent(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch proposed child")
    h, base = auth_headers(token), project_base(project["id"])
    parent = make_element(client, token, project["id"], "Parent", activate=True)
    child = make_element(client, token, project["id"], "Child", parent_id=parent["id"])
    client.post(f"{base}/elements/{child['id']}/status", json={"version": child["version"], "status": "proposed"}, headers=h)
    blocked = client.post(f"{base}/elements/{parent['id']}/status", json={"version": parent["version"], "status": "retired"}, headers=h)
    assert blocked.status_code == 409


def test_a_proposed_row_in_an_import_is_created_proposed(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch proposed import")
    h = auth_headers(token)
    type_name = client.get(f"{project_base(project['id'])}/element-types", headers=h).json()[0]["name"]
    csv_text = f"code,name,type,status\n,Proposed part,{type_name},Proposed\n"
    resp = client.post(
        f"/api/v1/projects/{project['id']}/records/architecture_element/import", params={"dry_run": "false"},
        files={"file": ("elements.csv", csv_text.encode("utf-8"), "text/csv")}, headers=h,
    )
    assert resp.status_code == 200, resp.text
    listed = client.get(f"{project_base(project['id'])}/elements", headers=h).json()
    assert [(e["name"], e["status"]) for e in listed] == [("Proposed part", "proposed")]


def test_a_rejected_element_is_out_of_use_like_a_retired_one(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch rejected element")
    h, base = auth_headers(token), project_base(project["id"])
    parent = make_element(client, token, project["id"], "Parent", activate=True)
    child = make_element(client, token, project["id"], "Child", parent_id=parent["id"])
    make_element(client, token, project["id"], "Other", activate=True)

    rejected = client.post(f"{base}/elements/{child['id']}/status", json={"version": child["version"], "status": "rejected"}, headers=h)
    assert rejected.status_code == 200 and rejected.json()["allowed_status_moves"] == ["draft"]
    names = lambda **p: {e["name"] for e in client.get(f"{base}/elements", params=p, headers=h).json()}  # noqa: E731
    assert names(open_only="true") == {"Parent", "Other"} and names(status="rejected") == {"Child"}
    # A rejected child no longer blocks retiring its parent.
    retire = {"version": parent["version"], "status": "retired"}
    assert client.post(f"{base}/elements/{parent['id']}/status", json=retire, headers=h).status_code == 200
    reopened = client.post(f"{base}/elements/{child['id']}/status", json={"version": rejected.json()["version"], "status": "draft"}, headers=h)
    assert reopened.status_code == 200 and reopened.json()["status"] == "draft"


def test_a_rejected_connection_and_diagram_are_left_out_of_open_lists(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch rejected others")
    h, base = auth_headers(token), project_base(project["id"])
    a, b = make_element(client, token, project["id"], "A"), make_element(client, token, project["id"], "B")
    link = make_connection(client, token, project["id"], a["id"], b["id"])
    diagram = make_diagram(client, token, project["id"], "Idea")
    for kind, record in (("connections", link), ("diagrams", diagram)):
        assert client.post(f"{base}/{kind}/{record['id']}/status", json={"version": 1, "status": "rejected"}, headers=h).status_code == 200
        assert client.get(f"{base}/{kind}", params={"open_only": "true"}, headers=h).json() == []
        assert len(client.get(f"{base}/{kind}", params={"status": "rejected"}, headers=h).json()) == 1


def test_a_new_record_cannot_be_imported_as_rejected(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch rejected import")
    h = auth_headers(token)
    type_name = client.get(f"{project_base(project['id'])}/element-types", headers=h).json()[0]["name"]
    csv_text = f"code,name,type,status\n,Idea,{type_name},Rejected\n"
    resp = client.post(
        f"/api/v1/projects/{project['id']}/records/architecture_element/import", params={"dry_run": "false"},
        files={"file": ("elements.csv", csv_text.encode("utf-8"), "text/csv")}, headers=h,
    )
    assert resp.status_code == 200, resp.text
    assert client.get(f"{project_base(project['id'])}/elements", headers=h).json() == []
