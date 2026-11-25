"""
Tests for the core approval check (`services.approval_policy`) with no Governance module involved: every approval path of a
Requirement and a Change Request keeps its current answer (a project manager approves, anyone else is refused with the
same message), and a holder of the type's `approve_baseline` permission atom through a custom role now approves too.
Also pins the strict role-holding helpers the policy uses: a role is held, never composed from an administrator.
"""

from __future__ import annotations

import uuid

import pytest

from app.database import SessionLocal
from app.models.user import User
from app.modules.seams import ApproverRole
from app.services import approval_policy
from app.services.permissions import encode_permission
from tests.conftest import auth_headers, create_org_admin_in, create_org_user, create_project, login
from tests.test_approval_separation import _approve_requirement, _requirement


def _setup(client, admin_token, name):
    org, token = create_org_admin_in(client, admin_token, name)
    project = create_project(client, token, org["id"], f"{name} project")
    return org, project, token


def _member(client, token, org_id, project_id, role="stakeholder") -> tuple[str, str]:
    email = f"seam_{uuid.uuid4().hex[:8]}@example.com"
    user_id = create_org_user(client, token, org_id, email)
    resp = client.post(f"/api/v1/projects/{project_id}/roles", json={"user_id": user_id, "role": role}, headers=auth_headers(token))
    assert resp.status_code == 204, resp.text
    return user_id, login(client, email, "Password123!")


