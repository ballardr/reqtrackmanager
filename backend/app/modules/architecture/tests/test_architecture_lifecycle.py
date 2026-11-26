"""
Module: test_architecture_lifecycle

The status path of an element, a connection, a diagram and a state machine diagram on the lifecycle engine
(`modules.architecture.lifecycles`): each type is registered with `transitions.STATUS_MOVES` as its table, Proposed is the one
state a project may turn off, a move into a turned-off state is refused with the allowed states named, a record's offered
moves (`allowed_status_moves`) are what the endpoint accepts, and nothing changes while the project configures nothing
(pinned by `test_architecture_status_moves.py`).
"""

from __future__ import annotations

import pytest

from app.modules.architecture.lifecycles import LIFECYCLES
from app.modules.architecture.service import (
    CONNECTION_ARTEFACT_TYPE,
    DIAGRAM_ARTEFACT_TYPE,
    ELEMENT_ARTEFACT_TYPE,
    STATE_MACHINE_ARTEFACT_TYPE,
)
from app.modules.architecture.tests._helpers import make_connection, make_diagram, make_element, project_base, setup
from app.modules.architecture.transitions import STATUS_MOVES
from app.modules.registry import get_lifecycles
from app.services.lifecycles import validate_definition
from tests.conftest import auth_headers

TYPES = (ELEMENT_ARTEFACT_TYPE, CONNECTION_ARTEFACT_TYPE, DIAGRAM_ARTEFACT_TYPE, STATE_MACHINE_ARTEFACT_TYPE)


def test_every_status_carrying_type_is_registered_with_the_one_map():
    assert set(LIFECYCLES) == set(TYPES)
    registered = get_lifecycles()
    expected = {a.value: frozenset(b.value for b in moves) for a, moves in STATUS_MOVES.items()}
    for artefact_type in TYPES:
        module_key, definition = registered[artefact_type]
        assert module_key == "architecture"
        assert validate_definition(definition) == []
        assert dict(definition.transitions) == expected
        assert definition.optional == ("proposed",) and definition.gated == ()


def _turn_off_proposed(client, token, project_id, artefact_type: str) -> None:
    resp = client.put(
        f"/api/v1/projects/{project_id}/lifecycles/{artefact_type}", json={"disabled_states": ["proposed"]}, headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text


def _record(client, token, project_id, kind: str, name: str) -> dict:
    if kind == "elements":
        return make_element(client, token, project_id, name)
    if kind == "diagrams":
        return make_diagram(client, token, project_id, name)
    a, b = make_element(client, token, project_id, f"{name} A"), make_element(client, token, project_id, f"{name} B")
    return make_connection(client, token, project_id, a["id"], b["id"])


@pytest.mark.parametrize(
    ("kind", "artefact_type"),
    [("elements", ELEMENT_ARTEFACT_TYPE), ("connections", CONNECTION_ARTEFACT_TYPE), ("diagrams", DIAGRAM_ARTEFACT_TYPE)],
)
def test_a_state_the_project_turned_off_is_refused_and_not_offered(client, admin_token, kind, artefact_type):
    _org, project, token = setup(client, admin_token, f"Arch lifecycle {kind}")
    pid, base = project["id"], project_base(project["id"])
    record = _record(client, token, pid, kind, "Subject")
    assert record["allowed_status_moves"] == ["proposed", "active", "rejected"]

    _turn_off_proposed(client, token, pid, artefact_type)
    shown = client.get(f"{base}/{kind}/{record['id']}", headers=auth_headers(token)).json()
    assert shown["allowed_status_moves"] == ["active", "rejected"]
    assert next(r for r in client.get(f"{base}/{kind}", headers=auth_headers(token)).json() if r["id"] == record["id"])[
        "allowed_status_moves"
    ] == ["active", "rejected"]

    refused = client.post(
        f"{base}/{kind}/{record['id']}/status", json={"version": record["version"], "status": "proposed"}, headers=auth_headers(token),
    )
    assert refused.status_code == 409 and "turned off" in refused.json()["detail"]
    accepted = client.post(
        f"{base}/{kind}/{record['id']}/status", json={"version": record["version"], "status": "active"}, headers=auth_headers(token),
    )
    assert accepted.status_code == 200, accepted.text


def test_a_record_parked_in_a_state_that_is_later_turned_off_moves_on(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch lifecycle parked")
    pid, base = project["id"], project_base(project["id"])
    record = make_element(client, token, pid, "Parked")
    proposed = client.post(
        f"{base}/elements/{record['id']}/status", json={"version": record["version"], "status": "proposed"}, headers=auth_headers(token),
    ).json()
    _turn_off_proposed(client, token, pid, ELEMENT_ARTEFACT_TYPE)
    shown = client.get(f"{base}/elements/{record['id']}", headers=auth_headers(token)).json()
    assert shown["status"] == "proposed" and shown["allowed_status_moves"] == ["active", "draft", "rejected"]
    moved = client.post(
        f"{base}/elements/{record['id']}/status", json={"version": proposed["version"], "status": "active"}, headers=auth_headers(token),
    )
    assert moved.status_code == 200, moved.text


def test_an_organisation_requirement_stops_a_project_turning_proposed_off(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch lifecycle required")
    required = client.put(
        f"/api/v1/orgs/{org['id']}/lifecycles/{ELEMENT_ARTEFACT_TYPE}", json={"required_states": ["proposed"]}, headers=auth_headers(token),
    )
    assert required.status_code == 200, required.text
    record = make_element(client, token, project["id"], "Required")
    shown = client.get(f"{project_base(project['id'])}/elements/{record['id']}", headers=auth_headers(token)).json()
    assert shown["allowed_status_moves"] == ["proposed", "active", "rejected"]
