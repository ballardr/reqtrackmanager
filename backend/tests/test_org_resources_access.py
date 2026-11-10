"""Tests for who may manage an organisation's shared resources (`routers.orgs.resources`).

Upload and delete need the `manage_org_resources` permission: organisation administrators hold it, a custom role gives it
to a user or an organisation group, and a project creator, a member or a user of another organisation never has it.
The list is open to every member and carries each uploader's name and the number of records linking the resource; the
`access` read tells the page whether to show the controls. Each test builds its own organisation.
"""

from __future__ import annotations

import uuid

from sqlalchemy import event

from app.database import engine
from tests.conftest import (
    auth_headers,
    create_component_and_category,
    create_org_admin_in,
    create_org_user,
    create_project,
    login,
)

PNG = ("resource.txt", b"shared", "text/plain")


def _user(client, admin_token, org, role: str) -> tuple[str, str]:
    """A new organisation user with the given organisation role; returns (user id, token)."""
    email = f"res-{role}-{uuid.uuid4().hex[:6]}@example.com"
    user_id = create_org_user(client, admin_token, org["id"], email, role=role)
    return user_id, login(client, email, "Password123!")


def _role_with_resources(client, org_admin_token, org) -> str:
    """A custom role holding only `manage_org_resources`; returns its id."""
    resp = client.post(
        f"/api/v1/orgs/{org['id']}/custom-roles",
        json={"name": f"Resources {uuid.uuid4().hex[:6]}", "description": "", "scope": "org", "permissions": ["manage_org_resources"]},
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _upload(client, org, token):
    return client.post(f"/api/v1/orgs/{org['id']}/resources", files={"file": PNG}, headers=auth_headers(token))


def _access(client, org, token) -> bool:
    resp = client.get(f"/api/v1/orgs/{org['id']}/resources/access", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()["can_manage"]


def test_the_permission_is_in_the_vocabulary(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "Resources Vocabulary Org")
    resp = client.get(f"/api/v1/orgs/{org['id']}/permissions", headers=auth_headers(org_admin_token))
    assert "manage_org_resources" in {p["key"] for p in resp.json()}


def test_administrator_manages_and_others_only_read(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "Resources Roles Org")
    _, creator_token = _user(client, admin_token, org, "project_creator")
    _, member_token = _user(client, admin_token, org, "member")

    uploaded = _upload(client, org, org_admin_token)
    assert uploaded.status_code == 201, uploaded.text
    resource_id = uploaded.json()["id"]

    assert _access(client, org, org_admin_token) is True
    for token in (creator_token, member_token):
        assert _access(client, org, token) is False
        assert _upload(client, org, token).status_code == 403
        assert client.delete(f"/api/v1/orgs/{org['id']}/resources/{resource_id}", headers=auth_headers(token)).status_code == 403
        listed = client.get(f"/api/v1/orgs/{org['id']}/resources", headers=auth_headers(token))
        assert [r["id"] for r in listed.json()] == [resource_id]

    assert client.delete(f"/api/v1/orgs/{org['id']}/resources/{resource_id}", headers=auth_headers(org_admin_token)).status_code == 204


def test_a_custom_role_grants_the_right_to_a_user(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "Resources User Role Org")
    user_id, token = _user(client, admin_token, org, "member")
    role_id = _role_with_resources(client, org_admin_token, org)
    assert _upload(client, org, token).status_code == 403

    grant = client.post(f"/api/v1/orgs/{org['id']}/custom-roles/{role_id}/users/{user_id}", json={}, headers=auth_headers(org_admin_token))
    assert grant.status_code == 204, grant.text
    assert _access(client, org, token) is True
    assert _upload(client, org, token).status_code == 201

    client.delete(f"/api/v1/orgs/{org['id']}/custom-roles/{role_id}/users/{user_id}", headers=auth_headers(org_admin_token))
    assert _access(client, org, token) is False
    assert _upload(client, org, token).status_code == 403


def test_a_custom_role_grants_the_right_to_a_group_and_its_nested_group(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "Resources Group Role Org")
    user_id, token = _user(client, admin_token, org, "member")
    headers = auth_headers(org_admin_token)
    outer = client.post(f"/api/v1/orgs/{org['id']}/groups", json={"name": "Librarians"}, headers=headers).json()["id"]
    inner = client.post(f"/api/v1/orgs/{org['id']}/groups", json={"name": "Archivists"}, headers=headers).json()["id"]
    client.post(f"/api/v1/orgs/{org['id']}/groups/{inner}/members", json={"user_id": user_id}, headers=headers)
    client.post(f"/api/v1/orgs/{org['id']}/groups/{outer}/members", json={"member_org_group_id": inner}, headers=headers)
    role_id = _role_with_resources(client, org_admin_token, org)
    assert _access(client, org, token) is False

    grant = client.post(f"/api/v1/orgs/{org['id']}/custom-roles/{role_id}/groups/{outer}", json={}, headers=headers)
    assert grant.status_code == 204, grant.text
    assert _access(client, org, token) is True
    assert _upload(client, org, token).status_code == 201


def test_another_organisation_has_no_right_and_cannot_reach_the_resource(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "Resources Tenant A Org")
    other, other_admin_token = create_org_admin_in(client, admin_token, "Resources Tenant B Org")
    resource_id = _upload(client, org, org_admin_token).json()["id"]

    assert _upload(client, org, other_admin_token).status_code == 403
    assert client.get(f"/api/v1/orgs/{org['id']}/resources", headers=auth_headers(other_admin_token)).status_code == 403
    assert client.delete(f"/api/v1/orgs/{other['id']}/resources/{resource_id}", headers=auth_headers(other_admin_token)).status_code == 404
    assert client.delete(f"/api/v1/orgs/{org['id']}/resources/{resource_id}", headers=auth_headers(other_admin_token)).status_code == 403


def test_the_list_names_the_uploader_and_counts_links_in_flat_statements(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "Resources Links Org")
    project = create_project(client, org_admin_token, org["id"])
    component_id, category_id = create_component_and_category(client, org_admin_token, project["id"])
    resource_id = _upload(client, org, org_admin_token).json()["id"]
    unlinked_id = _upload(client, org, org_admin_token).json()["id"]
    for name in ("One", "Two"):
        requirement = client.post(
            f"/api/v1/projects/{project['id']}/requirements",
            json={"name": name, "description": "d", "component_id": component_id, "category_id": category_id},
            headers=auth_headers(org_admin_token),
        )
        assert requirement.status_code == 201, requirement.text
        link = client.post(
            f"/api/v1/projects/{project['id']}/requirements/{requirement.json()['id']}/files/link",
            json={"file_id": resource_id}, headers=auth_headers(org_admin_token),
        )
        assert link.status_code == 201, link.text

    statements: list[str] = []

    def count(conn, cursor, statement, *args):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", count)
    try:
        rows = client.get(f"/api/v1/orgs/{org['id']}/resources", headers=auth_headers(org_admin_token)).json()
    finally:
        event.remove(engine, "before_cursor_execute", count)

    by_id = {r["id"]: r for r in rows}
    assert by_id[resource_id]["link_count"] == 2
    assert by_id[unlinked_id]["link_count"] == 0
    assert by_id[resource_id]["uploaded_by_display_name"]
    assert len(statements) < 15  # a fixed number, however many resources there are

    deleted = client.delete(f"/api/v1/orgs/{org['id']}/resources/{resource_id}", headers=auth_headers(org_admin_token))
    assert deleted.status_code == 204
    remaining = client.get(f"/api/v1/orgs/{org['id']}/resources", headers=auth_headers(org_admin_token)).json()
    assert [r["id"] for r in remaining] == [unlinked_id]
