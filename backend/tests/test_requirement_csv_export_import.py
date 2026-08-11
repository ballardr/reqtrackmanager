"""
Tests for the full-fidelity requirement CSV export/import round trip:
custom field values, target stage, owner/reviewer, keywords, and review
scheduling all survive `GET .../export` -> `POST .../import`, CSV formula
injection is neutralized, and the pre-existing minimal (6-column) import
format still works unchanged.
"""

import csv
import io

from tests.conftest import auth_headers, create_component_and_category, create_project


def _create_custom_field(client, admin_token, project_id, *, name, field_type, options=None, required=False):
    resp = client.post(
        f"/api/v1/projects/{project_id}/custom-fields",
        json={"entity_kind": "requirement", "name": name, "field_type": field_type, "options": options, "required": required},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _rows(csv_text: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(csv_text)))


def test_export_includes_every_field_and_reimports_into_a_fresh_project(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id, name="Source Project")
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    stages = client.get(f"/api/v1/projects/{project['id']}/stages", headers=auth_headers(admin_token)).json()
    stage_name = stages[0]["name"]

    priority_field = _create_custom_field(client, admin_token, project["id"], name="Priority", field_type="short_text")
    reviewed_field = _create_custom_field(client, admin_token, project["id"], name="Reviewed", field_type="checkbox")

    create_resp = client.post(
        f"/api/v1/projects/{project['id']}/requirements",
        json={
            "name": "Widget must ship", "reasoning": "Because customers want it", "clarification": "Clarify this",
            "description": "A fuller description", "component_id": component_id, "category_id": category_id,
            "level": "recommended", "keywords": ["safety", "power"],
            "custom_fields": {priority_field["id"]: "High", reviewed_field["id"]: True},
            "review_date": "2027-01-15", "review_lead_days": 10,
        },
        headers=auth_headers(admin_token),
    )
    assert create_resp.status_code == 201, create_resp.text

    export_resp = client.get(f"/api/v1/projects/{project['id']}/requirements/export", headers=auth_headers(admin_token))
    assert export_resp.status_code == 200
    assert export_resp.headers["content-type"].startswith("text/csv")
    rows = _rows(export_resp.text)
    assert len(rows) == 1
    row = rows[0]
    assert row["name"] == "Widget must ship"
    assert row["reasoning"] == "Because customers want it"
    assert row["clarification"] == "Clarify this"
    assert row["description"] == "A fuller description"
    assert row["component_prefix"] == "SW"
    assert row["category_prefix"] == "PERF"
    assert row["level"] == "recommended"
    assert row["target_version"] == stage_name
    assert row["keywords"] == "power;safety"
    assert row["review_date"] == "2027-01-15"
    assert row["review_lead_days"] == "10"
    assert row["cf_Priority"] == "High"
    assert row["cf_Reviewed"] == "True"
    assert row["status"] == "draft"

    # Re-import the exported file into a brand-new project with matching
    # component/category prefixes, stage name, and custom field definitions
    # — this is the round-trip fidelity the feature exists for.
    target_project = create_project(client, admin_token, org_id, name="Target Project")
    client.post(
        f"/api/v1/projects/{target_project['id']}/components",
        json={"name": "Software", "prefix": "SW"}, headers=auth_headers(admin_token),
    )
    target_component = client.get(f"/api/v1/projects/{target_project['id']}/components", headers=auth_headers(admin_token)).json()[0]
    client.post(
        f"/api/v1/projects/{target_project['id']}/categories",
        json={"name": "Performance", "prefix": "PERF", "component_id": target_component["id"]},
        headers=auth_headers(admin_token),
    )
    target_stages = client.get(f"/api/v1/projects/{target_project['id']}/stages", headers=auth_headers(admin_token)).json()
    if target_stages[0]["name"] != stage_name:
        client.patch(
            f"/api/v1/projects/{target_project['id']}/stages/{target_stages[0]['id']}",
            json={"name": stage_name}, headers=auth_headers(admin_token),
        )
    target_priority = _create_custom_field(client, admin_token, target_project["id"], name="Priority", field_type="short_text")
    _create_custom_field(client, admin_token, target_project["id"], name="Reviewed", field_type="checkbox")

    import_resp = client.post(
        f"/api/v1/projects/{target_project['id']}/requirements/import",
        files={"file": ("export.csv", export_resp.text, "text/csv")},
        headers=auth_headers(admin_token),
    )
    assert import_resp.status_code == 201, import_resp.text
    result = import_resp.json()
    assert result["created"] == 1
    assert result["errors"] == []

    imported = client.get(f"/api/v1/projects/{target_project['id']}/requirements", headers=auth_headers(admin_token)).json()
    assert len(imported) == 1
    req = imported[0]
    assert req["name"] == "Widget must ship"
    assert req["reasoning"] == "Because customers want it"
    assert req["clarification"] == "Clarify this"
    assert req["description"] == "A fuller description"
    assert req["level"] == "recommended"
    assert sorted(req["keywords"]) == ["power", "safety"]
    assert req["review_date"] == "2027-01-15"
    assert req["review_lead_days"] == 10
    assert req["status"] == "draft"  # status is never carried over by import
    assert req["custom_fields"][target_priority["id"]] == "High"


