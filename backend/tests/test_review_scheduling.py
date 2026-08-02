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
