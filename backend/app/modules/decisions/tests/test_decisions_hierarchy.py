"""Tests for Decision Types' hierarchical-project fallback (Phase 9,
2026-09-22, **Decided by: User** — supersedes Phase 4's own **Decided by:
Agent** call that Decision Types would have no such fallback, unlike
`ActionTypeDefinition`). Mirrors `tests/test_action_types.py`'s own
hierarchy test suite exactly, through the real HTTP API
(`test_decisions_api.py`'s own convention), scoped to Decisions instead.
"""

from __future__ import annotations

from app.modules.decisions.tests.test_decisions_api import _base, _create_decision, _enable_decisions_module
from tests.conftest import auth_headers, create_org_admin_in, create_project


def _decision_types(client, token, project_id):
    return client.get(f"{_base(project_id)}/decision-types", headers=auth_headers(token)).json()


def test_child_project_falls_back_to_parent_decision_types_when_empty(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "Decision Fallback Org")
    _enable_decisions_module(client, org_admin_token, org["id"])
    parent = create_project(client, org_admin_token, org["id"], "Fallback Parent", can_be_parent=True)
    child = create_project(client, org_admin_token, org["id"], "Fallback Child", parent_project_id=parent["id"])

    # A child project starts with none of its own (Phase 9's root-only
    # seeding gate), so the *effective* list (what list_decision_types
    # always returns) falls back to the parent's 5 defaults.
    assert [t["name"] for t in _decision_types(client, org_admin_token, child["id"])] == [
        "Architecture", "Design", "Engineering", "Strategy", "Operational",
    ]


def test_child_with_its_own_decision_types_does_not_fall_back(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "No Fallback Org")
    _enable_decisions_module(client, org_admin_token, org["id"])
    parent = create_project(client, org_admin_token, org["id"], "No Fallback Parent", can_be_parent=True)
    child = create_project(client, org_admin_token, org["id"], "No Fallback Child", parent_project_id=parent["id"])
    client.post(f"{_base(child['id'])}/decision-types", json={"name": "Child Only"}, headers=auth_headers(org_admin_token))

    names = {t["name"] for t in _decision_types(client, org_admin_token, child["id"])}
    assert names == {"Child Only"}
    assert "Architecture" not in names


def test_deleting_last_child_decision_type_is_allowed_but_not_for_a_root(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "Delete Floor Org")
    _enable_decisions_module(client, org_admin_token, org["id"])
    parent = create_project(client, org_admin_token, org["id"], "Delete Floor Parent", can_be_parent=True)
    child = create_project(client, org_admin_token, org["id"], "Delete Floor Child", parent_project_id=parent["id"])
    child_type = client.post(
        f"{_base(child['id'])}/decision-types", json={"name": "Only Child Type"}, headers=auth_headers(org_admin_token)
    ).json()

    resp = client.delete(f"{_base(child['id'])}/decision-types/{child_type['id']}", headers=auth_headers(org_admin_token))
    assert resp.status_code == 204
    # allow_empty let the child be emptied of its own — it now falls back
    # to the parent's 5 defaults, same as the always-empty case above.
    assert [t["name"] for t in _decision_types(client, org_admin_token, child["id"])] == [
        "Architecture", "Design", "Engineering", "Strategy", "Operational",
    ]

    # A root project keeps the unconditional floor-of-1. None of the
    # parent's 5 defaults are in use by any Decision here, so no
    # `reassign_to_id` is needed until only one is left.
    root_types = _decision_types(client, org_admin_token, parent["id"])
    for t in root_types[:-1]:
        resp = client.delete(f"{_base(parent['id'])}/decision-types/{t['id']}", headers=auth_headers(org_admin_token))
        assert resp.status_code == 204
    last = _decision_types(client, org_admin_token, parent["id"])
    assert len(last) == 1
    resp2 = client.delete(f"{_base(parent['id'])}/decision-types/{last[0]['id']}", headers=auth_headers(org_admin_token))
    assert resp2.status_code == 409


def test_decision_on_child_can_reference_an_inherited_parent_decision_type(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "Inherited Decision Org")
    _enable_decisions_module(client, org_admin_token, org["id"])
    parent = create_project(client, org_admin_token, org["id"], "Inherited Decision Parent", can_be_parent=True)
    child = create_project(client, org_admin_token, org["id"], "Inherited Decision Child", parent_project_id=parent["id"])

    parent_types = _decision_types(client, org_admin_token, parent["id"])
    decision = _create_decision(client, org_admin_token, child["id"], parent_types[0]["id"])
    assert decision["decision_type_id"] == parent_types[0]["id"]
