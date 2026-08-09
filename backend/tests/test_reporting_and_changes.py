"""Tests for the project changes-over-time view (C-A-10) and report filters/
sections (R-G-03, R-G-04)."""

from tests.conftest import auth_headers, create_component_and_category, create_org_admin_in, create_project


def test_project_changes_excludes_comments_by_default(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    requirement = client.post(
        f"/api/v1/projects/{project['id']}/requirements",
        json={"name": "Req", "component_id": component_id, "category_id": category_id},
        headers=auth_headers(admin_token),
    ).json()
    client.post(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/comments",
        json={"body": "a discussion comment"}, headers=auth_headers(admin_token),
    )

    changes = client.get(f"/api/v1/projects/{project['id']}/changes", headers=auth_headers(admin_token)).json()
    assert any(c["entity_type"] == "requirement" and c["action"] == "created" for c in changes)
    assert not any(c["action"] == "comment_added" for c in changes)

    changes_with_comments = client.get(
        f"/api/v1/projects/{project['id']}/changes?include_comments=true", headers=auth_headers(admin_token)
    ).json()
    assert any(c["action"] == "comment_added" for c in changes_with_comments)


def test_project_changes_time_filter(client, admin_token, org_id):
    import datetime

    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    client.post(
        f"/api/v1/projects/{project['id']}/requirements",
        json={"name": "Req", "component_id": component_id, "category_id": category_id},
        headers=auth_headers(admin_token),
    )

    future = (datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=1)).isoformat()
    changes = client.get(
        f"/api/v1/projects/{project['id']}/changes", params={"since": future}, headers=auth_headers(admin_token)
    ).json()
    assert changes == []


def test_requirement_activity_entries_always_carry_current_id_and_title(client, admin_token, org_id):
    """Regression: an AuditEvent-sourced entry (e.g. "archived") never had
    `unique_code`/a title in `detail` at all — only entries sourced from
    requirement version history did. `get_project_changes` now resolves
    both, from *current* state, for every requirement-entity entry
    regardless of source."""
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    requirement = client.post(
        f"/api/v1/projects/{project['id']}/requirements",
        json={"name": "Original Name", "component_id": component_id, "category_id": category_id},
        headers=auth_headers(admin_token),
    ).json()
    me = client.get("/api/v1/auth/me", headers=auth_headers(admin_token)).json()

    # Rename it via a direct edit, then archive it — "archived" is logged
    # via plain log_event() with no detail at all (see routers/requirements.py).
    put_resp = client.put(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}",
        json={
            "name": "Renamed", "component_id": component_id, "category_id": category_id, "owner_id": me["id"],
        },
        headers=auth_headers(admin_token),
    )
    assert put_resp.status_code == 200, put_resp.text
    archive_resp = client.delete(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}", headers=auth_headers(admin_token)
    )
    assert archive_resp.status_code == 204, archive_resp.text

    changes = client.get(f"/api/v1/projects/{project['id']}/changes", headers=auth_headers(admin_token)).json()
    archived_entry = next(c for c in changes if c["entity_type"] == "requirement" and c["action"] == "archived")
    assert archived_entry["detail"]["unique_code"] == requirement["unique_code"]
    # Current name (post-rename), not the name at creation time.
    assert archived_entry["detail"]["name"] == "Renamed"


def test_change_request_activity_entries_always_carry_current_title(client, admin_token, org_id):
    """Regression: "submitted"/"withdrawn" are logged via plain log_event()
    with no `proposed_name` in `detail` at all — only the "created" entry
    (sourced from version history) had it before this fix."""
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    requirement = client.post(
        f"/api/v1/projects/{project['id']}/requirements",
        json={"name": "Req", "component_id": component_id, "category_id": category_id},
        headers=auth_headers(admin_token),
    ).json()
    cr = client.post(
        f"/api/v1/projects/{project['id']}/change-requests",
        json={
            "kind": "modify_requirement", "requirement_id": requirement["id"], "proposed_name": "The Proposal",
            "proposed_reasoning": "x", "proposed_clarification": "", "reason": "test",
        },
        headers=auth_headers(admin_token),
    ).json()
    submit_resp = client.post(
        f"/api/v1/projects/{project['id']}/change-requests/{cr['id']}/submit", headers=auth_headers(admin_token)
    )
    assert submit_resp.status_code == 200, submit_resp.text

    changes = client.get(f"/api/v1/projects/{project['id']}/changes", headers=auth_headers(admin_token)).json()
    submitted_entry = next(c for c in changes if c["entity_type"] == "change_request" and c["action"] == "submitted")
    assert submitted_entry["detail"]["proposed_name"] == "The Proposal"


def test_report_filters_by_status_and_component(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    other_component = client.post(
        f"/api/v1/projects/{project['id']}/components", json={"name": "Hardware", "prefix": "HW"},
        headers=auth_headers(admin_token),
    ).json()

    client.post(
        f"/api/v1/projects/{project['id']}/requirements",
        json={"name": "Software req", "component_id": component_id, "category_id": category_id},
        headers=auth_headers(admin_token),
    )
    client.post(
        f"/api/v1/projects/{project['id']}/requirements",
        json={"name": "Hardware req", "component_id": other_component["id"], "category_id": category_id},
        headers=auth_headers(admin_token),
    )

    resp = client.post(
        f"/api/v1/projects/{project['id']}/reports/csv",
        json={"component_id": component_id}, headers=auth_headers(admin_token),
    )
    text = resp.content.decode("utf-8")
    assert "Software req" in text
    assert "Hardware req" not in text


def test_report_includes_org_shared_resource_section(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    client.post(
        f"/api/v1/projects/{project['id']}/requirements",
        json={"name": "Req", "component_id": component_id, "category_id": category_id},
        headers=auth_headers(admin_token),
    )
    resource = client.post(
        f"/api/v1/orgs/{org_id}/resources",
        files={"file": ("appendix.txt", b"Standard appendix content.", "text/plain")},
        headers=auth_headers(admin_token),
    ).json()

    resp = client.post(
        f"/api/v1/projects/{project['id']}/reports/pdf",
        json={"resource_file_ids": [resource["id"]]}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200
    assert resp.content[:5] == b"%PDF-"


def test_report_rejects_resource_from_another_organization(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    other_org, other_org_admin_token = create_org_admin_in(client, admin_token, "Other Org 2")
    other_resource = client.post(
        f"/api/v1/orgs/{other_org['id']}/resources",
        files={"file": ("x.txt", b"data", "text/plain")}, headers=auth_headers(other_org_admin_token),
    ).json()

    resp = client.post(
        f"/api/v1/projects/{project['id']}/reports/pdf",
        json={"resource_file_ids": [other_resource["id"]]}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 400