def _custom_role(client, token, org_id, project_id, user_id, permissions) -> str:
    resp = client.post(
        f"/api/v1/orgs/{org_id}/custom-roles",
        json={"name": f"Role {uuid.uuid4().hex[:8]}", "description": "", "scope": "project", "permissions": permissions},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    role_id = resp.json()["id"]
    grant = client.post(
        f"/api/v1/orgs/{org_id}/custom-roles/{role_id}/users/{user_id}", json={"project_id": project_id}, headers=auth_headers(token),
    )
    assert grant.status_code == 204, grant.text
    return role_id


def _submitted_change_request(client, token, project_id, requirement_id) -> str:
    cr = client.post(
        f"/api/v1/projects/{project_id}/change-requests",
        json={
            "kind": "modify_requirement", "requirement_id": requirement_id, "changed_fields": ["name"],
            "proposed_name": f"Renamed {uuid.uuid4().hex[:6]}", "reason": "Reason",
        },
        headers=auth_headers(token),
    )
    assert cr.status_code == 201, cr.text
    sent = client.post(f"/api/v1/projects/{project_id}/change-requests/{cr.json()['id']}/submit", headers=auth_headers(token))
    assert sent.status_code == 200, sent.text
    return cr.json()["id"]


def _decide(client, token, project_id, cr_id):
    return client.post(
        f"/api/v1/projects/{project_id}/change-requests/{cr_id}/decide", json={"approve": True, "note": "ok"},
        headers=auth_headers(token),
    )


def test_a_stakeholder_is_refused_with_the_unchanged_message(client, admin_token):
    org, project, token = _setup(client, admin_token, "Seam Default Co")
    _, stakeholder = _member(client, token, org["id"], project["id"])
    requirement = _requirement(client, token, project["id"])
    refused = _approve_requirement(client, stakeholder, project["id"], requirement)
    assert refused.status_code == 403
    assert refused.json()["detail"] == "Only a project manager can approve a requirement."
    assert _approve_requirement(client, token, project["id"], requirement).status_code == 200


def test_the_refusal_comes_before_the_not_found_answer(client, admin_token):
    org, project, token = _setup(client, admin_token, "Seam Order Co")
    _, stakeholder = _member(client, token, org["id"], project["id"])
    missing = _approve_requirement(client, stakeholder, project["id"], str(uuid.uuid4()))
    assert missing.status_code == 403
    assert _approve_requirement(client, token, project["id"], str(uuid.uuid4())).status_code == 404


def test_a_custom_role_holding_the_requirement_approval_atom_approves_a_requirement(client, admin_token):
    org, project, token = _setup(client, admin_token, "Seam Atom Requirement Co")
    user_id, member = _member(client, token, org["id"], project["id"])
    requirement = _requirement(client, token, project["id"])
    assert _approve_requirement(client, member, project["id"], requirement).status_code == 403
    _custom_role(client, token, org["id"], project["id"], user_id, [encode_permission("requirement", "approve_baseline")])
    approved = _approve_requirement(client, member, project["id"], requirement, "Checked.")
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"


def test_a_role_holding_only_another_atom_does_not_approve(client, admin_token):
    org, project, token = _setup(client, admin_token, "Seam Other Atom Co")
    user_id, member = _member(client, token, org["id"], project["id"])
    requirement = _requirement(client, token, project["id"])
    _custom_role(client, token, org["id"], project["id"], user_id, [encode_permission("requirement", "manage")])
    assert _approve_requirement(client, member, project["id"], requirement).status_code == 403


def test_the_atom_also_reaches_the_edit_path_and_a_change_request_decision(client, admin_token):
    org, project, token = _setup(client, admin_token, "Seam Atom Paths Co")
    user_id, member = _member(client, token, org["id"], project["id"])
    requirement = _requirement(client, token, project["id"])
    other = _requirement(client, token, project["id"], "Second")
    assert _approve_requirement(client, token, project["id"], other).status_code == 200
    cr_id = _submitted_change_request(client, token, project["id"], other)
    assert _decide(client, member, project["id"], cr_id).status_code == 403

    _custom_role(client, token, org["id"], project["id"], user_id, [
        encode_permission("requirement", "approve_baseline"), encode_permission("change_request", "approve_baseline"),
    ])
    assert _decide(client, member, project["id"], cr_id).status_code == 200
    current = client.get(f"/api/v1/projects/{project['id']}/requirements/{requirement}", headers=auth_headers(token)).json()
    from tests.test_approval_separation import _SCOPES

    component_id, category_id = _SCOPES[project["id"]]
    edit = client.put(
        f"/api/v1/projects/{project['id']}/requirements/{requirement}",
        json={
            "name": current["name"], "component_id": component_id, "category_id": category_id, "owner": current["owner"],
            "status": "approved", "change_note": "Approved in the edit form.",
        },
        headers=auth_headers(member),
    )
    assert edit.status_code == 200, edit.text


def test_a_change_request_atom_alone_does_not_decide_a_change_request_without_it(client, admin_token):
    org, project, token = _setup(client, admin_token, "Seam CR Atom Co")
    user_id, member = _member(client, token, org["id"], project["id"])
    requirement = _requirement(client, token, project["id"])
    assert _approve_requirement(client, token, project["id"], requirement).status_code == 200
    cr_id = _submitted_change_request(client, token, project["id"], requirement)
    _custom_role(client, token, org["id"], project["id"], user_id, [encode_permission("requirement", "approve_baseline")])
    refused = _decide(client, member, project["id"], cr_id)
    assert refused.status_code == 403 and refused.json()["detail"] == "Only a project manager can decide change requests."


# --- the role-holding helpers --------------------------------------------------------------------


def test_a_module_role_is_held_not_composed_from_an_administrator(client, admin_token):
    """`rbac.user_satisfies_module_role` admits an organisation administrator to every organisation-scoped module role; a
    policy that names the role must admit only those who were given it."""
    from app.services import rbac

    org, project, token = _setup(client, admin_token, "Seam Held Role Co")
    org_id = uuid.UUID(org["id"])
    db = SessionLocal()
    try:
        org_admin = db.get(User, uuid.UUID(client.get("/api/v1/auth/me", headers=auth_headers(token)).json()["id"]))
        assert org_admin is not None
        assert rbac.user_satisfies_module_role(
            db, org_admin, "context_strategy", "org_strategy_approver", organization_id=org_id, project_id=None,
        ) is True
        assert rbac.user_holds_module_role(
            db, org_admin.id, "context_strategy", "org_strategy_approver", organization_id=org_id, project_id=None,
        ) is False
        assert rbac.user_holds_module_role(
            db, org_admin.id, "no_such_module", "x", organization_id=org_id, project_id=None,
        ) is False
    finally:
        db.close()


@pytest.mark.parametrize(
    "role",
    [
        ApproverRole("project", "not_a_role"),
        ApproverRole("module", "no_such_module:role"),
        ApproverRole("custom", "not-a-uuid"),
        ApproverRole("custom", str(uuid.uuid4())),
    ],
    ids=["project", "module", "custom-not-an-id", "custom-unknown-id"],
)
def test_an_unknown_role_is_held_by_nobody(client, admin_token, role):
    org, project, token = _setup(client, admin_token, f"Seam Unknown Role {role.kind} {role.key[:6]} Co")
    db = SessionLocal()
    try:
        user = db.get(User, uuid.UUID(client.get("/api/v1/auth/me", headers=auth_headers(token)).json()["id"]))
        assert user is not None
        assert approval_policy.holds_role(
            db, user, role, organization_id=uuid.UUID(org["id"]), project_id=uuid.UUID(project["id"]),
        ) is False
    finally:
        db.close()
