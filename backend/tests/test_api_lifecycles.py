"""Full create -> read -> update -> remove lifecycle tests for the API
resources that don't already get this treatment elsewhere in the suite.
"Remove" means different things for different resources by design (see
docs/decisions.md): most domain entities are soft-deleted/archived rather
than hard-deleted, to preserve audit history (C-A-06); a few (organisations,
project components/categories, groups themselves) have no removal endpoint
at all, which each test below notes explicitly rather than silently skipping
it."""

from tests.conftest import (
    auth_headers,
    create_component_and_category,
    create_org_user,
    create_project,
)


def test_organization_create_and_get_lifecycle(client, admin_token):
    """Organisations have no delete/archive endpoint at all (by design -
    they are the top-level tenant boundary); this covers create + both
    read paths (list and single)."""
    resp = client.post("/api/v1/orgs", json={"name": "Lifecycle Org"}, headers=auth_headers(admin_token))
    assert resp.status_code == 201, resp.text
    org = resp.json()
    assert org["name"] == "Lifecycle Org"

    listing = client.get("/api/v1/orgs", headers=auth_headers(admin_token)).json()
    assert org["id"] in [o["id"] for o in listing]

    single = client.get(f"/api/v1/orgs/{org['id']}", headers=auth_headers(admin_token))
    assert single.status_code == 200
    assert single.json()["name"] == "Lifecycle Org"


