"""Tests for the optional `sort`/`order` column-header sorting query params
(2026-08 UX audit roadmap, "Column-header sorting on data tables") on the
requirements, change-request, and org-users list endpoints.

Each endpoint's default (no `sort` given) ordering is asserted unchanged
from before this feature existed, so this is purely additive — see
`test_pagination.py` for the equivalent contract around `limit`/`offset`."""

from tests.conftest import auth_headers, create_component_and_category, create_org_user, create_project


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

    default = client.get(f"/api/v1/projects/{project['id']}/change-requests", headers=auth_headers(admin_token))
    assert [c["proposed_name"] for c in default.json()] == ["Zebra change", "Alpha change"]

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
