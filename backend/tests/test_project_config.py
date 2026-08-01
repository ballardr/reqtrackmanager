"""Tests for Pelion (v2) project configuration: the member change-request
submission toggle (C-U-13) and project archiving (C-P-01)."""

from tests.conftest import auth_headers, create_org_user, create_project, login


def _make_member(client, admin_token, org_id, project_id, email):
    user_id = create_org_user(client, admin_token, org_id, email, role="member")
    client.post(
        f"/api/v1/projects/{project_id}/roles", json={"user_id": user_id, "role": "member"},
        headers=auth_headers(admin_token),
    )
    return login(client, email, "Password123!")


def test_member_cannot_submit_change_request_by_default_toggle_off(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    client.patch(
        f"/api/v1/projects/{project['id']}", json={"allow_member_change_requests": False},
        headers=auth_headers(admin_token),
    )
    member_token = _make_member(client, admin_token, org_id, project["id"], "member_cr@example.com")

    resp = client.post(
        f"/api/v1/projects/{project['id']}/change-requests",
        json={"kind": "new_requirement", "proposed_name": "x", "reason": "y"},
        headers=auth_headers(member_token),
    )
    assert resp.status_code == 403


def test_member_can_submit_change_request_when_toggle_enabled(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    assert project["allow_member_change_requests"] is True  # defaults to enabled

    member_token = _make_member(client, admin_token, org_id, project["id"], "member_cr2@example.com")
    resp = client.post(
        f"/api/v1/projects/{project['id']}/change-requests",
        json={"kind": "new_requirement", "proposed_name": "x", "reason": "y"},
        headers=auth_headers(member_token),
    )
    assert resp.status_code == 201


def test_archive_and_unarchive_project(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)

    resp = client.post(f"/api/v1/projects/{project['id']}/archive", headers=auth_headers(admin_token))
    assert resp.status_code == 200
    assert resp.json()["is_archived"] is True

    active = client.get("/api/v1/projects?archived=false", headers=auth_headers(admin_token)).json()
    assert project["id"] not in [p["id"] for p in active]
    archived = client.get("/api/v1/projects?archived=true", headers=auth_headers(admin_token)).json()
    assert project["id"] in [p["id"] for p in archived]

    resp = client.post(f"/api/v1/projects/{project['id']}/unarchive", headers=auth_headers(admin_token))
    assert resp.status_code == 200
    assert resp.json()["is_archived"] is False


def test_favorite_project_sorts_first_and_toggles(client, admin_token, org_id):
    """U-U-03: favourited projects are flagged and sorted ahead of others."""
    project_a = create_project(client, admin_token, org_id, name="A Project")
    project_b = create_project(client, admin_token, org_id, name="Z Project")

    listing = client.get("/api/v1/projects?archived=false", headers=auth_headers(admin_token)).json()
    assert [p["is_favorite"] for p in listing] == [False, False]
    assert [p["id"] for p in listing] == [project_a["id"], project_b["id"]]  # alphabetical, no favourites

    resp = client.put(f"/api/v1/projects/{project_b['id']}/favorite", headers=auth_headers(admin_token))
    assert resp.status_code == 204

    listing = client.get("/api/v1/projects?archived=false", headers=auth_headers(admin_token)).json()
    assert listing[0]["id"] == project_b["id"]
    assert listing[0]["is_favorite"] is True
    assert listing[1]["is_favorite"] is False

    resp = client.delete(f"/api/v1/projects/{project_b['id']}/favorite", headers=auth_headers(admin_token))
    assert resp.status_code == 204
    listing = client.get("/api/v1/projects?archived=false", headers=auth_headers(admin_token)).json()
    assert all(not p["is_favorite"] for p in listing)


def test_project_list_role_and_stage_status_filters(client, admin_token, org_id):
    """U-E-05: the project list can be filtered by the caller's effective role
    and by the project's current stage status."""
    project = create_project(client, admin_token, org_id, name="Filter Target")

    member_token = _make_member(client, admin_token, org_id, project["id"], "filter_member@example.com")

    manager_only = client.get(
        "/api/v1/projects?archived=false&role=project_manager", headers=auth_headers(admin_token)
    ).json()
    assert project["id"] in [p["id"] for p in manager_only]

    member_as_member_role = client.get(
        "/api/v1/projects?archived=false&role=member", headers=auth_headers(member_token)
    ).json()
    assert project["id"] in [p["id"] for p in member_as_member_role]

    member_as_manager_role = client.get(
        "/api/v1/projects?archived=false&role=project_manager", headers=auth_headers(member_token)
    ).json()
    assert project["id"] not in [p["id"] for p in member_as_manager_role]

    scoping = client.get(
        "/api/v1/projects?archived=false&stage_status=scoping", headers=auth_headers(admin_token)
    ).json()
    assert project["id"] in [p["id"] for p in scoping]

    approved = client.get(
        "/api/v1/projects?archived=false&stage_status=approved", headers=auth_headers(admin_token)
    ).json()
    assert project["id"] not in [p["id"] for p in approved]


def test_terminology_override_rejects_unknown_keys(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    resp = client.put(
        f"/api/v1/projects/{project['id']}/terminology", json={"terminology": {"stage": "Horizon"}},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200
    assert resp.json()["terminology"] == {"stage": "Horizon"}

    resp = client.put(
        f"/api/v1/projects/{project['id']}/terminology", json={"terminology": {"bogus": "x"}},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 422
