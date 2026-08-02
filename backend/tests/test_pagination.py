"""Tests for optional `limit`/`offset` pagination (U-P-06) on the
requirements, projects, and change-request list endpoints. Omitting both
must still return every match (C-G-05: no artificial limit is ever imposed
unless the caller asks for a page)."""

from tests.conftest import auth_headers, create_component_and_category, create_project


def test_requirements_list_paginates_and_reports_total(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    for i in range(5):
        client.post(
            f"/api/v1/projects/{project['id']}/requirements",
            json={"name": f"Req {i}", "component_id": component_id, "category_id": category_id},
            headers=auth_headers(admin_token),
        )

    unpaginated = client.get(f"/api/v1/projects/{project['id']}/requirements", headers=auth_headers(admin_token))
    assert len(unpaginated.json()) == 5
    assert unpaginated.headers["x-total-count"] == "5"

    page1 = client.get(
        f"/api/v1/projects/{project['id']}/requirements?limit=2&offset=0", headers=auth_headers(admin_token)
    )
    assert len(page1.json()) == 2
    assert page1.headers["x-total-count"] == "5"

    page2 = client.get(
        f"/api/v1/projects/{project['id']}/requirements?limit=2&offset=2", headers=auth_headers(admin_token)
    )
    assert len(page2.json()) == 2
    assert {r["id"] for r in page1.json()} & {r["id"] for r in page2.json()} == set()

    page3 = client.get(
        f"/api/v1/projects/{project['id']}/requirements?limit=2&offset=4", headers=auth_headers(admin_token)
    )
    assert len(page3.json()) == 1


def test_projects_list_paginates_and_reports_total(client, admin_token, org_id):
    for i in range(3):
        create_project(client, admin_token, org_id, f"Paged Project {i}")

    page = client.get("/api/v1/projects?archived=false&limit=1&offset=0", headers=auth_headers(admin_token))
    assert len(page.json()) == 1
    assert int(page.headers["x-total-count"]) >= 3


def test_change_requests_list_paginates_and_reports_total(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    for i in range(3):
        client.post(
            f"/api/v1/projects/{project['id']}/change-requests",
            json={"kind": "new_requirement", "proposed_name": f"CR {i}", "reason": "because"},
            headers=auth_headers(admin_token),
        )

    page = client.get(
        f"/api/v1/projects/{project['id']}/change-requests?limit=2&offset=0", headers=auth_headers(admin_token)
    )
    assert len(page.json()) == 2
    assert page.headers["x-total-count"] == "3"
