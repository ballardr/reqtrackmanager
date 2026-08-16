"""Tests for the self-service "my groups & roles" endpoint
(GET /auth/me/memberships) — org roles, direct + inherited org-group
membership, and per-project roles across every org the caller belongs to."""

from app.database import SessionLocal
from app.models.organization import OrgGroupMember
from tests.conftest import auth_headers, create_org_admin_in, create_org_user, create_project, login


def test_my_memberships_includes_org_role_group_and_project_role(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id, "Memberships Project")
    user_id = create_org_user(client, admin_token, org_id, "memberships_member@example.com", role="member")
    client.post(
        f"/api/v1/projects/{project['id']}/roles", json={"user_id": user_id, "role": "stakeholder"},
        headers=auth_headers(admin_token),
    )
    group = client.post(
        f"/api/v1/orgs/{org_id}/groups", json={"name": "Memberships Group"}, headers=auth_headers(admin_token)
    ).json()
    client.post(
        f"/api/v1/orgs/{org_id}/groups/{group['id']}/members", json={"user_id": user_id},
        headers=auth_headers(admin_token),
    )

    token = login(client, "memberships_member@example.com", "Password123!")
    resp = client.get("/api/v1/auth/me/memberships", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["organizations"]) == 1
    org_membership = body["organizations"][0]
    assert org_membership["organization_id"] == org_id
    assert "member" in org_membership["org_roles"]
    assert {"id": group["id"], "name": "Memberships Group", "direct": True} in org_membership["groups"]
    project_entry = next(p for p in org_membership["projects"] if p["id"] == project["id"])
    assert "stakeholder" in project_entry["roles"]


def test_my_memberships_marks_transitively_inherited_groups_as_not_direct(client, admin_token, org_id):
    user_id = create_org_user(client, admin_token, org_id, "inherited_member@example.com", role="member")
    parent = client.post(
        f"/api/v1/orgs/{org_id}/groups", json={"name": "Inherited Parent"}, headers=auth_headers(admin_token)
    ).json()
    child = client.post(
        f"/api/v1/orgs/{org_id}/groups", json={"name": "Inherited Child"}, headers=auth_headers(admin_token)
    ).json()
    client.post(
        f"/api/v1/orgs/{org_id}/groups/{parent['id']}/members", json={"member_org_group_id": child["id"]},
        headers=auth_headers(admin_token),
    )
    client.post(
        f"/api/v1/orgs/{org_id}/groups/{child['id']}/members", json={"user_id": user_id},
        headers=auth_headers(admin_token),
    )

    token = login(client, "inherited_member@example.com", "Password123!")
    resp = client.get("/api/v1/auth/me/memberships", headers=auth_headers(token))
    groups_by_id = {g["id"]: g for g in resp.json()["organizations"][0]["groups"]}
    assert groups_by_id[child["id"]]["direct"] is True
    assert groups_by_id[parent["id"]]["direct"] is False


def test_my_memberships_only_includes_orgs_the_caller_belongs_to(client, admin_token, org_id):
    resp = client.get("/api/v1/auth/me/memberships", headers=auth_headers(admin_token))
    assert resp.status_code == 200
    org_ids = {o["organization_id"] for o in resp.json()["organizations"]}
    assert org_id in org_ids
    assert len(org_ids) == 1


def test_my_memberships_ancestor_closure_never_leaks_a_cross_org_group_name(client, admin_token, org_id):
    """Hardening-review finding (defense in depth): `add_org_group_member`
    already rejects nesting an org group from a different organisation at
    write time, so this should be unreachable through the real API — but
    `services.rbac._ancestor_org_group_ids` itself walks `OrgGroupMember`
    with no organisation filter, and `get_user_org_group_ids` (backing this
    endpoint) had no downstream re-check either, unlike the equivalent
    project-role resolution in `get_effective_project_roles`, which does
    re-join on `OrgGroup.organization_id` even though the same write-time
    check already applies there. Simulates the invariant being violated by
    inserting a cross-org nesting edge directly (bypassing the API, the
    only way to construct this state at all) and confirms the foreign
    organisation's group is never attributed to this org's membership
    entry."""
    other_org, other_admin_token = create_org_admin_in(client, admin_token, "Cross-Org Leak Org")
    user_id = create_org_user(client, admin_token, org_id, "leak_check_member@example.com", role="member")
    my_group = client.post(
        f"/api/v1/orgs/{org_id}/groups", json={"name": "Leak Check Group"}, headers=auth_headers(admin_token)
    ).json()
    client.post(
        f"/api/v1/orgs/{org_id}/groups/{my_group['id']}/members", json={"user_id": user_id},
        headers=auth_headers(admin_token),
    )
    foreign_group = client.post(
        f"/api/v1/orgs/{other_org['id']}/groups", json={"name": "Foreign Org Group"},
        headers=auth_headers(other_admin_token),
    ).json()

    db = SessionLocal()
    try:
        # Bypasses the API's own cross-org rejection to construct the state
        # a bug elsewhere would need to produce for this to matter at all.
        db.add(OrgGroupMember(org_group_id=foreign_group["id"], member_org_group_id=my_group["id"]))
        db.commit()
    finally:
        db.close()

    token = login(client, "leak_check_member@example.com", "Password123!")
    resp = client.get("/api/v1/auth/me/memberships", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    org_membership = next(o for o in resp.json()["organizations"] if o["organization_id"] == org_id)
    group_names = {g["name"] for g in org_membership["groups"]}
    assert group_names == {"Leak Check Group"}
    assert "Foreign Org Group" not in group_names
