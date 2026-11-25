"""Tests for the optional `sort`/`order` column-header sorting query params
 on the
requirements, change-request, and org-users list endpoints.

Each endpoint's default (no `sort` given) ordering is asserted unchanged
from before this feature existed, so this is purely additive — see
`test_pagination.py` for the equivalent contract around `limit`/`offset`.
Exception: change requests now default to newest first; their old default
was unspecified (see that test)."""

from app.database import SessionLocal
from app.models.user import User
from tests.conftest import (
    auth_headers,
    create_component_and_category,
    create_org_admin_in,
    create_org_group,
    create_org_user,
    create_project,
    create_project_group,
)


def test_requirements_list_sorts_by_name_and_status_both_directions(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    for name in ["Charlie", "Alpha", "Bravo"]:
        client.post(
            f"/api/v1/projects/{project['id']}/requirements",
            json={"name": name, "component_id": component_id, "category_id": category_id},
            headers=auth_headers(admin_token),
        )

    default = client.get(f"/api/v1/projects/{project['id']}/requirements", headers=auth_headers(admin_token))
    # Default order is unchanged: creation/component-category order, not alphabetical.
    assert [r["name"] for r in default.json()] == ["Charlie", "Alpha", "Bravo"]

    asc = client.get(
        f"/api/v1/projects/{project['id']}/requirements?sort=name", headers=auth_headers(admin_token)
    )
    assert [r["name"] for r in asc.json()] == ["Alpha", "Bravo", "Charlie"]

    desc = client.get(
        f"/api/v1/projects/{project['id']}/requirements?sort=name&order=desc", headers=auth_headers(admin_token)
    )
    assert [r["name"] for r in desc.json()] == ["Charlie", "Bravo", "Alpha"]

    # All requirements start out "draft", so sorting by status is a no-op on
    # order here, but confirms the query param is accepted and doesn't 422.
    by_status = client.get(
        f"/api/v1/projects/{project['id']}/requirements?sort=status", headers=auth_headers(admin_token)
    )
    assert by_status.status_code == 200
    assert {r["status"] for r in by_status.json()} == {"draft"}

    invalid = client.get(
        f"/api/v1/projects/{project['id']}/requirements?sort=not_a_field", headers=auth_headers(admin_token)
    )
    assert invalid.status_code == 422


def test_change_requests_list_sorts_by_proposed_name(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    for name in ["Zebra change", "Alpha change"]:
        client.post(
            f"/api/v1/projects/{project['id']}/change-requests",
            json={"kind": "new_requirement", "proposed_name": name, "reason": "because"},
            headers=auth_headers(admin_token),
        )

    # The default order is newest first.
    default = client.get(f"/api/v1/projects/{project['id']}/change-requests", headers=auth_headers(admin_token))
    assert [c["proposed_name"] for c in default.json()] == ["Alpha change", "Zebra change"]

    asc = client.get(
        f"/api/v1/projects/{project['id']}/change-requests?sort=proposed_name", headers=auth_headers(admin_token)
    )
    assert [c["proposed_name"] for c in asc.json()] == ["Alpha change", "Zebra change"]

    desc = client.get(
        f"/api/v1/projects/{project['id']}/change-requests?sort=proposed_name&order=desc",
        headers=auth_headers(admin_token),
    )
    assert [c["proposed_name"] for c in desc.json()] == ["Zebra change", "Alpha change"]


def test_org_users_list_sorts_by_email(client, admin_token, org_id):
    create_org_user(client, admin_token, org_id, "zack@example.com")
    create_org_user(client, admin_token, org_id, "amy@example.com")

    default = client.get(f"/api/v1/orgs/{org_id}/users", headers=auth_headers(admin_token))
    # Default is unchanged: sorted by display_name, not email.
    default_emails = [u["email"] for u in default.json()]
    assert default_emails.index("amy@example.com") is not None  # sanity: both present
    assert set(["zack@example.com", "amy@example.com"]).issubset(set(default_emails))

    asc = client.get(f"/api/v1/orgs/{org_id}/users?sort=email", headers=auth_headers(admin_token))
    emails = [u["email"] for u in asc.json()]
    assert emails.index("amy@example.com") < emails.index("zack@example.com")

    desc = client.get(f"/api/v1/orgs/{org_id}/users?sort=email&order=desc", headers=auth_headers(admin_token))
    emails_desc = [u["email"] for u in desc.json()]
    assert emails_desc.index("zack@example.com") < emails_desc.index("amy@example.com")

    invalid = client.get(f"/api/v1/orgs/{org_id}/users?sort=password", headers=auth_headers(admin_token))
    assert invalid.status_code == 422


def test_org_users_list_sorts_by_roles_status_and_two_factor(client, admin_token):
    """`roles` orders by the joined role names the column shows, `status` by Active/Archived/Deactivated and `2fa`
    by without before with; equal values keep the name order, in both directions."""
    org, org_admin_token = create_org_admin_in(client, admin_token, "Derived Sort Org")
    headers = auth_headers(org_admin_token)
    create_org_user(client, org_admin_token, org["id"], "member.derived@example.com", role="member")
    creator_id = create_org_user(client, org_admin_token, org["id"], "creator.derived@example.com", role="project_creator")
    gone_id = create_org_user(client, org_admin_token, org["id"], "gone.derived@example.com", role="member")
    assert client.post(f"/api/v1/orgs/{org['id']}/users/{gone_id}/deactivate", headers=headers).status_code == 204
    db = SessionLocal()
    try:
        db.query(User).filter(User.id == creator_id).update({"is_2fa_enabled": True})
        db.commit()
    finally:
        db.close()

    def emails(sort: str, order: str) -> list[str]:
        resp = client.get(f"/api/v1/orgs/{org['id']}/users?search=derived&sort={sort}&order={order}", headers=headers)
        assert resp.status_code == 200, resp.text
        return [u["email"] for u in resp.json()]

    admin = "derived_sort_org_admin@example.com"
    member, creator, gone = "member.derived@example.com", "creator.derived@example.com", "gone.derived@example.com"
    assert emails("roles", "asc") == [gone, member, admin, creator]
    assert emails("roles", "desc") == [creator, admin, gone, member]
    assert emails("status", "asc") == [creator, member, admin, gone]
    assert emails("status", "desc") == [gone, creator, member, admin]
    assert emails("2fa", "asc") == [gone, member, admin, creator]
    assert emails("2fa", "desc") == [creator, gone, member, admin]


def test_org_groups_list_sorts_by_members(client, admin_token, org_id):
    """`sort=members` orders groups by their user-member count, ties by name; `name` stays the default."""
    users = [create_org_user(client, admin_token, org_id, f"grp{i}.sortmembers@example.com") for i in range(3)]
    create_org_group(client, admin_token, org_id, "SortGroup Alpha", users=users[:1])
    create_org_group(client, admin_token, org_id, "SortGroup Beta", users=users)
    create_org_group(client, admin_token, org_id, "SortGroup Gamma")

    def names(query: str) -> list[str]:
        resp = client.get(f"/api/v1/orgs/{org_id}/groups?search=SortGroup&{query}", headers=auth_headers(admin_token))
        assert resp.status_code == 200, resp.text
        return [g["name"] for g in resp.json()]

    assert names("sort=members&order=asc") == ["SortGroup Gamma", "SortGroup Alpha", "SortGroup Beta"]
    assert names("sort=members&order=desc") == ["SortGroup Beta", "SortGroup Alpha", "SortGroup Gamma"]
    assert names("order=desc") == ["SortGroup Gamma", "SortGroup Beta", "SortGroup Alpha"]
    assert client.get(f"/api/v1/orgs/{org_id}/groups?sort=password", headers=auth_headers(admin_token)).status_code == 422


def test_project_groups_list_sorts_by_roles_and_members(client, admin_token, org_id):
    """`sort=roles` orders groups by the joined role names (a group with none last ascending); `sort=members` by
    their user-member count."""
    project = create_project(client, admin_token, org_id)
    users = [create_org_user(client, admin_token, org_id, f"pg{i}.sortmembers@example.com") for i in range(2)]
    alpha = create_project_group(client, admin_token, project["id"], "Alpha", users=users[:1])
    beta = create_project_group(client, admin_token, project["id"], "Beta")
    create_project_group(client, admin_token, project["id"], "Gamma", users=users)
    for group_id, role in ((alpha, "stakeholder"), (beta, "project_manager")):
        resp = client.post(
            f"/api/v1/projects/{project['id']}/groups/{group_id}/roles", json={"role": role}, headers=auth_headers(admin_token)
        )
        assert resp.status_code == 204, resp.text

    def names(query: str) -> list[str]:
        resp = client.get(f"/api/v1/projects/{project['id']}/groups?{query}", headers=auth_headers(admin_token))
        assert resp.status_code == 200, resp.text
        return [g["name"] for g in resp.json()]

    assert names("sort=roles&order=asc") == ["Beta", "Alpha", "Gamma"]
    assert names("sort=roles&order=desc") == ["Gamma", "Alpha", "Beta"]
    assert names("sort=members&order=asc") == ["Beta", "Alpha", "Gamma"]
    assert names("sort=members&order=desc") == ["Gamma", "Alpha", "Beta"]
    assert names("") == ["Alpha", "Beta", "Gamma"]
    assert client.get(f"/api/v1/projects/{project['id']}/groups?sort=password", headers=auth_headers(admin_token)).status_code == 422
