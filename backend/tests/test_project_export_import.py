"""
Tests for project bundle export/import (`GET /projects/{id}/export`,
`POST /projects/import`): structure (stages/components/categories/custom
field definitions), full requirement history (versions/keywords/custom
field values), change request history (versions/tasks/votes/comments),
baselines, cross-organisation import, unmatched-user fallback, and bundle
validation.
"""

import io
import zipfile

from tests.conftest import auth_headers, create_component_and_category, create_org_admin_in, create_project


def _create_custom_field(client, admin_token, project_id, *, name, field_type="short_text", entity_kind="requirement"):
    resp = client.post(
        f"/api/v1/projects/{project_id}/custom-fields",
        json={"entity_kind": entity_kind, "name": name, "field_type": field_type},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _approve_current_stage(client, admin_token, project_id):
    stages = client.get(f"/api/v1/projects/{project_id}/stages", headers=auth_headers(admin_token)).json()
    stage_id = stages[0]["id"]
    assert client.post(
        f"/api/v1/projects/{project_id}/stages/{stage_id}/transition?new_status=review", headers=auth_headers(admin_token)
    ).status_code == 200
    resp = client.post(
        f"/api/v1/projects/{project_id}/stages/{stage_id}/transition?new_status=approved", headers=auth_headers(admin_token)
    )
    assert resp.status_code == 200


def _build_rich_project(client, admin_token, org_id):
    """Builds a project exercising every part of the bundle: custom fields
    (both entity kinds), a requirement with a custom field value and
    keywords, a submitted+approved change request with a task/vote/comment,
    and (via stage approval) a baseline and a locked/approved requirement."""
    project = create_project(client, admin_token, org_id, name="Rich Source Project")
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    req_field = _create_custom_field(client, admin_token, project["id"], name="Priority")
    _create_custom_field(client, admin_token, project["id"], name="Risk", entity_kind="change_request")

    req_resp = client.post(
        f"/api/v1/projects/{project['id']}/requirements",
        json={
            "name": "Boot within 3s", "reasoning": "UX requirement", "component_id": component_id, "category_id": category_id,
            "keywords": ["boot", "perf"], "custom_fields": {req_field["id"]: "High"},
        },
        headers=auth_headers(admin_token),
    )
    assert req_resp.status_code == 201, req_resp.text
    requirement = req_resp.json()

    second_req = client.post(
        f"/api/v1/projects/{project['id']}/requirements",
        json={"name": "For CR modification", "component_id": component_id, "category_id": category_id},
        headers=auth_headers(admin_token),
    ).json()

    cr_resp = client.post(
        f"/api/v1/projects/{project['id']}/change-requests",
        json={
            "kind": "modify_requirement", "requirement_id": second_req["id"], "changed_fields": ["name"],
            "proposed_name": "Renamed via CR", "reason": "Naming cleanup",
        },
        headers=auth_headers(admin_token),
    )
    assert cr_resp.status_code == 201, cr_resp.text
    cr = cr_resp.json()
    task_resp = client.post(
        f"/api/v1/projects/{project['id']}/change-requests/{cr['id']}/tasks",
        json={"description": "Confirm with stakeholders"}, headers=auth_headers(admin_token),
    )
    assert task_resp.status_code == 201, task_resp.text

    submit_resp = client.post(f"/api/v1/projects/{project['id']}/change-requests/{cr['id']}/submit", headers=auth_headers(admin_token))
    assert submit_resp.status_code == 200, submit_resp.text

    # Voting requires the stakeholder role specifically (not just
    # project-manager) and only while the CR is open for review — grant it
    # to the project-creating admin so they can cast a vote here.
    admin_user_id = client.get("/api/v1/auth/me", headers=auth_headers(admin_token)).json()["id"]
    role_resp = client.post(
        f"/api/v1/projects/{project['id']}/roles",
        json={"user_id": admin_user_id, "role": "stakeholder"}, headers=auth_headers(admin_token),
    )
    assert role_resp.status_code == 204, role_resp.text
    vote_resp = client.post(
        f"/api/v1/projects/{project['id']}/change-requests/{cr['id']}/votes",
        json={"vote": "approve", "comment": "LGTM"}, headers=auth_headers(admin_token),
    )
    assert vote_resp.status_code == 200, vote_resp.text
    comment_resp = client.post(
        f"/api/v1/projects/{project['id']}/change-requests/{cr['id']}/comments",
        json={"body": "Discussion comment"}, headers=auth_headers(admin_token),
    )
    assert comment_resp.status_code == 201, comment_resp.text
    decide_resp = client.post(
        f"/api/v1/projects/{project['id']}/change-requests/{cr['id']}/decide",
        json={"approve": True, "note": "Approved"}, headers=auth_headers(admin_token),
    )
    assert decide_resp.status_code == 200, decide_resp.text

    _approve_current_stage(client, admin_token, project["id"])
    return project, requirement, req_field


def test_export_returns_a_zip_with_manifest_and_project_json(client, admin_token, org_id):
    project, _, _ = _build_rich_project(client, admin_token, org_id)
    resp = client.get(f"/api/v1/projects/{project['id']}/export", headers=auth_headers(admin_token))
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"
    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    names = set(zf.namelist())
    assert {"manifest.json", "project.json"} <= names
    import json
    manifest = json.loads(zf.read("manifest.json"))
    assert manifest["kind"] == "project-export"
    assert manifest["format_version"] == 1
    assert manifest["project_name"] == "Rich Source Project"


def test_import_reconstructs_structure_and_full_history_in_the_same_org(client, admin_token, org_id):
    project, requirement, req_field = _build_rich_project(client, admin_token, org_id)
    export_resp = client.get(f"/api/v1/projects/{project['id']}/export", headers=auth_headers(admin_token))
    assert export_resp.status_code == 200

    import_resp = client.post(
        "/api/v1/projects/import",
        data={"organization_id": org_id, "name": "Reimported Project"},
        files={"file": ("bundle.zip", export_resp.content, "application/zip")},
        headers=auth_headers(admin_token),
    )
    assert import_resp.status_code == 201, import_resp.text
    result = import_resp.json()
    new_project = result["project"]
    assert new_project["name"] == "Reimported Project"
    assert new_project["organization_id"] == org_id
    assert result["warnings"] == []

    components = client.get(f"/api/v1/projects/{new_project['id']}/components", headers=auth_headers(admin_token)).json()
    assert {c["prefix"] for c in components} == {"SW"}
    categories = client.get(f"/api/v1/projects/{new_project['id']}/categories", headers=auth_headers(admin_token)).json()
    assert {c["prefix"] for c in categories} == {"PERF"}
    new_req_fields = client.get(
        f"/api/v1/projects/{new_project['id']}/custom-fields?entity_kind=requirement", headers=auth_headers(admin_token)
    ).json()
    assert [f["name"] for f in new_req_fields] == ["Priority"]

    requirements = client.get(f"/api/v1/projects/{new_project['id']}/requirements", headers=auth_headers(admin_token)).json()
    boot_req = next(r for r in requirements if r["name"] == "Boot within 3s")
    assert sorted(boot_req["keywords"]) == ["boot", "perf"]
    assert boot_req["custom_fields"][new_req_fields[0]["id"]] == "High"

    renamed_req = next(r for r in requirements if r["name"] == "Renamed via CR")
    assert renamed_req["status"] == "approved"  # approved via the CR, then stage approval locked it
    assert renamed_req["is_locked"] is True
    history = client.get(
        f"/api/v1/projects/{new_project['id']}/requirements/{renamed_req['id']}/history", headers=auth_headers(admin_token)
    ).json()
    assert len(history) == 2  # initial creation + the CR-driven version

    change_requests = client.get(f"/api/v1/projects/{new_project['id']}/change-requests", headers=auth_headers(admin_token)).json()
    assert len(change_requests) == 1
    imported_cr = change_requests[0]
    assert imported_cr["status"] == "approved"
    tasks = client.get(
        f"/api/v1/projects/{new_project['id']}/change-requests/{imported_cr['id']}/tasks", headers=auth_headers(admin_token)
    ).json()
    assert [t["description"] for t in tasks] == ["Confirm with stakeholders"]
    votes = client.get(
        f"/api/v1/projects/{new_project['id']}/change-requests/{imported_cr['id']}/votes", headers=auth_headers(admin_token)
    ).json()
    assert votes["approve_count"] == 1
    comments = client.get(
        f"/api/v1/projects/{new_project['id']}/change-requests/{imported_cr['id']}/comments", headers=auth_headers(admin_token)
    ).json()
    assert [c["body"] for c in comments] == ["Discussion comment"]


def test_import_into_a_different_organisation(client, admin_token, org_id):
    project, _, _ = _build_rich_project(client, admin_token, org_id)
    export_resp = client.get(f"/api/v1/projects/{project['id']}/export", headers=auth_headers(admin_token))

    other_org, other_org_admin_token = create_org_admin_in(client, admin_token, "Cross Org Import Target")
    import_resp = client.post(
        "/api/v1/projects/import",
        data={"organization_id": other_org["id"], "name": "Cross-Org Reimport"},
        files={"file": ("bundle.zip", export_resp.content, "application/zip")},
        headers=auth_headers(other_org_admin_token),
    )
    assert import_resp.status_code == 201, import_resp.text
    new_project = import_resp.json()["project"]
    assert new_project["organization_id"] == other_org["id"]

    requirements = client.get(
        f"/api/v1/projects/{new_project['id']}/requirements", headers=auth_headers(other_org_admin_token)
    ).json()
    assert any(r["name"] == "Boot within 3s" for r in requirements)


def test_export_requires_project_manage_role(client, admin_token, org_id):
    from tests.conftest import create_org_user, login

    project = create_project(client, admin_token, org_id)
    create_component_and_category(client, admin_token, project["id"])
    member_id = create_org_user(client, admin_token, org_id, "csv-export-member@example.com", role="member")
    client.post(
        f"/api/v1/projects/{project['id']}/roles",
        json={"user_id": member_id, "role": "member"}, headers=auth_headers(admin_token),
    )
    member_token = login(client, "csv-export-member@example.com", "Password123!")
    resp = client.get(f"/api/v1/projects/{project['id']}/export", headers=auth_headers(member_token))
    assert resp.status_code == 403


def test_import_requires_org_admin_or_project_creator_role(client, admin_token, org_id):
    from tests.conftest import create_org_user, login

    project, _, _ = _build_rich_project(client, admin_token, org_id)
    export_resp = client.get(f"/api/v1/projects/{project['id']}/export", headers=auth_headers(admin_token))
    create_org_user(client, admin_token, org_id, "csv-import-member@example.com", role="member")
    member_token = login(client, "csv-import-member@example.com", "Password123!")

    import_resp = client.post(
        "/api/v1/projects/import",
        data={"organization_id": org_id, "name": "Should Not Be Created"},
        files={"file": ("bundle.zip", export_resp.content, "application/zip")},
        headers=auth_headers(member_token),
    )
    assert import_resp.status_code == 403


def test_import_rejects_a_bundle_of_the_wrong_kind(client, admin_token, org_id):
    import json

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"kind": "org-export", "format_version": 1}))
        zf.writestr("project.json", json.dumps({}))
    resp = client.post(
        "/api/v1/projects/import",
        data={"organization_id": org_id, "name": "Bad Bundle"},
        files={"file": ("bundle.zip", buffer.getvalue(), "application/zip")},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 400


def test_import_rejects_a_bundle_from_a_newer_format_version(client, admin_token, org_id):
    import json

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"kind": "project-export", "format_version": 999}))
        zf.writestr("project.json", json.dumps({}))
    resp = client.post(
        "/api/v1/projects/import",
        data={"organization_id": org_id, "name": "Future Bundle"},
        files={"file": ("bundle.zip", buffer.getvalue(), "application/zip")},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 400


def test_import_rejects_a_non_zip_file(client, admin_token, org_id):
    resp = client.post(
        "/api/v1/projects/import",
        data={"organization_id": org_id, "name": "Not A Zip"},
        files={"file": ("bundle.zip", b"not a zip file", "application/zip")},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 400


def test_unmatched_required_user_reference_falls_back_to_importer_with_a_warning(client, admin_token, org_id):
    """Unit-level test of `import_project_bundle` (rather than round-tripping
    through a real export) so a bundle can reference an email that matches
    no real account — every user in this app is a real, never-deleted
    account (see models.user.User), so there's no way to produce this case
    by exporting real data."""
    import json
    from uuid import UUID

    from sqlalchemy import select

    from app.database import SessionLocal
    from app.models.requirement import Requirement, RequirementVersion
    from app.models.user import User
    from app.services.project_export import import_project_bundle

    project_json = {
        "summary": "", "allow_member_change_requests": True, "terminology": {},
        "review_reminder_lead_days_default": 7, "report_intro": "", "report_chapters": [], "report_appendices": [],
        "default_report_template_name": None,
        "stages": [{"name": "Scoping", "sort_order": 0}],
        "components": [{"name": "Software", "prefix": "SW", "sort_order": 0, "categories": [{"name": "Perf", "prefix": "PERF", "sort_order": 0}]}],
        "custom_field_definitions": [], "groups": [],
        "requirements": [
            {
                "unique_code": "SW-PERF-001", "component_prefix": "SW", "category_prefix": "PERF",
                "creator_email": "ghost@example.com", "is_archived": False, "archived_at": None, "archived_by_email": None,
                "versions": [{
                    "version_number": 1, "valid_from": "2024-01-01T00:00:00+00:00", "valid_to": None,
                    "name": "Ghost-owned requirement", "reasoning": "", "clarification": "", "description": "",
                    "status": "draft", "target_stage": "Scoping", "level": "requirement",
                    "owner_email": "ghost@example.com", "approval_authority_email": None, "sort_order": 0,
                    "custom_fields": {}, "change_request_ref": None, "change_note": "", "review_date": None,
                    "review_lead_days": None, "reviewer_email": None, "created_by_email": "ghost@example.com",
                    "created_at": "2024-01-01T00:00:00+00:00",
                }],
                "keywords": [], "attachments": [],
            }
        ],
        "requirement_links": [], "requirement_comments": [], "change_requests": [], "baselines": [], "requirement_reviews": [],
        "audit_events": [],
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"kind": "project-export", "format_version": 1, "project_name": "Ghost"}))
        zf.writestr("project.json", json.dumps(project_json))

    db = SessionLocal()
    try:
        importing_user = db.scalar(select(User).where(User.email == "admin@example.com"))
        project, warnings = import_project_bundle(
            db, organization_id=UUID(org_id), name="Ghost Import", summary=None,
            zip_bytes=buffer.getvalue(), current_user=importing_user,
        )
        assert any("ghost@example.com" in w for w in warnings)
        owner_id = db.scalar(
            select(RequirementVersion.owner_id)
            .join(Requirement, Requirement.id == RequirementVersion.requirement_id)
            .where(Requirement.project_id == project.id)
        )
        assert owner_id == importing_user.id
    finally:
        db.close()
