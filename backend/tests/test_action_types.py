"""Tests for project-scoped requirement-action type definitions
(`ActionTypeDefinition`) — creation seeds 2 defaults (Review, Test), and
the shared §4.0 rename/reorder/delete-with-reassignment rules
(`services.definitions`), scoped to a project instead of an organisation."""

from tests.conftest import auth_headers, create_org_admin_in, create_project


def _action_types(client, token, project_id):
    return client.get(f"/api/v1/projects/{project_id}/action-types", headers=auth_headers(token)).json()


def _create_action(client, token, project_id, action_type_id, title="An action"):
    return client.post(
        f"/api/v1/projects/{project_id}/actions",
        json={"title": title, "action_type_id": action_type_id},
        headers=auth_headers(token),
    ).json()


def test_new_project_is_seeded_with_two_default_action_types(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    action_types = _action_types(client, admin_token, project["id"])
    assert [t["name"] for t in action_types] == ["Review", "Test"]
    assert [t["sort_order"] for t in action_types] == [0, 1]


def test_create_rename_move_action_type(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    created = client.post(
        f"/api/v1/projects/{project['id']}/action-types", json={"name": "Audit"}, headers=auth_headers(admin_token)
    )
    assert created.status_code == 201, created.text
    action_type_id = created.json()["id"]
    assert created.json()["sort_order"] == 2

    renamed = client.patch(
        f"/api/v1/projects/{project['id']}/action-types/{action_type_id}", json={"name": "Compliance Audit"},
        headers=auth_headers(admin_token),
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Compliance Audit"

    duplicate = client.post(
        f"/api/v1/projects/{project['id']}/action-types", json={"name": "Review"}, headers=auth_headers(admin_token)
    )
    assert duplicate.status_code == 400

    moved = client.post(
        f"/api/v1/projects/{project['id']}/action-types/{action_type_id}/move", json={"direction": "up"},
        headers=auth_headers(admin_token),
    )
    assert moved.status_code == 200


def test_renaming_action_type_does_not_disturb_actions_of_it(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    action_types = _action_types(client, admin_token, project["id"])
    action = _create_action(client, admin_token, project["id"], action_types[0]["id"])

    client.patch(
        f"/api/v1/projects/{project['id']}/action-types/{action_types[0]['id']}", json={"name": "Renamed Review"},
        headers=auth_headers(admin_token),
    )
    refreshed = client.get(f"/api/v1/projects/{project['id']}/actions/{action['id']}", headers=auth_headers(admin_token)).json()
    assert refreshed["action_type_id"] == action_types[0]["id"]


def test_cannot_delete_last_remaining_action_type_even_if_unused(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    action_types = _action_types(client, admin_token, project["id"])
    resp = client.delete(
        f"/api/v1/projects/{project['id']}/action-types/{action_types[1]['id']}", headers=auth_headers(admin_token)
    )
    assert resp.status_code == 204, resp.text

    last = _action_types(client, admin_token, project["id"])
    assert len(last) == 1
    resp = client.delete(
        f"/api/v1/projects/{project['id']}/action-types/{last[0]['id']}", headers=auth_headers(admin_token)
    )
    assert resp.status_code == 409


def test_deleting_in_use_action_type_without_reassign_id_409s_with_count(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    action_types = _action_types(client, admin_token, project["id"])
    _create_action(client, admin_token, project["id"], action_types[0]["id"])

    resp = client.delete(
        f"/api/v1/projects/{project['id']}/action-types/{action_types[0]['id']}", headers=auth_headers(admin_token)
    )
    assert resp.status_code == 409
    assert "1" in resp.json()["detail"]


def test_deleting_in_use_action_type_with_reassign_id_moves_actions_then_deletes(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    action_types = _action_types(client, admin_token, project["id"])
    action = _create_action(client, admin_token, project["id"], action_types[0]["id"])

    resp = client.delete(
        f"/api/v1/projects/{project['id']}/action-types/{action_types[0]['id']}",
        params={"reassign_to_id": action_types[1]["id"]}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 204, resp.text

    refreshed = client.get(f"/api/v1/projects/{project['id']}/actions/{action['id']}", headers=auth_headers(admin_token)).json()
    assert refreshed["action_type_id"] == action_types[1]["id"]
    remaining_ids = {t["id"] for t in _action_types(client, admin_token, project["id"])}
    assert action_types[0]["id"] not in remaining_ids


def test_reassign_to_id_must_be_in_same_project_and_not_self(client, admin_token, org_id):
    project_a = create_project(client, admin_token, org_id, "Action Type Project A")
    project_b = create_project(client, admin_token, org_id, "Action Type Project B")
    types_a = _action_types(client, admin_token, project_a["id"])
    types_b = _action_types(client, admin_token, project_b["id"])
    _create_action(client, admin_token, project_a["id"], types_a[0]["id"])

    resp = client.delete(
        f"/api/v1/projects/{project_a['id']}/action-types/{types_a[0]['id']}",
        params={"reassign_to_id": types_a[0]["id"]}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 400

    resp = client.delete(
        f"/api/v1/projects/{project_a['id']}/action-types/{types_a[0]['id']}",
        params={"reassign_to_id": types_b[0]["id"]}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 400


def test_action_types_scoped_per_project_not_shared_across_org(client, admin_token, org_id):
    project_a = create_project(client, admin_token, org_id, "Scoped Project A")
    project_b = create_project(client, admin_token, org_id, "Scoped Project B")
    client.post(f"/api/v1/projects/{project_a['id']}/action-types", json={"name": "Only In A"}, headers=auth_headers(admin_token))
    names_b = {t["name"] for t in _action_types(client, admin_token, project_b["id"])}
    assert "Only In A" not in names_b


def test_action_type_endpoints_require_project_membership(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    _other_org, other_token = create_org_admin_in(client, admin_token, "Action Type Auth Other Org")
    resp = client.get(f"/api/v1/projects/{project['id']}/action-types", headers=auth_headers(other_token))
    assert resp.status_code == 403
