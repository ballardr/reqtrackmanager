"""Tests for the lifecycles of the core record types (`services.lifecycles_core`): the Requirement and the Change Request
are registered with the lifecycle engine, their transition tables equal the moves the endpoints allow (driven through the
real API), their step entry checks mirror the endpoints' rights, and the shipped project and organisation lifecycle
settings work for a core type (module key empty)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi import HTTPException

from app.database import SessionLocal
from app.models.project import Project
from app.models.user import User
from app.modules.registry import get_lifecycles
from app.services.lifecycles import effective_moves, enabled_for_organization, validate_definition
from app.services.lifecycles_core import CHANGE_REQUEST_TYPE, CORE_LIFECYCLES, REQUIREMENT_TYPE
from tests.conftest import (
    auth_headers,
    create_component_and_category,
    create_org_admin_in,
    create_org_user,
    create_project,
    login,
)


def _definition(artefact_type: str):
    return get_lifecycles()[artefact_type][1]


def _moves(artefact_type: str, current: str, disabled: tuple[str, ...] = ()) -> set[str]:
    return set(effective_moves(_definition(artefact_type), disabled, current))


# --- registration ---------------------------------------------------------------------------


def test_the_core_types_are_registered_without_a_module():
    for artefact_type in (REQUIREMENT_TYPE, CHANGE_REQUEST_TYPE):
        module_key, definition = get_lifecycles()[artefact_type]
        assert module_key == ""
        assert definition is CORE_LIFECYCLES[artefact_type]
        assert validate_definition(definition) == []


def test_the_requirement_path_has_one_optional_state_and_a_gated_approval():
    definition = _definition(REQUIREMENT_TYPE)
    assert definition.path == ("draft", "reviewed", "approved")
    assert definition.optional == ("reviewed",) and definition.gated == ("approved",)
    assert definition.labels["reviewed"] == "Reviewed"


def test_the_change_request_path_has_no_optional_state():
    definition = _definition(CHANGE_REQUEST_TYPE)
    assert definition.path == ("draft", "submitted", "approved")
    assert definition.optional == () and definition.gated == ("approved",)


def test_turning_reviewed_off_steps_a_draft_straight_to_approval():
    assert _moves(REQUIREMENT_TYPE, "draft") == {"reviewed", "approved", "archived"}
    assert _moves(REQUIREMENT_TYPE, "draft", ("reviewed",)) == {"approved", "archived"}
    assert effective_moves(_definition(REQUIREMENT_TYPE), ("reviewed",), "draft")["approved"] == ()


def test_a_core_type_is_enabled_for_every_organisation():
    db = SessionLocal()
    try:
        assert enabled_for_organization(db, uuid.uuid4(), REQUIREMENT_TYPE, "") is True
    finally:
        db.close()


# --- the tables equal the endpoints ---------------------------------------------------------


def _setup(client, admin_token, name):
    org, token = create_org_admin_in(client, admin_token, name)
    project = create_project(client, token, org["id"], f"{name} project")
    return org, project, token


def _new_requirement(client, token, project_id) -> str:
    component_id, category_id = create_component_and_category(client, token, project_id)
    resp = client.post(
        f"/api/v1/projects/{project_id}/requirements",
        json={"name": "Boot fast", "component_id": component_id, "category_id": category_id}, headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _edit_status(client, token, project_id, requirement_id, value):
    """A direct edit that sets the status and leaves the rest of the requirement as it is."""
    url = f"/api/v1/projects/{project_id}/requirements/{requirement_id}"
    current = client.get(url, headers=auth_headers(token)).json()
    owner = current["owner"]
    return client.put(
        url,
        json={
            "name": current["name"], "component_id": current["component_id"], "category_id": current["category_id"],
            "owner": {"type": owner["type"], "id": owner["id"]}, "status": value,
        },
        headers=auth_headers(token),
    )


def test_every_requirement_move_the_endpoints_make_is_in_the_table(client, admin_token):
    _, project, token = _setup(client, admin_token, "Core Lifecycle Requirement Co")
    pid = project["id"]
    requirement = _new_requirement(client, token, pid)

    def status() -> str:
        return client.get(f"/api/v1/projects/{pid}/requirements/{requirement}", headers=auth_headers(token)).json()["status"]

    observed: list[tuple[str, str]] = []
    for target in ("reviewed", "draft", "archived", "draft", "reviewed"):
        before = status()
        assert _edit_status(client, token, pid, requirement, target).status_code == 200
        assert status() == target
        observed.append((before, target))
    before = status()
    approved = client.post(f"/api/v1/projects/{pid}/requirements/{requirement}/approve", json={}, headers=auth_headers(token))
    assert approved.status_code == 200, approved.text
    observed.append((before, status()))

    assert observed[-1] == ("reviewed", "approved")
    for source, target in observed:
        assert target in _moves(REQUIREMENT_TYPE, source), (source, target)

    # Approved locks the requirement: no direct edit moves it, which the table states by giving it no way out.
    assert _edit_status(client, token, pid, requirement, "draft").status_code == 409
    assert _moves(REQUIREMENT_TYPE, "approved") == set()


def test_a_draft_can_be_approved_directly_as_the_table_says(client, admin_token):
    _, project, token = _setup(client, admin_token, "Core Lifecycle Direct Approval Co")
    requirement = _new_requirement(client, token, project["id"])
    approved = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{requirement}/approve", json={}, headers=auth_headers(token)
    )
    assert approved.status_code == 200, approved.text
    assert "approved" in _moves(REQUIREMENT_TYPE, "draft")


def _change_request(client, token, project_id, requirement_id, *, submit: bool) -> str:
    created = client.post(
        f"/api/v1/projects/{project_id}/change-requests",
        json={
            "kind": "modify_requirement", "requirement_id": requirement_id, "changed_fields": ["name"],
            "proposed_name": f"Renamed {uuid.uuid4().hex[:6]}", "reason": "Reason",
        },
        headers=auth_headers(token),
    )
    assert created.status_code == 201, created.text
    cr_id = created.json()["id"]
    if submit:
        sent = client.post(f"/api/v1/projects/{project_id}/change-requests/{cr_id}/submit", headers=auth_headers(token))
        assert sent.status_code == 200, sent.text
    return cr_id


def _cr_status(client, token, project_id, cr_id) -> str:
    return client.get(f"/api/v1/projects/{project_id}/change-requests/{cr_id}", headers=auth_headers(token)).json()["status"]


def test_every_change_request_move_the_endpoints_make_is_in_the_table(client, admin_token):
    _, project, token = _setup(client, admin_token, "Core Lifecycle CR Co")
    pid = project["id"]
    requirement = _new_requirement(client, token, pid)
    assert client.post(
        f"/api/v1/projects/{pid}/requirements/{requirement}/approve", json={}, headers=auth_headers(token)
    ).status_code == 200

    observed: list[tuple[str, str]] = []

    def decide(cr_id: str, approve: bool):
        return client.post(
            f"/api/v1/projects/{pid}/change-requests/{cr_id}/decide", json={"approve": approve, "note": "Decided"},
            headers=auth_headers(token),
        )

    drafted = _change_request(client, token, pid, requirement, submit=False)
    assert _cr_status(client, token, pid, drafted) == "draft"
    assert decide(drafted, True).status_code == 409  # a draft is never decided: no draft to approved move
    sent = client.post(f"/api/v1/projects/{pid}/change-requests/{drafted}/submit", headers=auth_headers(token))
    assert sent.status_code == 200
    observed.append(("draft", _cr_status(client, token, pid, drafted)))
    assert decide(drafted, True).status_code == 200
    observed.append(("submitted", _cr_status(client, token, pid, drafted)))

    rejected = _change_request(client, token, pid, requirement, submit=False)
    assert client.post(f"/api/v1/projects/{pid}/change-requests/{rejected}/submit", headers=auth_headers(token)).status_code == 200
    assert decide(rejected, False).status_code == 200
    observed.append(("submitted", _cr_status(client, token, pid, rejected)))

    withdrawn_draft = _change_request(client, token, pid, requirement, submit=False)
    assert client.post(f"/api/v1/projects/{pid}/change-requests/{withdrawn_draft}/withdraw", headers=auth_headers(token)).status_code == 200
    observed.append(("draft", _cr_status(client, token, pid, withdrawn_draft)))

    withdrawn_sent = _change_request(client, token, pid, requirement, submit=True)
    assert client.post(f"/api/v1/projects/{pid}/change-requests/{withdrawn_sent}/withdraw", headers=auth_headers(token)).status_code == 200
    observed.append(("submitted", _cr_status(client, token, pid, withdrawn_sent)))

    assert observed == [
        ("draft", "submitted"), ("submitted", "approved"), ("submitted", "rejected"), ("draft", "withdrawn"),
        ("submitted", "withdrawn"),
    ]
    for source, target in observed:
        assert target in _moves(CHANGE_REQUEST_TYPE, source), (source, target)
    # A decided request is final: the table gives each decided state no way out, as the endpoints refuse a second decision.
    assert decide(drafted, False).status_code == 409
    assert all(_moves(CHANGE_REQUEST_TYPE, final) == set() for final in ("approved", "rejected", "withdrawn"))
    assert "draft" not in {t for state in ("draft", "submitted", "in_review") for t in _moves(CHANGE_REQUEST_TYPE, state)}


def test_a_request_in_review_can_still_be_decided_or_withdrawn():
    assert _moves(CHANGE_REQUEST_TYPE, "in_review") == {"approved", "rejected", "withdrawn"}


# --- the step entry checks ------------------------------------------------------------------


def _entry(artefact_type: str, user_id: str, project_id: str, record_id: str, state: str) -> None:
    db = SessionLocal()
    try:
        user = db.get(User, uuid.UUID(user_id))
        project = db.get(Project, uuid.UUID(project_id))
        assert user is not None and project is not None
        guard: Any = _definition(artefact_type).entry_guard
        guard(db, user, project, uuid.UUID(record_id), state)
    finally:
        db.close()


def _user_id(client, token) -> str:
    return client.get("/api/v1/auth/me", headers=auth_headers(token)).json()["id"]


def test_the_step_checks_mirror_the_endpoints_rights(client, admin_token):
    org, project, token = _setup(client, admin_token, "Core Lifecycle Guard Co")
    manager = _user_id(client, token)
    create_org_user(client, token, org["id"], "core_lifecycle_outsider@example.com")
    outsider = _user_id(client, login(client, "core_lifecycle_outsider@example.com", "Password123!"))
    requirement = _new_requirement(client, token, project["id"])

    _entry(REQUIREMENT_TYPE, manager, project["id"], requirement, "approved")
    _entry(REQUIREMENT_TYPE, manager, project["id"], requirement, "reviewed")
    for state in ("approved", "reviewed"):
        with pytest.raises(HTTPException) as refused:
            _entry(REQUIREMENT_TYPE, outsider, project["id"], requirement, state)
        assert refused.value.status_code == 403

    assert client.post(
        f"/api/v1/projects/{project['id']}/requirements/{requirement}/approve", json={}, headers=auth_headers(token)
    ).status_code == 200
    cr = _change_request(client, token, project["id"], requirement, submit=False)
    _entry(CHANGE_REQUEST_TYPE, manager, project["id"], cr, "submitted")
    _entry(CHANGE_REQUEST_TYPE, manager, project["id"], cr, "approved")
    for state in ("submitted", "approved"):
        with pytest.raises(HTTPException) as refused:
            _entry(CHANGE_REQUEST_TYPE, outsider, project["id"], cr, state)
        assert refused.value.status_code == 403


# --- the shipped settings work for a core type ----------------------------------------------


def _lifecycles(client, token, project_id) -> dict:
    resp = client.get(f"/api/v1/projects/{project_id}/lifecycles", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_the_project_view_lists_the_core_types_without_a_module(client, admin_token):
    _, project, token = _setup(client, admin_token, "Core Lifecycle View Co")
    listed = {x["artefact_type"]: x for x in _lifecycles(client, token, project["id"])["lifecycles"]}
    requirement, change_request = listed["requirement"], listed["change_request"]
    assert requirement["module_key"] == "" and requirement["module_name"] == ""
    assert [s["key"] for s in requirement["path"]] == ["draft", "reviewed", "approved"]
    assert [s["key"] for s in requirement["path"] if s["optional"]] == ["reviewed"]
    assert [s["key"] for s in requirement["path"] if s["gated"]] == ["approved"]
    assert {s["key"] for s in requirement["off_path"]} == {"archived"}
    assert requirement["transitions"]["draft"] == ["reviewed", "approved", "archived"]
    assert requirement["required_by_profiles"] == {}
    assert [s["key"] for s in change_request["path"] if s["optional"]] == []
    assert {s["key"] for s in change_request["off_path"]} == {"in_review", "rejected", "withdrawn"}


def test_a_project_turns_reviewed_off_and_the_organisation_can_require_it(client, admin_token):
    org, project, token = _setup(client, admin_token, "Core Lifecycle Settings Co")
    url = f"/api/v1/projects/{project['id']}/lifecycles/requirement"
    off = client.put(url, json={"disabled_states": ["reviewed"]}, headers=auth_headers(token))
    assert off.status_code == 200, off.text
    shown = next(x for x in off.json()["lifecycles"] if x["artefact_type"] == "requirement")
    assert shown["disabled"] == ["reviewed"] and shown["transitions"]["draft"] == ["approved", "archived"]

    assert client.put(url, json={"disabled_states": ["approved"]}, headers=auth_headers(token)).status_code == 422
    required = client.put(
        f"/api/v1/orgs/{org['id']}/lifecycles/requirement", json={"required_states": ["reviewed"]}, headers=auth_headers(token)
    )
    assert required.status_code == 200, required.text
    assert [x["artefact_type"] for x in required.json()] == ["component_stage", "project_stage", "requirement"]
    shown = next(x for x in _lifecycles(client, token, project["id"])["lifecycles"] if x["artefact_type"] == "requirement")
    assert shown["required"] == ["reviewed"] and shown["disabled"] == []

    exempt = client.post(
        f"/api/v1/orgs/{org['id']}/lifecycles/requirement/exemptions", json={"project_id": project["id"]},
        headers=auth_headers(token),
    )
    assert exempt.status_code == 200, exempt.text
    shown = next(x for x in _lifecycles(client, token, project["id"])["lifecycles"] if x["artefact_type"] == "requirement")
    assert shown["exempt"] is True and shown["disabled"] == ["reviewed"]


def test_a_change_request_has_nothing_to_configure(client, admin_token):
    org, project, token = _setup(client, admin_token, "Core Lifecycle CR Settings Co")
    url = f"/api/v1/projects/{project['id']}/lifecycles/change_request"
    assert client.put(url, json={"disabled_states": ["submitted"]}, headers=auth_headers(token)).status_code == 422
    listed = client.get(f"/api/v1/orgs/{org['id']}/lifecycles", headers=auth_headers(token)).json()
    assert "change_request" not in {x["artefact_type"] for x in listed}
