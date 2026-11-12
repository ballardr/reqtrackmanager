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


# --- Sharing ------------------------------------------------------------------


def org_element_types(client, token, org_id) -> dict[str, str]:
    """`{name: id}` of the organisation's own element types."""
    rows = client.get(f"{org_base(org_id)}/element-types", headers=auth_headers(token)).json()
    return {r["name"]: r["id"] for r in rows}


def make_org_element(client, token, org_id, name="Platform", *, type_name="System", expect=201, **fields) -> dict:
    """Creates an organisation-owned element; returns the response body (or the response when `expect` is not 201)."""
    body = {"name": name, "element_type_id": org_element_types(client, token, org_id)[type_name], **fields}
    resp = client.post(f"{org_base(org_id)}/elements", json=body, headers=auth_headers(token))
    assert resp.status_code == expect, resp.text
    return resp.json()


def make_collection(client, token, base, name="Shared", *, members=(), expect=201) -> dict:
    """Creates a collection under `base` (a project or organisation base URL) holding the given element ids."""
    resp = client.post(f"{base}/collections", json={"name": name}, headers=auth_headers(token))
    assert resp.status_code == expect, resp.text
    if expect != 201:
        return resp.json()
    collection = resp.json()
    if members:
        added = client.post(
            f"{base}/collections/{collection['id']}/members", json={"element_ids": list(members)}, headers=auth_headers(token),
        )
        assert added.status_code == 200, added.text
    return collection


def grant(client, token, base, collection_id, *, project_id=None, group=None, descendants=False, expect=201) -> dict:
    """Grants a collection to a project or a group (`{"type": ..., "id": ...}`); returns the grant (or the response)."""
    body: dict = {"include_descendants": descendants}
    if project_id is not None:
        body["project_id"] = project_id
    if group is not None:
        body["group"] = group
    resp = client.post(f"{base}/collections/{collection_id}/grants", json=body, headers=auth_headers(token))
    assert resp.status_code == expect, resp.text
    return resp.json()


def status_of(client, token, project_id, element_id) -> int:
    """The HTTP status of reading an element through a project."""
    return client.get(f"{project_base(project_id)}/elements/{element_id}", headers=auth_headers(token)).status_code


def shared_names(client, token, project_id, **params) -> set[str]:
    """Names of the elements shared with a project."""
    resp = client.get(f"{project_base(project_id)}/elements/shared", params=params, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return {e["name"] for e in resp.json()}


# --- Diagrams -----------------------------------------------------------------


def make_diagram(client, token, project_id, name="Context", *, expect=201, **fields) -> dict:
    """Creates a diagram; returns the response body (or the response when `expect` is not 201)."""
    resp = client.post(f"{project_base(project_id)}/diagrams", json={"name": name, **fields}, headers=auth_headers(token))
    assert resp.status_code == expect, resp.text
    return resp.json()


def place(client, token, project_id, diagram, element_id, *, expect=201, **box) -> dict:
    """Places an element on a diagram quoting its current `version`; returns the updated diagram."""
    resp = client.post(
        f"{project_base(project_id)}/diagrams/{diagram['id']}/placements",
        json={"version": diagram["version"], "element_id": element_id, **box}, headers=auth_headers(token),
    )
    assert resp.status_code == expect, resp.text
    return resp.json()


def place_all(client, token, project_id, diagram, *element_ids) -> dict:
    """Places several elements one after another; returns the final diagram."""
    for index, element_id in enumerate(element_ids):
        diagram = place(client, token, project_id, diagram, element_id, x=index * 200, y=0)
    return diagram


def view(client, token, project_id, diagram_id, *, expect=200, **params) -> dict:
    """The resolved view of a diagram; `params` are query parameters (`toggle_on`, `toggle_off`, `include_retired`)."""
    resp = client.get(f"{project_base(project_id)}/diagrams/{diagram_id}/view", params=params, headers=auth_headers(token))
    assert resp.status_code == expect, resp.text
    return resp.json()


def save_toggles(client, token, project_id, diagram, toggles, *, expect=200) -> dict:
    """Replaces a diagram's toggles quoting its current `version`; returns the updated diagram."""
    resp = client.put(
        f"{project_base(project_id)}/diagrams/{diagram['id']}/toggles",
        json={"version": diagram["version"], "toggles": toggles}, headers=auth_headers(token),
    )
    assert resp.status_code == expect, resp.text
    return resp.json()
