"""Tests for org-definable project statuses (`ProjectStatusDefinition`) —
creation seeds 4 defaults (Proposed/Active/Abandoned/Completed), a new
project defaults to the org's first status, and the shared §4.0
rename/reorder/delete-with-reassignment rules (`services.definitions`)."""

from tests.conftest import auth_headers, create_org_admin_in, create_project


def _statuses(client, token, org_id):
    return client.get(f"/api/v1/orgs/{org_id}/project-statuses", headers=auth_headers(token)).json()


def test_new_org_is_seeded_with_four_default_statuses(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "Status Seed Org")
    statuses = _statuses(client, token, org["id"])
    assert [s["name"] for s in statuses] == ["Proposed", "Active", "Abandoned", "Completed"]
    assert [s["sort_order"] for s in statuses] == [0, 1, 2, 3]


def test_new_project_defaults_to_first_org_status(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "Status Default Org")
    statuses = _statuses(client, token, org["id"])
    project = create_project(client, token, org["id"])
    assert project["status_id"] == statuses[0]["id"]
    assert statuses[0]["name"] == "Proposed"


def test_create_rename_move_status(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "Status CRUD Org")
    created = client.post(
        f"/api/v1/orgs/{org['id']}/project-statuses", json={"name": "On Hold"}, headers=auth_headers(token)
    )
    assert created.status_code == 201, created.text
    status_id = created.json()["id"]
    assert created.json()["sort_order"] == 4

    renamed = client.patch(
        f"/api/v1/orgs/{org['id']}/project-statuses/{status_id}", json={"name": "Paused"}, headers=auth_headers(token)
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Paused"

    duplicate = client.post(
        f"/api/v1/orgs/{org['id']}/project-statuses", json={"name": "Active"}, headers=auth_headers(token)
    )
    assert duplicate.status_code == 400

    moved = client.post(
        f"/api/v1/orgs/{org['id']}/project-statuses/{status_id}/move", json={"direction": "up"},
        headers=auth_headers(token),
    )
    assert moved.status_code == 200
    statuses = _statuses(client, token, org["id"])
    assert [s["name"] for s in statuses][:2] == ["Proposed", "Active"]  # unaffected middle order sanity check
    assert statuses[-2]["name"] == "Paused"  # moved up one from the very end


def test_renaming_status_does_not_disturb_projects_on_it(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "Status Rename Org")
    statuses = _statuses(client, token, org["id"])
    project = create_project(client, token, org["id"])
    assert project["status_id"] == statuses[0]["id"]

    client.patch(
        f"/api/v1/orgs/{org['id']}/project-statuses/{statuses[0]['id']}", json={"name": "Renamed Proposed"},
        headers=auth_headers(token),
    )
    refreshed = client.get(f"/api/v1/projects/{project['id']}", headers=auth_headers(token)).json()
    assert refreshed["status_id"] == statuses[0]["id"]


def test_cannot_delete_last_remaining_status_even_if_unused(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "Status Min Count Org")
    statuses = _statuses(client, token, org["id"])
    # Delete three of the four defaults (none in use yet — no project exists).
    for s in statuses[1:]:
        resp = client.delete(f"/api/v1/orgs/{org['id']}/project-statuses/{s['id']}", headers=auth_headers(token))
        assert resp.status_code == 204, resp.text

    last = _statuses(client, token, org["id"])
    assert len(last) == 1
    resp = client.delete(f"/api/v1/orgs/{org['id']}/project-statuses/{last[0]['id']}", headers=auth_headers(token))
    assert resp.status_code == 409


def test_deleting_in_use_status_without_reassign_id_409s_with_count(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "Status Reassign Org")
    project_a = create_project(client, token, org["id"], "Project A")
    project_b = create_project(client, token, org["id"], "Project B")
    used_status_id = project_a["status_id"]
    assert project_b["status_id"] == used_status_id

    resp = client.delete(f"/api/v1/orgs/{org['id']}/project-statuses/{used_status_id}", headers=auth_headers(token))
    assert resp.status_code == 409
    assert "2" in resp.json()["detail"]


def test_deleting_in_use_status_with_reassign_id_moves_projects_then_deletes(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "Status Reassign Success Org")
    statuses = _statuses(client, token, org["id"])
    project = create_project(client, token, org["id"])
    used_status_id = project["status_id"]
    other_status_id = statuses[1]["id"]
    assert other_status_id != used_status_id

    resp = client.delete(
        f"/api/v1/orgs/{org['id']}/project-statuses/{used_status_id}",
        params={"reassign_to_id": other_status_id}, headers=auth_headers(token),
    )
    assert resp.status_code == 204, resp.text

    refreshed = client.get(f"/api/v1/projects/{project['id']}", headers=auth_headers(token)).json()
    assert refreshed["status_id"] == other_status_id
    remaining_ids = {s["id"] for s in _statuses(client, token, org["id"])}
    assert used_status_id not in remaining_ids


def test_reassign_to_id_must_be_in_same_org_and_not_self(client, admin_token):
    org_a, token_a = create_org_admin_in(client, admin_token, "Reassign Org A")
    org_b, token_b = create_org_admin_in(client, admin_token, "Reassign Org B")
    project = create_project(client, token_a, org_a["id"])
    used_status_id = project["status_id"]

    # Same id as the one being deleted.
    resp = client.delete(
        f"/api/v1/orgs/{org_a['id']}/project-statuses/{used_status_id}",
        params={"reassign_to_id": used_status_id}, headers=auth_headers(token_a),
    )
    assert resp.status_code == 400

    # A status id from a different organisation.
    other_org_status_id = _statuses(client, token_b, org_b["id"])[0]["id"]
    resp = client.delete(
        f"/api/v1/orgs/{org_a['id']}/project-statuses/{used_status_id}",
        params={"reassign_to_id": other_org_status_id}, headers=auth_headers(token_a),
    )
    assert resp.status_code == 400


def test_project_status_update_rejects_cross_org_status_id(client, admin_token):
    org_a, token_a = create_org_admin_in(client, admin_token, "Cross Org Status A")
    org_b, token_b = create_org_admin_in(client, admin_token, "Cross Org Status B")
    project = create_project(client, token_a, org_a["id"])
    other_org_status_id = _statuses(client, token_b, org_b["id"])[0]["id"]

    resp = client.patch(
        f"/api/v1/projects/{project['id']}", json={"status_id": other_org_status_id}, headers=auth_headers(token_a),
    )
    assert resp.status_code == 400


def test_project_status_update_accepts_same_org_status_id(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "Same Org Status Update")
    statuses = _statuses(client, token, org["id"])
    project = create_project(client, token, org["id"])
    new_status_id = next(s["id"] for s in statuses if s["id"] != project["status_id"])

    resp = client.patch(
        f"/api/v1/projects/{project['id']}", json={"status_id": new_status_id}, headers=auth_headers(token),
    )
    assert resp.status_code == 200
    assert resp.json()["status_id"] == new_status_id


def test_project_statuses_endpoints_require_org_membership(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "Status Auth Org")
    other_org, other_token = create_org_admin_in(client, admin_token, "Status Auth Other Org")
    resp = client.get(f"/api/v1/orgs/{org['id']}/project-statuses", headers=auth_headers(other_token))
    assert resp.status_code == 403