def test_requirement_full_lifecycle_create_get_update_delete(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])

    created = client.post(
        f"/api/v1/projects/{project['id']}/requirements",
        json={"name": "Lifecycle requirement", "component_id": component_id, "category_id": category_id},
        headers=auth_headers(admin_token),
    )
    assert created.status_code == 201, created.text
    requirement_id = created.json()["id"]

    fetched = client.get(
        f"/api/v1/projects/{project['id']}/requirements/{requirement_id}", headers=auth_headers(admin_token)
    )
    assert fetched.status_code == 200
    assert fetched.json()["name"] == "Lifecycle requirement"

    me = client.get("/api/v1/auth/me", headers=auth_headers(admin_token)).json()
    updated = client.put(
        f"/api/v1/projects/{project['id']}/requirements/{requirement_id}",
        json={
            "name": "Lifecycle requirement (updated)", "reasoning": "", "clarification": "",
            "component_id": component_id, "category_id": category_id, "keywords": [], "custom_fields": {},
            "owner_id": me["id"],
        },
        headers=auth_headers(admin_token),
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["name"] == "Lifecycle requirement (updated)"

    deleted = client.delete(
        f"/api/v1/projects/{project['id']}/requirements/{requirement_id}", headers=auth_headers(admin_token)
    )
    assert deleted.status_code == 204

    after_delete = client.get(
        f"/api/v1/projects/{project['id']}/requirements/{requirement_id}", headers=auth_headers(admin_token)
    )
    assert after_delete.status_code == 200  # archiving is a soft-delete: the record still reads back
    assert after_delete.json()["is_archived"] is True

    active_list = client.get(
        f"/api/v1/projects/{project['id']}/requirements", headers=auth_headers(admin_token)
    ).json()
    assert requirement_id not in [r["id"] for r in active_list]


def test_change_request_full_lifecycle_create_get_submit_withdraw(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)

    created = client.post(
        f"/api/v1/projects/{project['id']}/change-requests",
        json={"kind": "new_requirement", "proposed_name": "Lifecycle CR", "reason": "Testing the lifecycle"},
        headers=auth_headers(admin_token),
    )
    assert created.status_code == 201, created.text
    cr_id = created.json()["id"]
    assert created.json()["status"] == "draft"

    fetched = client.get(
        f"/api/v1/projects/{project['id']}/change-requests/{cr_id}", headers=auth_headers(admin_token)
    )
    assert fetched.status_code == 200
    assert fetched.json()["proposed_name"] == "Lifecycle CR"

    listing = client.get(f"/api/v1/projects/{project['id']}/change-requests", headers=auth_headers(admin_token)).json()
    assert cr_id in [cr["id"] for cr in listing]

    submitted = client.post(
        f"/api/v1/projects/{project['id']}/change-requests/{cr_id}/submit", headers=auth_headers(admin_token)
    )
    assert submitted.status_code == 200
    assert submitted.json()["status"] == "submitted"

    # Withdrawing is the closest thing to "delete" a change request has —
    # there is no hard-delete endpoint, since the record must stay for audit.
    withdrawn = client.post(
        f"/api/v1/projects/{project['id']}/change-requests/{cr_id}/withdraw", headers=auth_headers(admin_token)
    )
    assert withdrawn.status_code == 200
    assert withdrawn.json()["status"] == "withdrawn"

    # A withdrawn change request cannot be submitted again.
    resubmit = client.post(
        f"/api/v1/projects/{project['id']}/change-requests/{cr_id}/submit", headers=auth_headers(admin_token)
    )
    assert resubmit.status_code == 409


def test_change_request_comment_lifecycle(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    cr = client.post(
        f"/api/v1/projects/{project['id']}/change-requests",
        json={"kind": "new_requirement", "proposed_name": "Commented CR", "reason": "x"},
        headers=auth_headers(admin_token),
    ).json()

    posted = client.post(
        f"/api/v1/projects/{project['id']}/change-requests/{cr['id']}/comments",
        json={"body": "Looks good to me"},
        headers=auth_headers(admin_token),
    )
    assert posted.status_code == 201, posted.text

    listed = client.get(
        f"/api/v1/projects/{project['id']}/change-requests/{cr['id']}/comments", headers=auth_headers(admin_token)
    )
    assert listed.status_code == 200
    assert any(c["body"] == "Looks good to me" for c in listed.json())


def test_org_group_lifecycle_create_get_member_add_remove(client, admin_token, org_id):
    """Org groups themselves have no delete endpoint (by design); this
    covers create, list, and the member add/remove lifecycle."""
    created = client.post(
        f"/api/v1/orgs/{org_id}/groups", json={"name": "Lifecycle Group"}, headers=auth_headers(admin_token)
    )
    assert created.status_code == 201, created.text
    group_id = created.json()["id"]

    listing = client.get(f"/api/v1/orgs/{org_id}/groups", headers=auth_headers(admin_token)).json()
    assert group_id in [g["id"] for g in listing]

    member_id = create_org_user(client, admin_token, org_id, "group_member@example.com")
    added = client.post(
        f"/api/v1/orgs/{org_id}/groups/{group_id}/members", json={"user_id": member_id},
        headers=auth_headers(admin_token),
    )
    assert added.status_code == 204

    after_add = client.get(f"/api/v1/orgs/{org_id}/groups", headers=auth_headers(admin_token)).json()
    group_after_add = next(g for g in after_add if g["id"] == group_id)
    assert member_id in group_after_add["member_user_ids"]

    removed = client.delete(
        f"/api/v1/orgs/{org_id}/groups/{group_id}/members/{member_id}", headers=auth_headers(admin_token)
    )
    assert removed.status_code == 204

    after_remove = client.get(f"/api/v1/orgs/{org_id}/groups", headers=auth_headers(admin_token)).json()
    group_after_remove = next(g for g in after_remove if g["id"] == group_id)
    assert member_id not in group_after_remove["member_user_ids"]


def test_project_group_lifecycle_create_get_member_add_remove(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)

    created = client.post(
        f"/api/v1/projects/{project['id']}/groups", json={"name": "Custom Group"},
        headers=auth_headers(admin_token),
    )
    assert created.status_code == 201, created.text
    group_id = created.json()["id"]

    listing = client.get(f"/api/v1/projects/{project['id']}/groups", headers=auth_headers(admin_token)).json()
    assert group_id in [g["id"] for g in listing]

    member_id = create_org_user(client, admin_token, org_id, "proj_group_member@example.com")
    added = client.post(
        f"/api/v1/projects/{project['id']}/groups/{group_id}/members", json={"user_id": member_id},
        headers=auth_headers(admin_token),
    )
    assert added.status_code == 204

    removed = client.delete(
        f"/api/v1/projects/{project['id']}/groups/{group_id}/members/{member_id}", headers=auth_headers(admin_token)
    )
    assert removed.status_code == 204

    after_remove = client.get(f"/api/v1/projects/{project['id']}/groups", headers=auth_headers(admin_token)).json()
    group_after_remove = next(g for g in after_remove if g["id"] == group_id)
    assert member_id not in group_after_remove["member_user_ids"]


def test_project_stage_lifecycle_create_get_transition(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)

    created = client.post(
        f"/api/v1/projects/{project['id']}/stages", json={"name": "Review"}, headers=auth_headers(admin_token)
    )
    assert created.status_code == 201, created.text
    stage_id = created.json()["id"]
    assert created.json()["status"] == "scoping"

    listing = client.get(f"/api/v1/projects/{project['id']}/stages", headers=auth_headers(admin_token)).json()
    assert stage_id in [s["id"] for s in listing]

    transitioned = client.post(
        f"/api/v1/projects/{project['id']}/stages/{stage_id}/transition?new_status=review",
        headers=auth_headers(admin_token),
    )
    assert transitioned.status_code == 200, transitioned.text
    assert transitioned.json()["status"] == "review"


def test_stage_transition_rejects_skipping_and_backwards_moves(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    stage_id = client.get(f"/api/v1/projects/{project['id']}/stages", headers=auth_headers(admin_token)).json()[0]["id"]

    skip = client.post(
        f"/api/v1/projects/{project['id']}/stages/{stage_id}/transition?new_status=approved",
        headers=auth_headers(admin_token),
    )
    assert skip.status_code == 409, skip.text

    skip_to_completed = client.post(
        f"/api/v1/projects/{project['id']}/stages/{stage_id}/transition?new_status=completed",
        headers=auth_headers(admin_token),
    )
    assert skip_to_completed.status_code == 409, skip_to_completed.text

    review = client.post(
        f"/api/v1/projects/{project['id']}/stages/{stage_id}/transition?new_status=review",
        headers=auth_headers(admin_token),
    )
    assert review.status_code == 200, review.text

    approved = client.post(
        f"/api/v1/projects/{project['id']}/stages/{stage_id}/transition?new_status=approved",
        headers=auth_headers(admin_token),
    )
    assert approved.status_code == 200, approved.text

    backwards = client.post(
        f"/api/v1/projects/{project['id']}/stages/{stage_id}/transition?new_status=scoping",
        headers=auth_headers(admin_token),
    )
    assert backwards.status_code == 409, backwards.text

    # ARCHIVED remains reachable from any non-terminal status regardless of
    # the forward-only rule (see StageStatus's own docstring).
    archived = client.post(
        f"/api/v1/projects/{project['id']}/stages/{stage_id}/transition?new_status=archived",
        headers=auth_headers(admin_token),
    )
    assert archived.status_code == 200, archived.text


def test_org_user_deactivate_then_archive_lifecycle(client, admin_token, org_id):
    """A user's removal from an org is two explicit steps (C-U-04, C-U-05):
    deactivate (can no longer log in, but still visible/attributed) then
    archive (hidden from user lists, still attributed). This is the
    resource's "delete" equivalent."""
    user_id = create_org_user(client, admin_token, org_id, "removable_user@example.com")

    listing = client.get(f"/api/v1/orgs/{org_id}/users", headers=auth_headers(admin_token)).json()
    assert user_id in [u["user_id"] for u in listing]

    deactivated = client.post(
        f"/api/v1/orgs/{org_id}/users/{user_id}/deactivate", headers=auth_headers(admin_token)
    )
    assert deactivated.status_code == 204

    login_after_deactivate = client.post(
        "/api/v1/auth/login", json={"email": "removable_user@example.com", "password": "Password123!"}
    )
    assert login_after_deactivate.status_code == 401

    still_listed = client.get(f"/api/v1/orgs/{org_id}/users", headers=auth_headers(admin_token)).json()
    deactivated_entry = next(u for u in still_listed if u["user_id"] == user_id)
    assert deactivated_entry["is_active"] is False

    archived = client.post(f"/api/v1/orgs/{org_id}/users/{user_id}/archive", headers=auth_headers(admin_token))
    assert archived.status_code == 204

    after_archive = client.get(f"/api/v1/orgs/{org_id}/users", headers=auth_headers(admin_token)).json()
    assert user_id not in [u["user_id"] for u in after_archive]


def test_archiving_org_user_before_deactivation_is_rejected(client, admin_token, org_id):
    user_id = create_org_user(client, admin_token, org_id, "still_active@example.com")
    resp = client.post(f"/api/v1/orgs/{org_id}/users/{user_id}/archive", headers=auth_headers(admin_token))
    assert resp.status_code == 400
