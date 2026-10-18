"""Tests for the per-record activity timeline (`GET /projects/{pid}/artefacts/{type}/{id}/activity`),
`services.record_activity`, and the audit-convention coverage it relies on: every registered artefact
type writes its audit events under its own type name, so a new type shows its history with no
registration.

Each test builds its own organisation (`tests.link_world.World`), so none depends on state left by
another test or run.
"""

from __future__ import annotations

import ast
import pathlib
import uuid

import pytest

from app.modules.registry import get_all_registered_artefact_types
from app.services.record_activity import _scrub
from tests.conftest import auth_headers, create_org_admin_in
from tests.link_world import ACTION, REQ, World

PAIN = "pain_point"


@pytest.fixture
def world(client, admin_token) -> World:
    return World(client, admin_token, "Activity Org", context_strategy=True)


def _activity(world: World, project: dict, artefact: tuple[str, uuid.UUID], token=None, **params):
    return world.client.get(
        f"/api/v1/projects/{project['id']}/artefacts/{artefact[0]}/{artefact[1]}/activity", params=params,
        headers=auth_headers(token or world.token),
    )


def _rename(world: World, project: dict, requirement: uuid.UUID, name: str) -> None:
    """Edits a requirement directly (a new version)."""
    me = world.client.get("/api/v1/auth/me", headers=auth_headers(world.token)).json()
    resp = world.client.put(
        f"/api/v1/projects/{project['id']}/requirements/{requirement}",
        json={
            "name": name, "component_id": project["component_id"], "category_id": project["category_id"],
            "owner": {"type": "user", "id": me["id"]}, "change_note": f"to {name}",
        },
        headers=auth_headers(world.token),
    )
    assert resp.status_code == 200, resp.text


def _actions(resp) -> list[str]:
    assert resp.status_code == 200, resp.text
    return [e["action"] for e in resp.json()["entries"]]


def test_requirement_activity_has_versions_and_actor_and_only_its_own_events(world):
    project = world.project()
    requirement = world.requirement(project, "First")
    other = world.requirement(project, "Second")
    _rename(world, project, requirement, "First renamed")

    body = _activity(world, project, (REQ, requirement)).json()
    actions = [e["action"] for e in body["entries"]]
    assert "created" in actions and "updated" in actions
    assert all(e["entity_id"] == str(requirement) for e in body["entries"])
    assert all(e["actor_display_name"] for e in body["entries"])
    assert body["has_more"] is False
    assert not any(e["entity_id"] == str(other) for e in body["entries"])


def test_action_and_module_record_events_use_the_artefact_type_name(world):
    project = world.project()
    action = world.action(project)
    pain = world.pain_point(project)

    assert "created" in _actions(_activity(world, project, (ACTION, action)))
    assert "created" in _actions(_activity(world, project, (PAIN, pain)))


def test_module_comment_edit_and_attachment_removal_are_audited(world):
    """Comment edits used to leave no audit event on Context & Strategy and Decisions records."""
    project = world.project()
    pain = world.pain_point(project)
    base = f"/api/v1/projects/{project['id']}/modules/context_strategy/pain-points/{pain}"
    comment = world.client.post(f"{base}/comments", json={"body": "one"}, headers=auth_headers(world.token)).json()
    resp = world.client.patch(
        f"{base}/comments/{comment['id']}", json={"body": "two"}, headers=auth_headers(world.token)
    )
    assert resp.status_code == 200, resp.text

    actions = _actions(_activity(world, project, (PAIN, pain)))
    assert "comment_added" in actions and "comment_edited" in actions
    # The comment text itself never appears in the timeline.
    assert "two" not in str(_activity(world, project, (PAIN, pain)).json())


def test_decision_comment_edit_is_audited(client, admin_token):
    decisions_world = World(client, admin_token, "Decision Activity Org", decisions=True)
    project = decisions_world.project()
    decision = decisions_world.decision(project)
    base = f"/api/v1/projects/{project['id']}/modules/decisions/{decision}"
    comment = client.post(f"{base}/comments", json={"body": "one"}, headers=auth_headers(decisions_world.token))
    assert comment.status_code == 201, comment.text
    edited = client.patch(
        f"{base}/comments/{comment.json()['id']}", json={"body": "two"}, headers=auth_headers(decisions_world.token)
    )
    assert edited.status_code == 200, edited.text

    actions = _actions(_activity(decisions_world, project, ("decision", decision)))
    assert "comment_added" in actions and "comment_edited" in actions


def test_generic_link_events_show_the_other_end_from_both_sides(world):
    project = world.project()
    requirement = world.requirement(project, "Linked req")
    action = world.action(project)
    link_type = world.link_type("Relates", "Relates back")
    resp = world.generic_link(project, (REQ, requirement), link_type, (ACTION, action))
    assert resp.status_code == 201, resp.text

    mine = [e for e in _activity(world, project, (REQ, requirement)).json()["entries"] if e["entity_type"] == "artefact_link"]
    assert len(mine) == 1
    assert mine[0]["detail"]["direction"] == "outgoing"
    assert mine[0]["detail"]["other_type"] == ACTION
    assert mine[0]["detail"]["other_label"]

    theirs = [e for e in _activity(world, project, (ACTION, action)).json()["entries"] if e["entity_type"] == "artefact_link"]
    assert len(theirs) == 1 and theirs[0]["detail"]["direction"] == "incoming"


