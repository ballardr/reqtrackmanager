"""Shared helpers for the Risk Management module's tests: org/project setup with
the module enabled, member and role grants, scoring-level lookup and a default
risk payload."""

from __future__ import annotations

from tests.conftest import auth_headers, create_org_admin_in, create_org_user, create_project, login

MODULE_KEY = "risk_management"


def project_base(project_id) -> str:
    return f"/api/v1/projects/{project_id}/modules/{MODULE_KEY}"


def org_base(org_id) -> str:
    return f"/api/v1/orgs/{org_id}/modules/{MODULE_KEY}"


def enable_module(client, token, org_id) -> None:
    resp = client.put(f"/api/v1/orgs/{org_id}/modules/{MODULE_KEY}", json={"enabled": True}, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text


def setup(client, admin_token, org_name: str):
    """An org with a real admin, a project, and the module enabled."""
    org, token = create_org_admin_in(client, admin_token, org_name)
    enable_module(client, token, org["id"])
    return org, create_project(client, token, org["id"], f"{org_name} Project"), token


def add_member(client, org_admin_token, org_id, project_id, email) -> tuple[str, str]:
    user_id = create_org_user(client, org_admin_token, org_id, email)
    resp = client.post(
        f"/api/v1/projects/{project_id}/roles", json={"user_id": user_id, "role": "member"}, headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 204, resp.text
    return user_id, login(client, email, "Password123!")


def grant_project_role(client, token, project_id, user_id, role_key) -> None:
    resp = client.post(
        f"/api/v1/projects/{project_id}/members/{user_id}/module-roles",
        json={"module_key": MODULE_KEY, "role_key": role_key}, headers=auth_headers(token),
    )
    assert resp.status_code == 204, resp.text


def grant_org_role(client, token, org_id, user_id, role_key) -> None:
    resp = client.post(
        f"/api/v1/orgs/{org_id}/users/{user_id}/module-roles",
        json={"module_key": MODULE_KEY, "role_key": role_key}, headers=auth_headers(token),
    )
    assert resp.status_code == 204, resp.text


def levels(client, token, project_id) -> dict[str, dict[str, str]]:
    """axis key -> level name -> level id of the `risk` scheme for the project's org."""
    resp = client.get(f"/api/v1/projects/{project_id}/scoring-schemes/risk", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return {a["key"]: {lvl["name"]: lvl["id"] for lvl in a["levels"]} for a in resp.json()["axes"]}


PAYLOAD = {
    "title": "Supplier misses delivery",
    "statement": "If the supplier misses the delivery date, integration testing slips.",
    "cause": "Single-sourced component.",
    "risk_event": "Late delivery of the controller board.",
    "consequence": "Integration slips by weeks.",
}


def create_risk(client, token, project_id, **extra) -> dict:
    resp = client.post(project_base(project_id) + "/risks", json={**PAYLOAD, **extra}, headers=auth_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()
