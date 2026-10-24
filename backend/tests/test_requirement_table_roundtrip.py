"""Tests for the requirement table's CSV round trip through the shared record routes
(`GET/POST /projects/{id}/records/requirement/export|import`): custom field values, target stage, owner and
reviewer, tags and review scheduling survive an export and an import into a fresh project; unknown people,
missing required custom fields and unknown prefixes are row errors, never silent drops.

The shared engine's own behaviour (codes, updates, previews, caps, injection guard) is in `test_record_tables.py`.
"""

import csv
import io

from tests.conftest import auth_headers, create_component_and_category, create_project


def _create_custom_field(client, admin_token, project_id, *, name, field_type, required=False):
    resp = client.post(
        f"/api/v1/projects/{project_id}/custom-fields",
        json={"entity_kind": "requirement", "name": name, "field_type": field_type, "options": None, "required": required},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _export(client, token, project_id) -> tuple[str, list[dict]]:
    resp = client.get(f"/api/v1/projects/{project_id}/records/requirement/export", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    text = resp.content.decode("utf-8-sig")
    return text, list(csv.DictReader(io.StringIO(text)))


def _import(client, token, project_id, text: str, *, apply: bool = True) -> dict:
    resp = client.post(
        f"/api/v1/projects/{project_id}/records/requirement/import",
        params={"dry_run": "false" if apply else "true"},
        files={"file": ("import.csv", text.encode("utf-8"), "text/csv")}, headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_export_includes_every_field_and_reimports_into_a_fresh_project(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id, name="Source Project")
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    stage_name = client.get(f"/api/v1/projects/{project['id']}/stages", headers=auth_headers(admin_token)).json()[0]["name"]
    priority = _create_custom_field(client, admin_token, project["id"], name="Priority", field_type="short_text")
    reviewed = _create_custom_field(client, admin_token, project["id"], name="Reviewed", field_type="checkbox")
    created = client.post(
        f"/api/v1/projects/{project['id']}/requirements",
        json={
            "name": "Widget must ship", "reasoning": "Because customers want it", "clarification": "Clarify this",
            "description": "A fuller description", "component_id": component_id, "category_id": category_id,
            "level": "recommended", "keywords": ["safety", "power"],
            "custom_fields": {priority["id"]: "High", reviewed["id"]: True},
            "review_date": "2027-01-15", "review_lead_days": 10,
        },
        headers=auth_headers(admin_token),
    )
    assert created.status_code == 201, created.text

    _, rows = _export(client, admin_token, project["id"])
    assert len(rows) == 1
    row = rows[0]
    assert (row["name"], row["reasoning"], row["clarification"]) == ("Widget must ship", "Because customers want it", "Clarify this")
    assert (row["component"], row["category"], row["level"]) == ("SW", "PERF", "Recommended")
    assert row["target_version"] == stage_name
    assert row["keywords"] == "power;safety"
    assert (row["review_date"], row["review_lead_days"]) == ("2027-01-15", "10")
    assert (row["cf_Priority"], row["cf_Reviewed"]) == ("High", "true")
    assert row["status"] == "Draft"

    target = create_project(client, admin_token, org_id, name="Target Project")
    create_component_and_category(client, admin_token, target["id"])
    target_stages = client.get(f"/api/v1/projects/{target['id']}/stages", headers=auth_headers(admin_token)).json()
    if target_stages[0]["name"] != stage_name:
        client.patch(
            f"/api/v1/projects/{target['id']}/stages/{target_stages[0]['id']}", json={"name": stage_name},
            headers=auth_headers(admin_token),
        )
    target_priority = _create_custom_field(client, admin_token, target["id"], name="Priority", field_type="short_text")
    _create_custom_field(client, admin_token, target["id"], name="Reviewed", field_type="checkbox")

    # The exported file names the source project's code; here the record is new, so the code is blanked.
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerow({**rows[0], "code": ""})
    body = out.getvalue()
    result = _import(client, admin_token, target["id"], body)
    assert (result["created"], result["failed"]) == (1, 0), result

    imported = client.get(f"/api/v1/projects/{target['id']}/requirements", headers=auth_headers(admin_token)).json()
    assert len(imported) == 1
    req = imported[0]
    assert (req["name"], req["level"], req["status"]) == ("Widget must ship", "recommended", "draft")
    assert sorted(req["keywords"]) == ["power", "safety"]
    assert (req["review_date"], req["review_lead_days"]) == ("2027-01-15", 10)
    assert req["custom_fields"][target_priority["id"]] == "High"


def test_owner_and_reviewer_email_round_trip(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    create_component_and_category(client, admin_token, project["id"])
    result = _import(
        client, admin_token, project["id"],
        "name,component,category,owner,reviewer\nNeeds an owner,SW,PERF,admin@example.com,admin@example.com\n",
    )
    assert result["created"] == 1, result
    _, rows = _export(client, admin_token, project["id"])
    assert (rows[0]["owner"], rows[0]["reviewer"]) == ("admin@example.com", "admin@example.com")


def test_unknown_owner_email_is_a_row_error_not_a_silent_drop(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    create_component_and_category(client, admin_token, project["id"])
    result = _import(client, admin_token, project["id"], "name,component,category,owner\nBad owner,SW,PERF,nobody@example.com\n")
    assert (result["created"], result["failed"]) == (0, 1)
    assert "nobody@example.com" in result["rows"][0]["message"]


def test_required_custom_field_missing_on_import_is_a_row_error(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    create_component_and_category(client, admin_token, project["id"])
    _create_custom_field(client, admin_token, project["id"], name="Priority", field_type="short_text", required=True)
    result = _import(client, admin_token, project["id"], "name,component,category\nMissing required field,SW,PERF\n")
    assert (result["created"], result["failed"]) == (0, 1)
    assert "Priority" in result["rows"][0]["message"]


def test_valid_rows_import_and_each_kind_of_bad_row_is_reported(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    create_component_and_category(client, admin_token, project["id"])
    stages = client.get(f"/api/v1/projects/{project['id']}/stages", headers=auth_headers(admin_token)).json()
    text = (
        "name,reasoning,component,category,level,target_version\n"
        f"Ship the widget,Because it must,SW,PERF,Recommended,{stages[0]['name']}\n"
        ",Missing name,SW,PERF,Requirement,\n"
        "Bad component,Oops,ZZ,PERF,Requirement,\n"
        "Bad category,Oops,SW,ZZ,Requirement,\n"
        "Bad level,Oops,SW,PERF,not_a_level,\n"
        "Bad stage,Oops,SW,PERF,Requirement,Nonexistent Stage\n"
        "Second valid row,Also fine,SW,PERF,Requirement,\n"
    )
    result = _import(client, admin_token, project["id"], text)
    assert (result["created"], result["failed"]) == (2, 5), result
    assert result["error_csv"].startswith("code,") or "error" in result["error_csv"].splitlines()[0]
    listed = client.get(f"/api/v1/projects/{project['id']}/requirements", headers=auth_headers(admin_token)).json()
    imported = next(r for r in listed if r["name"] == "Ship the widget")
    assert (imported["level"], imported["target_stage_id"]) == ("recommended", stages[0]["id"])
    assert {r["name"] for r in listed} == {"Ship the widget", "Second valid row"}
