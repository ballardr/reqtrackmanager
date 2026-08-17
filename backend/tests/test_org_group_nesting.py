"""Tests for true org-group-in-org-group nesting: cycle prevention, cross-org
rejection, transitive role resolution through a chain of nested groups, and
removal of a nested-group member — a distinct, fully transitive relationship
from the existing (deliberately one-level-deep) org-group-in-project-group
nesting (C-U-12), see docs/decisions.md and services/rbac.py's docstring."""

from tests.conftest import auth_headers, create_org_admin_in, create_org_user, create_project, login


def _create_group(client, admin_token, org_id, name):
    return client.post(
        f"/api/v1/orgs/{org_id}/groups", json={"name": name}, headers=auth_headers(admin_token)
    ).json()


def _nest(client, admin_token, org_id, parent_id, child_id):
    return client.post(
        f"/api/v1/orgs/{org_id}/groups/{parent_id}/members",
        json={"member_org_group_id": child_id}, headers=auth_headers(admin_token),
    )


def test_group_cannot_be_nested_inside_itself(client, admin_token, org_id):
    group = _create_group(client, admin_token, org_id, "Self Nest")
    resp = _nest(client, admin_token, org_id, group["id"], group["id"])
    assert resp.status_code == 400


def test_longer_cycle_is_rejected(client, admin_token, org_id):
    """A contains B; attempting to then nest A inside B must be rejected —
    it would close a loop (A -> B -> A)."""
    group_a = _create_group(client, admin_token, org_id, "Cycle A")
    group_b = _create_group(client, admin_token, org_id, "Cycle B")
    resp = _nest(client, admin_token, org_id, group_a["id"], group_b["id"])
    assert resp.status_code == 204, resp.text

    resp = _nest(client, admin_token, org_id, group_b["id"], group_a["id"])
    assert resp.status_code == 400


def test_deep_cycle_is_rejected(client, admin_token, org_id):
    """A contains B contains C; nesting A inside C must be rejected (it
    would close a longer loop, A -> B -> C -> A)."""
    group_a = _create_group(client, admin_token, org_id, "Deep A")
    group_b = _create_group(client, admin_token, org_id, "Deep B")
    group_c = _create_group(client, admin_token, org_id, "Deep C")
    assert _nest(client, admin_token, org_id, group_a["id"], group_b["id"]).status_code == 204
    assert _nest(client, admin_token, org_id, group_b["id"], group_c["id"]).status_code == 204

    resp = _nest(client, admin_token, org_id, group_c["id"], group_a["id"])
    assert resp.status_code == 400


def test_cannot_nest_org_group_from_another_organization(client, admin_token, org_id):
    other_org, other_admin_token = create_org_admin_in(client, admin_token, "Other Nesting Org")
    other_group = _create_group(client, other_admin_token, other_org["id"], "Foreign Group")
    my_group = _create_group(client, admin_token, org_id, "My Group")

    resp = _nest(client, admin_token, org_id, my_group["id"], other_group["id"])
    assert resp.status_code in (400, 404)


def test_transitive_nesting_grants_effective_project_role_through_a_chain(client, admin_token, org_id):
    """user in C; C nested in B; B nested in A; A nested into a project
    group -> the user must get that project group's effective role, even
    though they're only a *direct* member of the innermost group C."""
    project = create_project(client, admin_token, org_id, "Transitive Nesting Project")
    user_id = create_org_user(client, admin_token, org_id, "deep_nested_member@example.com", role="member")

    group_a = _create_group(client, admin_token, org_id, "Chain A")
    group_b = _create_group(client, admin_token, org_id, "Chain B")
    group_c = _create_group(client, admin_token, org_id, "Chain C")
    assert _nest(client, admin_token, org_id, group_a["id"], group_b["id"]).status_code == 204
    assert _nest(client, admin_token, org_id, group_b["id"], group_c["id"]).status_code == 204
    client.post(
        f"/api/v1/orgs/{org_id}/groups/{group_c['id']}/members",
        json={"user_id": user_id}, headers=auth_headers(admin_token),
    )

    project_group = client.post(
        f"/api/v1/projects/{project['id']}/groups", json={"name": "Chain Stakeholders", "role": "stakeholder"},
        headers=auth_headers(admin_token),
    ).json()
    nested = client.post(
        f"/api/v1/projects/{project['id']}/groups/{project_group['id']}/members",
        json={"org_group_id": group_a["id"]}, headers=auth_headers(admin_token),
    )
    assert nested.status_code == 204, nested.text

    token = login(client, "deep_nested_member@example.com", "Password123!")
    resp = client.get(f"/api/v1/projects/{project['id']}", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text


def test_nested_group_member_can_be_removed(client, admin_token, org_id):
    group_a = _create_group(client, admin_token, org_id, "Removable Parent")
    group_b = _create_group(client, admin_token, org_id, "Removable Child")
    assert _nest(client, admin_token, org_id, group_a["id"], group_b["id"]).status_code == 204

    groups = client.get(f"/api/v1/orgs/{org_id}/groups", headers=auth_headers(admin_token)).json()
    parent = next(g for g in groups if g["id"] == group_a["id"])
    assert group_b["id"] in parent["member_org_group_ids"]

    resp = client.delete(
        f"/api/v1/orgs/{org_id}/groups/{group_a['id']}/members/{group_b['id']}", headers=auth_headers(admin_token)
    )
    assert resp.status_code == 204

    groups = client.get(f"/api/v1/orgs/{org_id}/groups", headers=auth_headers(admin_token)).json()
    parent = next(g for g in groups if g["id"] == group_a["id"])
    assert group_b["id"] not in parent["member_org_group_ids"]


def test_leave_organization_cleanup_is_unaffected_by_nested_groups_present(client, admin_token, org_id):
    """Nested-group edges aren't tied to any one user's membership, so a
    user leaving the org must not disturb them, and the existing
    user-membership cleanup must still work correctly with nesting present."""
    group_a = _create_group(client, admin_token, org_id, "Leave Test Parent")
    group_b = _create_group(client, admin_token, org_id, "Leave Test Child")
    assert _nest(client, admin_token, org_id, group_a["id"], group_b["id"]).status_code == 204

    user_id = create_org_user(client, admin_token, org_id, "leaving_member@example.com", role="member")
    client.post(
        f"/api/v1/orgs/{org_id}/groups/{group_b['id']}/members",
        json={"user_id": user_id}, headers=auth_headers(admin_token),
    )
    token = login(client, "leaving_member@example.com", "Password123!")
    resp = client.delete(f"/api/v1/orgs/{org_id}/membership", headers=auth_headers(token))
    assert resp.status_code == 204

    groups = client.get(f"/api/v1/orgs/{org_id}/groups", headers=auth_headers(admin_token)).json()
    parent = next(g for g in groups if g["id"] == group_a["id"])
    child = next(g for g in groups if g["id"] == group_b["id"])
    assert group_b["id"] in parent["member_org_group_ids"]
    assert user_id not in child["member_user_ids"]
