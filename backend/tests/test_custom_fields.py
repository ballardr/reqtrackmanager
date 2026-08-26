"""Tests for per-project custom attribute definitions and values (C-C-01, C-C-02)."""

from tests.conftest import auth_headers, create_component_and_category, create_project


def test_create_custom_field_and_require_it_on_requirement(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])

    field = client.post(
        f"/api/v1/projects/{project['id']}/custom-fields",
        json={"entity_kind": "requirement", "name": "Priority", "field_type": "list", "options": ["low", "high"], "required": True},
        headers=auth_headers(admin_token),
    )
    assert field.status_code == 201
    field_id = field.json()["id"]

    # Missing required field is rejected.
    resp = client.post(
        f"/api/v1/projects/{project['id']}/requirements",
        json={"name": "Req", "component_id": component_id, "category_id": category_id},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 400

    # Invalid option value is rejected.
    resp = client.post(
        f"/api/v1/projects/{project['id']}/requirements",
        json={
            "name": "Req", "component_id": component_id, "category_id": category_id,
            "custom_fields": {field_id: "medium"},
        },
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 400

    # Valid value is accepted and stored.
    resp = client.post(
        f"/api/v1/projects/{project['id']}/requirements",
        json={
            "name": "Req", "component_id": component_id, "category_id": category_id,
            "custom_fields": {field_id: "high"},
        },
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 201
    assert resp.json()["custom_fields"] == {field_id: "high"}


def test_change_request_approval_carries_custom_fields_to_requirement(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    field = client.post(
        f"/api/v1/projects/{project['id']}/custom-fields",
        json={"entity_kind": "requirement", "name": "Risk", "field_type": "short_text"},
        headers=auth_headers(admin_token),
    ).json()

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
            "kind": "modify_requirement", "requirement_id": requirement["id"], "changed_fields": ["custom_fields"],
            "reason": "add risk rating",
            "custom_fields": {field["id"]: "Medium risk"},
        },
        headers=auth_headers(admin_token),
    ).json()
    client.post(f"/api/v1/projects/{project['id']}/change-requests/{cr['id']}/submit", headers=auth_headers(admin_token))
    client.post(
        f"/api/v1/projects/{project['id']}/change-requests/{cr['id']}/decide",
        json={"approve": True, "note": ""}, headers=auth_headers(admin_token),
    )

    updated = client.get(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}", headers=auth_headers(admin_token)
    ).json()
    assert updated["custom_fields"] == {field["id"]: "Medium risk"}


def test_deleting_custom_field_definition_preserves_historical_values(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    field = client.post(
        f"/api/v1/projects/{project['id']}/custom-fields",
        json={"entity_kind": "requirement", "name": "Notes", "field_type": "long_text"},
        headers=auth_headers(admin_token),
    ).json()
    requirement = client.post(
        f"/api/v1/projects/{project['id']}/requirements",
        json={
            "name": "Req", "component_id": component_id, "category_id": category_id,
            "custom_fields": {field["id"]: "some notes"},
        },
        headers=auth_headers(admin_token),
    ).json()

    resp = client.delete(f"/api/v1/projects/{project['id']}/custom-fields/{field['id']}", headers=auth_headers(admin_token))
    assert resp.status_code == 204

    history = client.get(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/history", headers=auth_headers(admin_token)
    ).json()
    assert requirement["custom_fields"] == {field["id"]: "some notes"}
    assert history  # historical version rows are untouched by definition deletion
