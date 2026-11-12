"""Shared helpers for the Architecture module's tests: an organisation with the module enabled, a project,
members and module-role grants."""

from __future__ import annotations

from tests.conftest import auth_headers, create_org_admin_in, create_org_user, create_project, login

MODULE_KEY = "architecture"


def project_base(project_id) -> str:
    return f"/api/v1/projects/{project_id}/modules/{MODULE_KEY}"


def org_base(org_id) -> str:
    return f"/api/v1/orgs/{org_id}/modules/{MODULE_KEY}"


def enable_module(client, token, org_id) -> None:
    resp = client.put(f"/api/v1/orgs/{org_id}/modules/{MODULE_KEY}", json={"enabled": True}, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text


def setup(client, admin_token, org_name: str):
    """An organisation with a real admin, a project, and the module enabled: `(org, project, admin token)`."""
    org, token = create_org_admin_in(client, admin_token, org_name)
    enable_module(client, token, org["id"])
    return org, create_project(client, token, org["id"], f"{org_name} Project"), token


def add_member(client, org_admin_token, org_id, project_id, email) -> tuple[str, str]:
    """A project member with no module role: `(user id, token)`."""
    user_id = create_org_user(client, org_admin_token, org_id, email)
    resp = client.post(
        f"/api/v1/projects/{project_id}/roles", json={"user_id": user_id, "role": "member"},
        headers=auth_headers(org_admin_token),
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


def element_types(client, token, project_id) -> dict[str, str]:
    """`{name: id}` of the project's effective element types."""
    rows = client.get(f"{project_base(project_id)}/element-types", headers=auth_headers(token)).json()
    return {r["name"]: r["id"] for r in rows}


def connection_types(client, token, project_id) -> dict[str, str]:
    """`{name: id}` of the project's effective connection types."""
    rows = client.get(f"{project_base(project_id)}/connection-types", headers=auth_headers(token)).json()
    return {r["name"]: r["id"] for r in rows}


def make_element(client, token, project_id, name="Gateway", *, type_name="Component", expect=201, **fields) -> dict:
    """Creates an element of the named type; returns the response body (or the response when `expect` is not 201)."""
    body = {"name": name, "element_type_id": element_types(client, token, project_id)[type_name], **fields}
    resp = client.post(f"{project_base(project_id)}/elements", json=body, headers=auth_headers(token))
    assert resp.status_code == expect, resp.text
    return resp.json()


def make_connection(client, token, project_id, source, target, *, type_name="REST API", expect=201, **fields) -> dict:
    """Creates a connection between two elements (ids); returns the response body."""
    body = {
        "connection_type_id": connection_types(client, token, project_id)[type_name],
        "source_element_id": source, "target_element_id": target, **fields,
    }
    resp = client.post(f"{project_base(project_id)}/connections", json=body, headers=auth_headers(token))
    assert resp.status_code == expect, resp.text
    return resp.json()


def make_architect(client, admin_token, org_id, project_id, email) -> str:
    """A project member holding the `architect` role; returns their token."""
    user_id, token = add_member(client, admin_token, org_id, project_id, email)
    grant_project_role(client, admin_token, project_id, user_id, "architect")
    return token


def put_element(client, token, project_id, element, expect=200, **fields) -> dict:
    """Edits an element quoting its current `version`; returns the response body."""
    resp = client.put(
        f"{project_base(project_id)}/elements/{element['id']}", json={"version": element["version"], **fields},
        headers=auth_headers(token),
    )
    assert resp.status_code == expect, resp.text
    return resp.json()