def test_link_event_is_omitted_when_the_other_end_is_not_visible(world):
    project = world.project()
    requirement = world.requirement(project)
    pain = world.pain_point(project)
    link_type = world.link_type("Informs", "Informed by")
    assert world.generic_link(project, (REQ, requirement), link_type, (PAIN, pain)).status_code == 201
    assert any(e["entity_type"] == "artefact_link" for e in _activity(world, project, (REQ, requirement)).json()["entries"])

    off = world.client.put(
        f"/api/v1/orgs/{world.org['id']}/modules/context_strategy", json={"enabled": False},
        headers=auth_headers(world.token),
    )
    assert off.status_code == 200, off.text
    after = _activity(world, project, (REQ, requirement)).json()["entries"]
    assert not any(e["entity_type"] == "artefact_link" for e in after)


def test_activity_of_a_record_from_another_project_is_not_found(world):
    project = world.project("A")
    other_project = world.project("B")
    requirement = world.requirement(project)
    assert _activity(world, other_project, (REQ, requirement)).status_code == 404


def test_unknown_type_and_unknown_record_are_not_found(world):
    project = world.project()
    assert _activity(world, project, ("not_a_type", uuid.uuid4())).status_code == 404
    assert _activity(world, project, (REQ, uuid.uuid4())).status_code == 404


def test_a_user_of_another_organisation_and_a_disabled_module_cannot_read_activity(client, admin_token, world):
    project = world.project()
    requirement = world.requirement(project)
    pain = world.pain_point(project)
    _, outsider_token = create_org_admin_in(client, admin_token, f"Outsider {uuid.uuid4().hex[:6]}")
    assert _activity(world, project, (REQ, requirement), token=outsider_token).status_code in (403, 404)

    # With the module off, the module record is hidden even from the organisation's admin.
    off = world.client.put(
        f"/api/v1/orgs/{world.org['id']}/modules/context_strategy", json={"enabled": False},
        headers=auth_headers(world.token),
    )
    assert off.status_code == 200, off.text
    assert _activity(world, project, (PAIN, pain)).status_code == 404


def test_paging(world):
    project = world.project()
    requirement = world.requirement(project)
    for i in range(3):
        _rename(world, project, requirement, f"Rev {i}")
    everything = _activity(world, project, (REQ, requirement), limit=100).json()["entries"]
    assert len(everything) >= 4

    first = _activity(world, project, (REQ, requirement), limit=2).json()
    assert len(first["entries"]) == 2 and first["has_more"] is True
    rest = _activity(world, project, (REQ, requirement), limit=100, offset=2).json()
    assert first["entries"] + rest["entries"] == everything
    assert rest["has_more"] is False
    assert _activity(world, project, (REQ, requirement), limit=0).status_code == 422


def test_requirement_reorder_is_audited(world):
    project = world.project()
    first = world.requirement(project, "One")
    world.requirement(project, "Two")
    resp = world.client.post(
        f"/api/v1/projects/{project['id']}/requirements/{first}/move", json={"direction": "down"},
        headers=auth_headers(world.token),
    )
    assert resp.status_code == 200, resp.text
    assert "moved" in _actions(_activity(world, project, (REQ, first)))


def test_scrub_removes_secret_looking_keys_recursively():
    cleaned = _scrub({"name": "x", "password_hash": "h", "nested": {"api_key": "k", "keep": 1}, "list": [{"token": "t", "ok": 2}]})
    assert cleaned == {"name": "x", "nested": {"keep": 1}, "list": [{"ok": 2}]}


def _audited_type_names() -> set[str]:
    """Every artefact type some `log_event(entity_type=...)` call in the application can emit,
    resolving `*_ARTEFACT_TYPE`-style constants to their string values."""
    root = pathlib.Path(__file__).resolve().parent.parent / "app"
    constants: dict[str, str] = {}
    trees = []
    for path in root.rglob("*.py"):
        if "tests" in path.parts:
            continue
        tree = ast.parse(path.read_text())
        trees.append(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        constants[target.id] = node.value.value
    emitted: set[str] = set()
    for tree in trees:
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for keyword in node.keywords:
                if keyword.arg not in ("entity_type", "audit_entity_type"):
                    continue
                value = keyword.value
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    emitted.add(value.value)
                elif isinstance(value, ast.Name) and value.id in constants:
                    emitted.add(constants[value.id])
                elif isinstance(value, ast.Attribute) and value.attr in constants:
                    emitted.add(constants[value.attr])
    return emitted


def test_every_registered_artefact_type_is_audited_under_its_own_name():
    """The activity endpoint finds a record's events by `entity_type == artefact type`; a type whose
    events are written under another name would show an empty timeline."""
    missing = get_all_registered_artefact_types() - _audited_type_names()
    assert not missing, f"artefact types with no audit events written under their own name: {sorted(missing)}"
