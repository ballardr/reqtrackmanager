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
    # A modify change request can only target an already-locked requirement
    # (2026-08 UX audit roadmap, "No requirement approval action; change
    # requests can target draft requirements") — approve it directly first.
    approve_resp = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/approve", headers=auth_headers(admin_token)
    )
    assert approve_resp.status_code == 200, approve_resp.text
    cr = client.post(
        f"/api/v1/projects/{project['id']}/change-requests",
        json={
            "kind": "modify_requirement", "requirement_id": requirement["id"],
            "changed_fields": ["name", "reasoning", "clarification"],
            "proposed_name": "The Proposal",
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


def test_project_changes_has_no_duplicate_entries_for_version_bumping_actions(client, admin_token, org_id):
    """Regression (UX review): create/approve/complete/uncomplete/edit each
    used to produce two feed entries for the same transition — one from the
    generic AuditEvent and one from the requirement/CR version history.
    `get_project_changes` now suppresses the redundant AuditEvent row for
    each of these, keeping exactly one entry per transition."""
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    me = client.get("/api/v1/auth/me", headers=auth_headers(admin_token)).json()
    requirement = client.post(
        f"/api/v1/projects/{project['id']}/requirements",
        json={"name": "Req", "component_id": component_id, "category_id": category_id},
        headers=auth_headers(admin_token),
    ).json()

    edit_resp = client.put(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}",
        json={
            "name": "Req edited", "component_id": component_id, "category_id": category_id, "owner_id": me["id"],
        },
        headers=auth_headers(admin_token),
    )
    assert edit_resp.status_code == 200, edit_resp.text
    approve_resp = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/approve", headers=auth_headers(admin_token)
    )
    assert approve_resp.status_code == 200, approve_resp.text
    complete_resp = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/complete", headers=auth_headers(admin_token)
    )
    assert complete_resp.status_code == 200, complete_resp.text
    uncomplete_resp = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/uncomplete", headers=auth_headers(admin_token)
    )
    assert uncomplete_resp.status_code == 200, uncomplete_resp.text

    cr_requirement = client.post(
        f"/api/v1/projects/{project['id']}/requirements",
        json={"name": "CR target", "component_id": component_id, "category_id": category_id},
        headers=auth_headers(admin_token),
    ).json()
    approve_cr_target = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{cr_requirement['id']}/approve", headers=auth_headers(admin_token)
    )
    assert approve_cr_target.status_code == 200, approve_cr_target.text
    cr = client.post(
        f"/api/v1/projects/{project['id']}/change-requests",
        json={
            "kind": "modify_requirement", "requirement_id": cr_requirement["id"],
            "changed_fields": ["name"], "proposed_name": "CR target renamed", "reason": "test",
        },
        headers=auth_headers(admin_token),
    ).json()

    changes = client.get(f"/api/v1/projects/{project['id']}/changes", headers=auth_headers(admin_token)).json()
    req_changes = [c for c in changes if c["entity_type"] == "requirement" and c["entity_id"] == requirement["id"]]
    cr_changes = [c for c in changes if c["entity_type"] == "change_request" and c["entity_id"] == cr["id"]]

    # Exactly one entry per transition, not two (created, then one "updated"
    # per edit/approve/complete/uncomplete — apply_new_version synthesizes
    # "updated" for every non-initial version regardless of the specific
    # action, so all four post-create transitions collapse to "updated").
    assert [c["action"] for c in req_changes].count("created") == 1
    assert [c["action"] for c in req_changes].count("updated") == 4
    assert len(req_changes) == 5

    assert [c["action"] for c in cr_changes].count("created") == 1
    assert len(cr_changes) == 1


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
