"""Shared helpers for the Risk Management module's tests: org/project setup with
the module enabled, member and role grants, scoring-level lookup, a default
risk payload and treatment-link builders."""

from __future__ import annotations

import uuid

from tests.conftest import (
    auth_headers,
    create_component_and_category,
    create_org_admin_in,
    create_org_user,
    create_project,
    login,
)

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


def link_type_id(client, token, org_id, forward_name: str) -> str:
    """The id of the organisation's link type with this forward name (listing seeds module types)."""
    rows = client.get(f"/api/v1/orgs/{org_id}/link-types", headers=auth_headers(token)).json()
    return next(row["id"] for row in rows if row["forward_name"] == forward_name)


def create_requirement(client, token, project_id, name: str = "Mitigating requirement") -> str:
    """Creates a requirement in the project (with a fresh component and category) and returns its id."""
    components = client.get(f"/api/v1/projects/{project_id}/components", headers=auth_headers(token)).json()
    categories = client.get(f"/api/v1/projects/{project_id}/categories", headers=auth_headers(token)).json()
    if components and categories:
        component_id, category_id = components[0]["id"], categories[0]["id"]
    else:
        component_id, category_id = create_component_and_category(client, token, project_id)
    resp = client.post(
        f"/api/v1/projects/{project_id}/requirements",
        json={"name": name, "component_id": component_id, "category_id": category_id}, headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def create_action(client, token, project_id, title: str = "Treatment action") -> str:
    """Creates a requirement action in the project and returns its id."""
    types = client.get(f"/api/v1/projects/{project_id}/action-types", headers=auth_headers(token)).json()
    resp = client.post(
        f"/api/v1/projects/{project_id}/actions", json={"title": title, "action_type_id": types[0]["id"]},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def generic_link(client, token, project_id, risk_id, link_type, direction, other_type, other_id):
    """POSTs the generic link-authoring endpoint from the risk's page."""
    return client.post(
        f"/api/v1/projects/{project_id}/artefacts/risk/{risk_id}/links",
        json={"link_type_id": link_type, "direction": direction, "other_type": other_type, "other_id": other_id},
        headers=auth_headers(token),
    )


def mitigate_with_requirement(client, token, org, project, risk_id, name: str | None = None) -> tuple[str, str]:
    """Links a new requirement to the risk as `Requirement Mitigates Risk` (the risk is the target).

    Returns:
        `(link id, requirement id)`.
    """
    requirement = create_requirement(client, token, project["id"], name or f"Mitigation {uuid.uuid4().hex[:6]}")
    resp = generic_link(
        client, token, project["id"], risk_id, link_type_id(client, token, org["id"], "Mitigates"), "incoming",
        "requirement", requirement,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"], requirement


def assess(client, token, project_id, risk_id, link_id, status: str = "effective", rationale: str = "Verified in review."):
    """PUTs a treatment verdict."""
    return client.put(
        f"{project_base(project_id)}/risks/{risk_id}/treatments/{link_id}", json={"status": status, "rationale": rationale},
        headers=auth_headers(token),
    )


def add_effective_treatment(client, token, org, project, risk_id) -> str:
    """Gives the risk one mitigating requirement assessed effective; returns the link id."""
    link_id, _ = mitigate_with_requirement(client, token, org, project, risk_id)
    resp = assess(client, token, project["id"], risk_id, link_id)
    assert resp.status_code == 200, resp.text
    return link_id
