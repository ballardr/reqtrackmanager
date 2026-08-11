"""Tests for the new requirement/change-request behaviour: mandatory
target defaulting, the optional description field, the "optional"
requirement level, change-request field-level tracking (changed_fields),
the lock gate now covering direct attachments, and change-request-approved
attachments."""

import struct
import zlib

from tests.conftest import (
    auth_headers,
    create_component_and_category,
    create_org_admin_in,
    create_org_user,
    create_project,
    login,
)


def _assign_project_role(client, admin_token, project_id, user_id, role):
    resp = client.post(
        f"/api/v1/projects/{project_id}/roles", json={"user_id": user_id, "role": role},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 204, resp.text


def _make_project_member(client, admin_token, org_id, project_id, email, role):
    user_id = create_org_user(client, admin_token, org_id, email, role="member")
    _assign_project_role(client, admin_token, project_id, user_id, role)
    return login(client, email, "Password123!")


def _tiny_png() -> bytes:
    """A minimal real, decodable 1x1 PNG (see test_report_images.py — a
    fake header alone won't pass content validation elsewhere)."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    idat = chunk(b"IDAT", zlib.compress(b"\x00" + b"\xff\xff\xff"))
    return signature + ihdr + idat + chunk(b"IEND", b"")


def _create_requirement(client, admin_token, project_id, component_id, category_id, name="Boot fast", **extra):
    resp = client.post(
        f"/api/v1/projects/{project_id}/requirements",
        json={"name": name, "component_id": component_id, "category_id": category_id, **extra},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _approve_current_stage(client, admin_token, project_id):
    stages = client.get(f"/api/v1/projects/{project_id}/stages", headers=auth_headers(admin_token)).json()
    stage_id = stages[0]["id"]
    review = client.post(
        f"/api/v1/projects/{project_id}/stages/{stage_id}/transition?new_status=review",
        headers=auth_headers(admin_token),
    )
    assert review.status_code == 200
    resp = client.post(
        f"/api/v1/projects/{project_id}/stages/{stage_id}/transition?new_status=approved",
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200


# --- Mandatory target, description, optional level -------------------------


def test_requirement_target_defaults_to_projects_earliest_stage_when_omitted(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    stages = client.get(f"/api/v1/projects/{project['id']}/stages", headers=auth_headers(admin_token)).json()

    requirement = _create_requirement(client, admin_token, project["id"], component_id, category_id)
    assert requirement["target_stage_id"] == stages[0]["id"]


def test_requirement_description_and_optional_level_round_trip(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])

    requirement = _create_requirement(
        client, admin_token, project["id"], component_id, category_id,
        description="Longer free-text elaboration.", level="optional",
    )
    assert requirement["description"] == "Longer free-text elaboration."
    assert requirement["level"] == "optional"

    fetched = client.get(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}", headers=auth_headers(admin_token)
    ).json()
    assert fetched["description"] == "Longer free-text elaboration."
    assert fetched["level"] == "optional"


def test_requirement_update_omitting_target_stage_id_carries_current_value_forward(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    requirement = _create_requirement(client, admin_token, project["id"], component_id, category_id)
    original_target = requirement["target_stage_id"]

    resp = client.put(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}",
        json={
            "name": "Renamed", "component_id": component_id, "category_id": category_id,
            "owner_id": requirement["owner_id"],
        },
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["target_stage_id"] == original_target


# --- Change request changed_fields validation -------------------------------


def test_modify_change_request_rejects_empty_or_unknown_changed_fields(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    requirement = _create_requirement(client, admin_token, project["id"], component_id, category_id)

    resp = client.post(
        f"/api/v1/projects/{project['id']}/change-requests",
        json={"kind": "modify_requirement", "requirement_id": requirement["id"], "reason": "x"},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 400, resp.text

    resp = client.post(
        f"/api/v1/projects/{project['id']}/change-requests",
        json={
            "kind": "modify_requirement", "requirement_id": requirement["id"],
            "changed_fields": ["not_a_real_field"], "reason": "x",
        },
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 400, resp.text


def test_modify_change_request_requires_a_value_for_fields_that_cant_be_null(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    requirement = _create_requirement(client, admin_token, project["id"], component_id, category_id)

    resp = client.post(
        f"/api/v1/projects/{project['id']}/change-requests",
        json={
            "kind": "modify_requirement", "requirement_id": requirement["id"],
            "changed_fields": ["name"], "reason": "x",
            # proposed_name deliberately omitted
        },
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 400, resp.text
    assert "name" in resp.json()["detail"]


def test_modify_change_request_can_clear_reviewer_via_changed_fields_alone(client, admin_token, org_id):
    """reviewer_id/review_date/review_lead_days are genuinely nullable on
    the requirement — changed_fields membership alone (not a non-None
    check) signals they're being touched, so a change request can propose
    *clearing* one."""
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    requirement = _create_requirement(client, admin_token, project["id"], component_id, category_id)
    # Set a reviewer directly first.
    admin_id = client.get("/api/v1/auth/me", headers=auth_headers(admin_token)).json()["id"]
    client.put(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}",
        json={
            "name": requirement["name"], "component_id": component_id, "category_id": category_id,
            "owner_id": requirement["owner_id"], "reviewer_id": admin_id,
        },
        headers=auth_headers(admin_token),
    )

    cr = client.post(
        f"/api/v1/projects/{project['id']}/change-requests",
        json={
            "kind": "modify_requirement", "requirement_id": requirement["id"],
            "changed_fields": ["reviewer_id"], "reason": "no longer needed",
        },
        headers=auth_headers(admin_token),
    ).json()
    client.post(f"/api/v1/projects/{project['id']}/change-requests/{cr['id']}/submit", headers=auth_headers(admin_token))
    decision = client.post(
        f"/api/v1/projects/{project['id']}/change-requests/{cr['id']}/decide",
        json={"approve": True, "note": ""}, headers=auth_headers(admin_token),
    )
    assert decision.status_code == 200, decision.text

    updated = client.get(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}", headers=auth_headers(admin_token)
    ).json()
    assert updated["reviewer_id"] is None


def test_approval_only_applies_fields_listed_in_changed_fields(client, admin_token, org_id):
    """The core regression this feature closes: approving a change request
    that only lists 'reasoning' must leave name/description/level/target
    completely untouched, even though the change request's own
    proposed_name field happens to differ from the current name (simulating
    a stale/leftover value that was never meant to be applied)."""
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    requirement = _create_requirement(
        client, admin_token, project["id"], component_id, category_id,
        name="Original name", description="Original description", level="requirement",
    )

    cr = client.post(
        f"/api/v1/projects/{project['id']}/change-requests",
        json={
            "kind": "modify_requirement", "requirement_id": requirement["id"],
            "changed_fields": ["reasoning"],
            "proposed_reasoning": "New reasoning only",
            "proposed_name": "This must never be applied",  # not in changed_fields
            "reason": "clarify reasoning",
        },
        headers=auth_headers(admin_token),
    ).json()
    client.post(f"/api/v1/projects/{project['id']}/change-requests/{cr['id']}/submit", headers=auth_headers(admin_token))
    decision = client.post(
        f"/api/v1/projects/{project['id']}/change-requests/{cr['id']}/decide",
        json={"approve": True, "note": ""}, headers=auth_headers(admin_token),
    )
    assert decision.status_code == 200, decision.text

    updated = client.get(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}", headers=auth_headers(admin_token)
    ).json()
    assert updated["reasoning"] == "New reasoning only"
    assert updated["name"] == "Original name"
    assert updated["description"] == "Original description"
    assert updated["level"] == "requirement"


# --- Attachment lock gate + change-request-approved attachments ------------


def test_direct_attachment_blocked_once_requirement_is_locked(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    requirement = _create_requirement(client, admin_token, project["id"], component_id, category_id)

    resp = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/files",
        files={"file": ("pixel.png", _tiny_png(), "image/png")}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 201, resp.text

    _approve_current_stage(client, admin_token, project["id"])

    resp = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/files",
        files={"file": ("pixel2.png", _tiny_png(), "image/png")}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 409, resp.text


def test_change_request_attachment_only_applies_on_approval(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    requirement = _create_requirement(client, admin_token, project["id"], component_id, category_id)
    _approve_current_stage(client, admin_token, project["id"])

    resource = client.post(
        f"/api/v1/orgs/{org_id}/resources", files={"file": ("shared.png", _tiny_png(), "image/png")},
        headers=auth_headers(admin_token),
    ).json()

    cr = client.post(
        f"/api/v1/projects/{project['id']}/change-requests",
        json={
            "kind": "modify_requirement", "requirement_id": requirement["id"],
            "changed_fields": ["attachments"], "proposed_attachment_file_ids": [resource["id"]],
            "reason": "attach diagram",
        },
        headers=auth_headers(admin_token),
    ).json()

    files_before = client.get(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/files", headers=auth_headers(admin_token)
    ).json()
    assert files_before == []

    client.post(f"/api/v1/projects/{project['id']}/change-requests/{cr['id']}/submit", headers=auth_headers(admin_token))
    decision = client.post(
        f"/api/v1/projects/{project['id']}/change-requests/{cr['id']}/decide",
        json={"approve": True, "note": ""}, headers=auth_headers(admin_token),
    )
    assert decision.status_code == 200, decision.text

    files_after = client.get(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/files", headers=auth_headers(admin_token)
    ).json()
    assert [f["id"] for f in files_after] == [resource["id"]]


def test_change_request_rejects_a_proposed_attachment_from_another_org(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    requirement = _create_requirement(client, admin_token, project["id"], component_id, category_id)

    other_org, other_admin_token = create_org_admin_in(client, admin_token, "Foreign Attachment Org")
    foreign_resource = client.post(
        f"/api/v1/orgs/{other_org['id']}/resources", files={"file": ("foreign.png", _tiny_png(), "image/png")},
        headers=auth_headers(other_admin_token),
    ).json()

    resp = client.post(
        f"/api/v1/projects/{project['id']}/change-requests",
        json={
            "kind": "modify_requirement", "requirement_id": requirement["id"],
            "changed_fields": ["attachments"], "proposed_attachment_file_ids": [foreign_resource["id"]],
            "reason": "attach diagram",
        },
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 400, resp.text


# --- Comment attachments -----------------------------------------------------


def test_comment_attachment_upload_and_download_on_a_requirement(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    requirement = _create_requirement(client, admin_token, project["id"], component_id, category_id)

    comment = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/comments",
        json={"body": "see attached"}, headers=auth_headers(admin_token),
    ).json()
    resp = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/comments/{comment['id']}/files",
        files={"file": ("evidence.png", _tiny_png(), "image/png")}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 201, resp.text
    file_id = resp.json()["id"]

    comments = client.get(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/comments", headers=auth_headers(admin_token)
    ).json()
    fetched_comment = next(c for c in comments if c["id"] == comment["id"])
    assert [a["id"] for a in fetched_comment["attachments"]] == [file_id]

    download = client.get(f"/api/v1/files/{file_id}", headers=auth_headers(admin_token))
    assert download.status_code == 200


def test_comment_attachment_still_allowed_after_requirement_is_locked(client, admin_token, org_id):
    """Comments (and their attachments) aren't governed C-G-12 content —
    unlike direct requirement attachments, they stay usable regardless of
    lock state."""
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    requirement = _create_requirement(client, admin_token, project["id"], component_id, category_id)
    _approve_current_stage(client, admin_token, project["id"])

    comment = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/comments",
        json={"body": "after lock"}, headers=auth_headers(admin_token),
    ).json()
    resp = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/comments/{comment['id']}/files",
        files={"file": ("late.png", _tiny_png(), "image/png")}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 201, resp.text


def test_comment_attachment_on_a_change_request_and_cross_project_isolation(client, admin_token, org_id):
    project_a = create_project(client, admin_token, org_id, "Project A")
    project_b = create_project(client, admin_token, org_id, "Project B")
    comp_a, cat_a = create_component_and_category(client, admin_token, project_a["id"])
    requirement = _create_requirement(client, admin_token, project_a["id"], comp_a, cat_a)

    cr = client.post(
        f"/api/v1/projects/{project_a['id']}/change-requests",
        json={
            "kind": "modify_requirement", "requirement_id": requirement["id"], "changed_fields": ["name"],
            "proposed_name": "x", "reason": "y",
        },
        headers=auth_headers(admin_token),
    ).json()
    comment = client.post(
        f"/api/v1/projects/{project_a['id']}/change-requests/{cr['id']}/comments",
        json={"body": "cr comment"}, headers=auth_headers(admin_token),
    ).json()

    # Wrong project in the URL: not found, not silently allowed.
    resp = client.post(
        f"/api/v1/projects/{project_b['id']}/change-requests/{cr['id']}/comments/{comment['id']}/files",
        files={"file": ("x.png", _tiny_png(), "image/png")}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 404

    resp = client.post(
        f"/api/v1/projects/{project_a['id']}/change-requests/{cr['id']}/comments/{comment['id']}/files",
        files={"file": ("x.png", _tiny_png(), "image/png")}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 201, resp.text


# --- Comment editing (author-only) ------------------------------------------


def test_comment_author_can_edit_body_and_edited_at_gets_stamped(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    requirement = _create_requirement(client, admin_token, project["id"], component_id, category_id)

    comment = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/comments",
        json={"body": "original"}, headers=auth_headers(admin_token),
    ).json()
    assert comment["edited_at"] is None

    resp = client.patch(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/comments/{comment['id']}",
        json={"body": "corrected"}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["body"] == "corrected"
    assert resp.json()["edited_at"] is not None


def test_non_author_cannot_edit_another_users_comment(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    requirement = _create_requirement(client, admin_token, project["id"], component_id, category_id)
    stakeholder_token = _make_project_member(
        client, admin_token, org_id, project["id"], "stakeholder_edit@example.com", "stakeholder"
    )

    comment = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/comments",
        json={"body": "original"}, headers=auth_headers(admin_token),
    ).json()

    resp = client.patch(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/comments/{comment['id']}",
        json={"body": "hijacked"}, headers=auth_headers(stakeholder_token),
    )
    assert resp.status_code == 403, resp.text


def test_non_author_cannot_edit_a_change_request_comment(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    requirement = _create_requirement(client, admin_token, project["id"], component_id, category_id)
    stakeholder_token = _make_project_member(
        client, admin_token, org_id, project["id"], "stakeholder_edit_cr@example.com", "stakeholder"
    )

    cr = client.post(
        f"/api/v1/projects/{project['id']}/change-requests",
        json={
            "kind": "modify_requirement", "requirement_id": requirement["id"], "changed_fields": ["name"],
            "proposed_name": "x", "reason": "y",
        },
        headers=auth_headers(admin_token),
    ).json()
    comment = client.post(
        f"/api/v1/projects/{project['id']}/change-requests/{cr['id']}/comments",
        json={"body": "cr comment"}, headers=auth_headers(admin_token),
    ).json()

    resp = client.patch(
        f"/api/v1/projects/{project['id']}/change-requests/{cr['id']}/comments/{comment['id']}",
        json={"body": "hijacked"}, headers=auth_headers(stakeholder_token),
    )
    assert resp.status_code == 403, resp.text


# --- Comment attachment upload/remove are author-only -----------------------


def test_non_author_cannot_attach_a_file_to_another_users_comment(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    requirement = _create_requirement(client, admin_token, project["id"], component_id, category_id)
    stakeholder_token = _make_project_member(
        client, admin_token, org_id, project["id"], "stakeholder_attach@example.com", "stakeholder"
    )

    comment = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/comments",
        json={"body": "original"}, headers=auth_headers(admin_token),
    ).json()

    resp = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/comments/{comment['id']}/files",
        files={"file": ("sneaky.png", _tiny_png(), "image/png")}, headers=auth_headers(stakeholder_token),
    )
    assert resp.status_code == 403, resp.text


def test_comment_author_can_remove_their_own_attachment(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    requirement = _create_requirement(client, admin_token, project["id"], component_id, category_id)

    comment = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/comments",
        json={"body": "see attached"}, headers=auth_headers(admin_token),
    ).json()
    file_id = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/comments/{comment['id']}/files",
        files={"file": ("evidence.png", _tiny_png(), "image/png")}, headers=auth_headers(admin_token),
    ).json()["id"]

    resp = client.delete(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/comments/{comment['id']}/files/{file_id}",
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 204, resp.text

    comments = client.get(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/comments", headers=auth_headers(admin_token)
    ).json()
    fetched_comment = next(c for c in comments if c["id"] == comment["id"])
    assert fetched_comment["attachments"] == []


def test_non_author_cannot_remove_another_users_comment_attachment(client, admin_token, org_id):
    project = create_project(client, admin_token, org_id)
    component_id, category_id = create_component_and_category(client, admin_token, project["id"])
    requirement = _create_requirement(client, admin_token, project["id"], component_id, category_id)
    stakeholder_token = _make_project_member(
        client, admin_token, org_id, project["id"], "stakeholder_remove@example.com", "stakeholder"
    )

    comment = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/comments",
        json={"body": "see attached"}, headers=auth_headers(admin_token),
    ).json()
    file_id = client.post(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/comments/{comment['id']}/files",
        files={"file": ("evidence.png", _tiny_png(), "image/png")}, headers=auth_headers(admin_token),
    ).json()["id"]

    resp = client.delete(
        f"/api/v1/projects/{project['id']}/requirements/{requirement['id']}/comments/{comment['id']}/files/{file_id}",
        headers=auth_headers(stakeholder_token),
    )
    assert resp.status_code == 403, resp.text
