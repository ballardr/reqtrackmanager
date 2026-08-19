"""Tests for optional `limit`/`offset` pagination (U-P-06) on the
requirements, projects, change-request, project-changes, system-users, and
my-reviews-due list endpoints. Omitting both must still return every match
(C-G-05: no artificial limit is ever imposed unless the caller asks for a
page)."""

from datetime import date, timedelta

from tests.conftest import auth_headers, create_component_and_category, create_org_user, create_project, login


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


def test_project_changes_paginates_and_reports_total(client, admin_token, org_id):
    """The project changes-over-time timeline (C-A-10) — one of the audit's
    two flagged unbounded lists (docs/ux-audit-2026-08.md, "Scale: two
    unbounded lists"). Each created requirement writes a "created"
    RequirementVersion entry (services/changes.py), so five requirements
    guarantee at least five timeline entries to page through."""
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    for i in range(5):
        client.post(
            f"/api/v1/projects/{project['id']}/requirements",
            json={"name": f"Change Req {i}", "component_id": component_id, "category_id": category_id},
            headers=auth_headers(admin_token),
        )

    unpaginated = client.get(f"/api/v1/projects/{project['id']}/changes", headers=auth_headers(admin_token))
    total = len(unpaginated.json())
    assert total >= 5
    assert int(unpaginated.headers["x-total-count"]) == total

    page1 = client.get(
        f"/api/v1/projects/{project['id']}/changes?limit=2&offset=0", headers=auth_headers(admin_token)
    )
    assert len(page1.json()) == 2
    assert int(page1.headers["x-total-count"]) == total

    page2 = client.get(
        f"/api/v1/projects/{project['id']}/changes?limit=2&offset=2", headers=auth_headers(admin_token)
    )
    assert len(page2.json()) == 2
    # No cross-page disjointness assertion here (unlike the requirements-list
    # test above) — entries sort by `timestamp`, and requirements created in
    # a tight loop can land in the same microsecond, so two independent
    # requests aren't guaranteed to agree on tied entries' relative order the
    # way the requirements list's deterministic component/category sort key
    # is. Length and total-count correctness per page is the actual
    # pagination contract under test.


def test_projects_list_favorite_only_filters_to_favourited_projects(client, admin_token, org_id):
    """Powers `FavouritesPage` (docs/ux-audit-2026-08.md's "unify the three
    aggregate list pages" item) — a `favorite_only` filter on the same
    paginated endpoint `ProjectListPage` already uses, rather than a
    separate one, so favouriting gets the same search/pagination for free."""
    kept = create_project(client, admin_token, org_id, "Favourite Project")
    create_project(client, admin_token, org_id, "Not Favourited Project")
    client.put(f"/api/v1/projects/{kept['id']}/favorite", headers=auth_headers(admin_token))

    resp = client.get("/api/v1/projects?archived=false&favorite_only=true", headers=auth_headers(admin_token))
    assert resp.status_code == 200
    names = [p["name"] for p in resp.json()]
    assert names == ["Favourite Project"]


def test_my_reviews_due_paginates_reports_total_and_includes_project_name(client, admin_token, org_id):
    """The cross-project "my reviews due" listing (C-R-09) — unlike its
    project-scoped sibling, this spans every project the reviewer has a
    role on, so each row needs its own `project_name` to be usable at all
    (docs/ux-audit-2026-08.md's "unify the three aggregate list pages")."""
    reviewer_id = create_org_user(client, admin_token, org_id, "paged_reviewer@example.com", role="member")
    reviewer_token = login(client, "paged_reviewer@example.com", "Password123!")

    for i in range(3):
        project = create_project(client, admin_token, org_id, f"Due Review Project {i}")
        client.post(
            f"/api/v1/projects/{project['id']}/roles",
            json={"user_id": reviewer_id, "role": "stakeholder"}, headers=auth_headers(admin_token),
        )
        component_id, category_id = create_component_and_category(client, admin_token, project["id"])
        client.post(
            f"/api/v1/projects/{project['id']}/requirements",
            json={
                "name": f"Req {i}", "component_id": component_id, "category_id": category_id,
                "review_date": str(date.today() - timedelta(days=1)), "reviewer_id": reviewer_id,
            },
            headers=auth_headers(admin_token),
        )

    unpaginated = client.get("/api/v1/me/reviews/due", headers=auth_headers(reviewer_token))
    assert len(unpaginated.json()) == 3
    assert unpaginated.headers["x-total-count"] == "3"
    assert all(row["project_name"] for row in unpaginated.json())

    page1 = client.get("/api/v1/me/reviews/due?limit=2&offset=0", headers=auth_headers(reviewer_token))
    assert len(page1.json()) == 2
    assert page1.headers["x-total-count"] == "3"

    page2 = client.get("/api/v1/me/reviews/due?limit=2&offset=2", headers=auth_headers(reviewer_token))
    assert len(page2.json()) == 1
    assert {r["requirement_id"] for r in page1.json()} & {r["requirement_id"] for r in page2.json()} == set()