def test_owner_and_reviewer_email_round_trip(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])

    csv_content = (
        "name,component_prefix,category_prefix,owner_email,reviewer_email\n"
        "Needs an owner,SW,PERF,admin@example.com,admin@example.com\n"
    )
    resp = client.post(
        f"/api/v1/projects/{project['id']}/requirements/import",
        files={"file": ("import.csv", csv_content, "text/csv")}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 201
    assert resp.json()["created"] == 1

    export_resp = client.get(f"/api/v1/projects/{project['id']}/requirements/export", headers=auth_headers(admin_token))
    row = _rows(export_resp.text)[0]
    assert row["owner_email"] == "admin@example.com"
    assert row["reviewer_email"] == "admin@example.com"


def test_unknown_owner_email_is_a_row_error_not_a_silent_drop(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    create_component_and_category(client, admin_token, project["id"])

    csv_content = (
        "name,component_prefix,category_prefix,owner_email\n"
        "Bad owner,SW,PERF,nobody@example.com\n"
    )
    resp = client.post(
        f"/api/v1/projects/{project['id']}/requirements/import",
        files={"file": ("import.csv", csv_content, "text/csv")}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["created"] == 0
    assert len(body["errors"]) == 1
    assert "nobody@example.com" in body["errors"][0]["message"]


def test_required_custom_field_missing_on_import_is_a_row_error(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    create_component_and_category(client, admin_token, project["id"])
    _create_custom_field(client, admin_token, project["id"], name="Priority", field_type="short_text", required=True)

    csv_content = "name,component_prefix,category_prefix\nMissing required field,SW,PERF\n"
    resp = client.post(
        f"/api/v1/projects/{project['id']}/requirements/import",
        files={"file": ("import.csv", csv_content, "text/csv")}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["created"] == 0
    assert len(body["errors"]) == 1
    assert "Priority" in body["errors"][0]["message"]


def test_old_minimal_format_still_imports_unchanged(client, admin_token, org_id):
    """Backward compatibility: a CSV using only the original 6 columns
    (name/reasoning/component_prefix/category_prefix/level/target_version)
    must keep working exactly as before this feature expanded the format."""
    project = create_project(client, admin_token, org_id)
    create_component_and_category(client, admin_token, project["id"])
    stages = client.get(f"/api/v1/projects/{project['id']}/stages", headers=auth_headers(admin_token)).json()

    csv_content = (
        "name,reasoning,component_prefix,category_prefix,level,target_version\n"
        f"Ship the widget,Because it must,SW,PERF,recommended,{stages[0]['name']}\n"
    )
    resp = client.post(
        f"/api/v1/projects/{project['id']}/requirements/import",
        files={"file": ("import.csv", csv_content, "text/csv")}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["created"] == 1
    assert body["errors"] == []


def test_export_neutralizes_csv_formula_injection(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    resp = client.post(
        f"/api/v1/projects/{project['id']}/requirements",
        json={
            "name": "=cmd|' /C calc'!A0", "reasoning": "@SUM(1+1)",
            "component_id": component_id, "category_id": category_id,
        },
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 201

    export_resp = client.get(f"/api/v1/projects/{project['id']}/requirements/export", headers=auth_headers(admin_token))
    row = _rows(export_resp.text)[0]
    assert row["name"].startswith("'=")
    assert row["reasoning"].startswith("'@")


def test_export_denies_users_without_project_access(client, admin_token, org_id):
    from tests.conftest import create_org_admin_in

    project = create_project(client, admin_token, org_id)
    _, other_org_admin_token = create_org_admin_in(client, admin_token, "Other Org For CSV Export Test")
    resp = client.get(
        f"/api/v1/projects/{project['id']}/requirements/export", headers=auth_headers(other_org_admin_token)
    )
    assert resp.status_code in (403, 404)
