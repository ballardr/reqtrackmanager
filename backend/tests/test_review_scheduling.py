"""Tests for Massif (v3) requirement review scheduling (C-R-06..10)."""

from datetime import date, timedelta

from tests.conftest import auth_headers, create_component_and_category, create_project, login


def _create_requirement_with_review(client, token, project_id, component_id, category_id, review_date, **extra):
    resp = client.post(
        f"/api/v1/projects/{project_id}/requirements",
        json={
            "name": "Req with review", "component_id": component_id, "category_id": category_id,
            "review_date": review_date, **extra,
        },
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_requirement_with_past_review_date_appears_on_project_due_list(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    req = _create_requirement_with_review(
        client, admin_token, project["id"], component_id, category_id, str(date.today() - timedelta(days=1)),
    )
    resp = client.get(f"/api/v1/projects/{project['id']}/requirements/reviews/due", headers=auth_headers(admin_token))
    assert resp.status_code == 200
    assert any(r["requirement_id"] == req["id"] for r in resp.json())


def test_future_review_date_does_not_appear_on_due_list(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    req = _create_requirement_with_review(
        client, admin_token, project["id"], component_id, category_id, str(date.today() + timedelta(days=30)),
    )
    resp = client.get(f"/api/v1/projects/{project['id']}/requirements/reviews/due", headers=auth_headers(admin_token))
    assert resp.status_code == 200
    assert not any(r["requirement_id"] == req["id"] for r in resp.json())


def test_recording_review_outcome_drops_requirement_off_due_list(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    req = _create_requirement_with_review(
        client, admin_token, project["id"], component_id, category_id, str(date.today() - timedelta(days=1)),
    )
    resp = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{req['id']}/reviews",
        json={"outcome": "met"}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 201, resp.text

    resp = client.get(f"/api/v1/projects/{project['id']}/requirements/reviews/due", headers=auth_headers(admin_token))
    assert not any(r["requirement_id"] == req["id"] for r in resp.json())


def test_failed_review_outcome_requires_a_comment(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    req = _create_requirement_with_review(
        client, admin_token, project["id"], component_id, category_id, str(date.today()),
    )
    resp = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{req['id']}/reviews",
        json={"outcome": "failed"}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 400

    resp = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{req['id']}/reviews",
        json={"outcome": "failed", "comment": "Regressed under load."}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 201


def test_review_assigned_to_a_user_appears_on_their_personal_due_list(client, admin_token, org_id):
    from tests.conftest import create_org_user

    reviewer_id = create_org_user(client, admin_token, org_id, "reviewer@example.com", role="member")
    project = create_project(client, admin_token, org_id)
    client.post(
        f"/api/v1/projects/{project['id']}/roles",
        json={"user_id": reviewer_id, "role": "stakeholder"}, headers=auth_headers(admin_token),
    )
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    _create_requirement_with_review(
        client, admin_token, project["id"], component_id, category_id,
        str(date.today() - timedelta(days=1)), reviewer_id=reviewer_id,
    )

    reviewer_token = login(client, "reviewer@example.com", "Password123!")
    resp = client.get("/api/v1/me/reviews/due", headers=auth_headers(reviewer_token))
    assert resp.status_code == 200
    assert len(resp.json()) == 1

    resp = client.get("/api/v1/me/reviews/due", headers=auth_headers(admin_token))
    assert resp.json() == []


def test_due_list_includes_reviewer_and_component_names(client, admin_token, org_id):
    """Regression: the UI showed the raw reviewer UUID instead of a name."""
    from tests.conftest import create_org_user

    reviewer_id = create_org_user(client, admin_token, org_id, "named_reviewer@example.com", role="member")
    project = create_project(client, admin_token, org_id)
    client.post(
        f"/api/v1/projects/{project['id']}/roles",
        json={"user_id": reviewer_id, "role": "stakeholder"}, headers=auth_headers(admin_token),
    )
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    _create_requirement_with_review(
        client, admin_token, project["id"], component_id, category_id,
        str(date.today() - timedelta(days=1)), reviewer_id=reviewer_id,
    )

    resp = client.get(f"/api/v1/projects/{project['id']}/requirements/reviews/due", headers=auth_headers(admin_token))
    assert resp.status_code == 200
    row = resp.json()[0]
    assert row["reviewer_name"] == "named_reviewer"
    assert row["reviewer_id"] == reviewer_id
    assert row["component_id"] == component_id
    assert row["component_name"]

    reviewer_token = login(client, "named_reviewer@example.com", "Password123!")
    my_due = client.get("/api/v1/me/reviews/due", headers=auth_headers(reviewer_token)).json()
    assert my_due[0]["component_name"] == row["component_name"]


def test_due_list_filters_by_component_and_reviewer(client, admin_token, org_id):
    from tests.conftest import create_org_user

    reviewer_id = create_org_user(client, admin_token, org_id, "filter_reviewer@example.com", role="member")
    project = create_project(client, admin_token, org_id)
    client.post(
        f"/api/v1/projects/{project['id']}/roles",
        json={"user_id": reviewer_id, "role": "stakeholder"}, headers=auth_headers(admin_token),
    )
    component_a, category_a_id = create_component_and_category(client, admin_token, project["id"])
    component_b = client.post(
        f"/api/v1/projects/{project['id']}/components", json={"name": "Component B", "prefix": "CB"},
        headers=auth_headers(admin_token),
    ).json()["id"]
    # A category is nested under one component (the tree) — component_b
    # needs its own, it can't reuse component_a's.
    category_b_id = client.post(
        f"/api/v1/projects/{project['id']}/categories",
        json={"name": "Performance", "prefix": "PERF", "component_id": component_b},
        headers=auth_headers(admin_token),
    ).json()["id"]

    req_a = _create_requirement_with_review(
        client, admin_token, project["id"], component_a, category_a_id,
        str(date.today() - timedelta(days=1)), reviewer_id=reviewer_id,
    )
    req_b = _create_requirement_with_review(
        client, admin_token, project["id"], component_b, category_b_id, str(date.today() - timedelta(days=1)),
    )

    resp = client.get(
        f"/api/v1/projects/{project['id']}/requirements/reviews/due?component_id={component_a}",
        headers=auth_headers(admin_token),
    )
    ids = {r["requirement_id"] for r in resp.json()}
    assert ids == {req_a["id"]}

    resp = client.get(
        f"/api/v1/projects/{project['id']}/requirements/reviews/due?reviewer_id={reviewer_id}",
        headers=auth_headers(admin_token),
    )
    ids = {r["requirement_id"] for r in resp.json()}
    assert ids == {req_a["id"]}

    resp = client.get(
        f"/api/v1/projects/{project['id']}/requirements/reviews/due?component_id={component_b}",
        headers=auth_headers(admin_token),
    )
    ids = {r["requirement_id"] for r in resp.json()}
    assert ids == {req_b["id"]}


def test_review_date_cannot_be_changed_by_direct_edit_once_requirement_approved(client, admin_token, org_id):
    """C-R-06: review_date can only change on creation or via a change request."""
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    req = _create_requirement_with_review(
        client, admin_token, project["id"], component_id, category_id, str(date.today()),
    )
    client.put(
        f"/api/v1/projects/{project['id']}/requirements/{req['id']}",
        json={
            "name": req["name"], "component_id": component_id, "category_id": category_id,
            "owner_id": req["owner_id"], "status": "approved",
        },
        headers=auth_headers(admin_token),
    )
    resp = client.put(
        f"/api/v1/projects/{project['id']}/requirements/{req['id']}",
        json={
            "name": req["name"], "component_id": component_id, "category_id": category_id,
            "owner_id": req["owner_id"], "review_date": str(date.today() + timedelta(days=5)),
        },
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 409