def test_system_users_paginates_and_reports_total(client, admin_token, org_id):
    """The server-admin cross-org user directory (C-A-13) — the other of
    the audit's two flagged unbounded lists."""
    for i in range(3):
        create_org_user(client, admin_token, org_id, f"paged_user_{i}@example.com", role="member")

    unpaginated = client.get("/api/v1/system/users", headers=auth_headers(admin_token))
    total = len(unpaginated.json())
    assert total >= 3
    assert int(unpaginated.headers["x-total-count"]) == total

    page = client.get("/api/v1/system/users?limit=2&offset=0", headers=auth_headers(admin_token))
    assert len(page.json()) == 2
    assert int(page.headers["x-total-count"]) == total


def test_org_users_search_and_paginate(client, admin_token, org_id):
    """Org Admin's Users directory (2026-08 UX audit, sixth pass:
    "Directories at scale") — a plain member/project-creator can call this
    unfiltered (existing behaviour), and `search`/`limit`/`offset` stay
    available to them too, unlike the access-review filters."""
    create_org_user(client, admin_token, org_id, "priya.patel@example.com")
    create_org_user(client, admin_token, org_id, "quinn.oshea@example.com")
    for i in range(3):
        create_org_user(client, admin_token, org_id, f"paged_orguser_{i}@example.com")

    unpaginated = client.get(f"/api/v1/orgs/{org_id}/users", headers=auth_headers(admin_token))
    total = len(unpaginated.json())
    assert total >= 5
    assert int(unpaginated.headers["x-total-count"]) == total

    page1 = client.get(f"/api/v1/orgs/{org_id}/users?limit=2&offset=0", headers=auth_headers(admin_token))
    assert len(page1.json()) == 2
    assert int(page1.headers["x-total-count"]) == total
    page2 = client.get(f"/api/v1/orgs/{org_id}/users?limit=2&offset=2", headers=auth_headers(admin_token))
    assert {u["user_id"] for u in page1.json()} & {u["user_id"] for u in page2.json()} == set()

    by_name = client.get(f"/api/v1/orgs/{org_id}/users?search=priya", headers=auth_headers(admin_token))
    assert [u["email"] for u in by_name.json()] == ["priya.patel@example.com"]
    by_email_fragment = client.get(f"/api/v1/orgs/{org_id}/users?search=oshea", headers=auth_headers(admin_token))
    assert [u["email"] for u in by_email_fragment.json()] == ["quinn.oshea@example.com"]


def test_org_groups_search_and_paginate(client, admin_token, org_id):
    """Org Admin's Groups section — same finding, one section down. Also
    checks that a caller who omits `limit` (e.g. Project Admin's own
    org-group nesting picker) still gets every group unpaginated, so
    adding pagination here can't silently break that existing caller."""
    client.post(f"/api/v1/orgs/{org_id}/groups", json={"name": "Finance Reviewers"}, headers=auth_headers(admin_token))
    client.post(f"/api/v1/orgs/{org_id}/groups", json={"name": "Field Engineers"}, headers=auth_headers(admin_token))
    for i in range(3):
        client.post(
            f"/api/v1/orgs/{org_id}/groups", json={"name": f"Paged Group {i}"}, headers=auth_headers(admin_token)
        )

    unpaginated = client.get(f"/api/v1/orgs/{org_id}/groups", headers=auth_headers(admin_token))
    total = len(unpaginated.json())
    assert total >= 5
    assert "x-total-count" not in unpaginated.headers or int(unpaginated.headers["x-total-count"]) == total

    page = client.get(f"/api/v1/orgs/{org_id}/groups?limit=2&offset=0", headers=auth_headers(admin_token))
    assert len(page.json()) == 2
    assert int(page.headers["x-total-count"]) == total

    by_search = client.get(f"/api/v1/orgs/{org_id}/groups?search=finance", headers=auth_headers(admin_token))
    assert [g["name"] for g in by_search.json()] == ["Finance Reviewers"]


def test_project_groups_search_and_paginate(client, admin_token, org_id):
    """Project Admin's Groups tab — the same finding, one level further
    down (a project's own groups rather than an org's)."""
    project = create_project(client, admin_token, org_id)
    client.post(
        f"/api/v1/projects/{project['id']}/groups",
        json={"name": "Safety Reviewers", "role": "stakeholder"}, headers=auth_headers(admin_token),
    )
    for i in range(4):
        client.post(
            f"/api/v1/projects/{project['id']}/groups",
            json={"name": f"Paged Project Group {i}", "role": "member"}, headers=auth_headers(admin_token),
        )

    unpaginated = client.get(f"/api/v1/projects/{project['id']}/groups", headers=auth_headers(admin_token))
    total = len(unpaginated.json())
    # Every project seeds 4 default groups (Managers/Administrators/Stakeholders/Members) on creation.
    assert total >= 5
    assert int(unpaginated.headers["x-total-count"]) == total

    page = client.get(f"/api/v1/projects/{project['id']}/groups?limit=2&offset=0", headers=auth_headers(admin_token))
    assert len(page.json()) == 2
    assert int(page.headers["x-total-count"]) == total

    by_search = client.get(
        f"/api/v1/projects/{project['id']}/groups?search=safety", headers=auth_headers(admin_token)
    )
    assert [g["name"] for g in by_search.json()] == ["Safety Reviewers"]
