"""Tests for the project-scoped Product Feedback API: create (starts New with a code), read, partial update as a
new version, the lifecycle (what each move demands, no direct move to duplicate), archive, versions, owners, comments
and files, the triager gate, and tenant isolation. Each test builds its own organisation."""

from __future__ import annotations

import uuid

from app.modules.product_feedback.tests._helpers import (
    add_member,
    create_request,
    grant_project_role,
    project_base,
    setup,
    transition,
    user_ref,
)
from tests.conftest import auth_headers


def _get(client, token, project_id, request_id) -> dict:
    resp = client.get(f"{project_base(project_id)}/requests/{request_id}", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_a_request_is_created_new_with_a_project_code_and_its_content(client, admin_token):
    _, project, token = setup(client, admin_token, "Feedback Create Co")
    request = create_request(client, token, project["id"], external_ref_url="https://jira.example/PROJ-1", external_ref_key="PROJ-1")
    assert request["status"] == "new" and request["scope"] == "project"
    assert request["unique_code"] == "ENH-001" and request["project_id"] == project["id"]
    assert request["organization_id"] is None and request["version_number"] == 1
    # The older single link pair is filed as a delivery reference on the "Other" system.
    assert [(r["system_name"], r["key"], r["url"], r["role"]) for r in request["external_refs"]] == [
        ("Other", "PROJ-1", "https://jira.example/PROJ-1", "delivery")
    ]
    assert request["owner"] is None
    assert request["allowed_next_statuses"] == ["under_review", "declined"]
    assert create_request(client, token, project["id"], title="Second")["unique_code"] == "ENH-002"


def test_a_title_is_required(client, admin_token):
    _, project, token = setup(client, admin_token, "Feedback Title Co")
    resp = client.post(project_base(project["id"]) + "/requests", json={"title": ""}, headers=auth_headers(token))
    assert resp.status_code == 422


def test_an_update_is_a_new_version_that_keeps_the_fields_it_does_not_mention(client, admin_token):
    _, project, token = setup(client, admin_token, "Feedback Update Co")
    request = create_request(client, token, project["id"])
    base = f"{project_base(project['id'])}/requests/{request['id']}"
    resp = client.put(base, json={"description": "Better words.", "change_note": "Reworded."}, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    updated = resp.json()
    assert updated["version_number"] == 2 and updated["description"] == "Better words." and updated["title"] == request["title"]
    versions = client.get(base + "/versions", headers=auth_headers(token)).json()
    assert [v["version_number"] for v in versions] == [1, 2]
    assert versions[0]["valid_to"] is not None and versions[1]["valid_to"] is None
    assert versions[1]["change_note"] == "Reworded." and versions[0]["description"] == request["description"]


def test_a_null_title_is_refused_and_clearing_the_older_link_pair_removes_its_reference(client, admin_token):
    _, project, token = setup(client, admin_token, "Feedback Null Co")
    request = create_request(client, token, project["id"], external_ref_key="PROJ-9")
    base = f"{project_base(project['id'])}/requests/{request['id']}"
    assert client.put(base, json={"title": None}, headers=auth_headers(token)).status_code == 422
    cleared = client.put(base, json={"external_ref_key": None}, headers=auth_headers(token)).json()
    assert cleared["external_refs"] == []
    assert cleared["version_number"] == 1  # a reference is not a content version


def test_the_owner_may_be_a_user_and_is_cleared_by_null(client, admin_token):
    org, project, token = setup(client, admin_token, "Feedback Owner Co")
    user_id, _ = add_member(client, token, org["id"], project["id"], "owner.feedback@example.com")
    request = create_request(client, token, project["id"], owner=user_ref(user_id))
    assert request["owner"]["id"] == user_id and request["owner"]["type"] == "user"
    base = f"{project_base(project['id'])}/requests/{request['id']}"
    assert client.put(base, json={"owner": None}, headers=auth_headers(token)).json()["owner"] is None


def test_an_owner_outside_the_organisation_is_refused(client, admin_token):
    _, project, token = setup(client, admin_token, "Feedback Stranger Co")
    resp = client.post(
        project_base(project["id"]) + "/requests", json={"title": "x", "owner": user_ref(str(uuid.uuid4()))},
        headers=auth_headers(token),
    )
    assert resp.status_code == 400


def test_the_lifecycle_moves_along_the_main_line_and_back(client, admin_token):
    _, project, token = setup(client, admin_token, "Feedback Lifecycle Co")
    base = project_base(project["id"])
    request = create_request(client, token, project["id"])
    for target in ("under_review", "accepted", "delivered"):
        resp = transition(client, token, base, request["id"], target)
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == target
    assert transition(client, token, base, request["id"], "accepted").json()["status"] == "accepted"
    assert [v["status"] for v in client.get(f"{base}/requests/{request['id']}/versions", headers=auth_headers(token)).json()] == [
        "new", "under_review", "accepted", "delivered", "accepted",
    ]


def test_an_illegal_move_is_refused_with_a_conflict(client, admin_token):
    _, project, token = setup(client, admin_token, "Feedback Illegal Co")
    base = project_base(project["id"])
    request = create_request(client, token, project["id"])
    resp = transition(client, token, base, request["id"], "delivered")
    assert resp.status_code == 409 and "New" in resp.json()["detail"] and "Delivered" in resp.json()["detail"]


def test_declining_needs_a_reason_which_is_stored_and_cleared_on_reopening(client, admin_token):
    _, project, token = setup(client, admin_token, "Feedback Decline Co")
    base = project_base(project["id"])
    request = create_request(client, token, project["id"])
    assert transition(client, token, base, request["id"], "declined").status_code == 409
    assert transition(client, token, base, request["id"], "declined", "   ").status_code == 409
    declined = transition(client, token, base, request["id"], "declined", "Out of scope for this product.").json()
    assert declined["status"] == "declined" and declined["decline_reason"] == "Out of scope for this product."
    assert declined["allowed_next_statuses"] == ["new"]
    reopened = transition(client, token, base, request["id"], "new").json()
    assert reopened["decline_reason"] == ""


def test_a_request_cannot_be_moved_to_duplicate_directly(client, admin_token):
    _, project, token = setup(client, admin_token, "Feedback Duplicate Co")
    base = project_base(project["id"])
    request = create_request(client, token, project["id"])
    resp = transition(client, token, base, request["id"], "duplicate")
    assert resp.status_code == 409 and "merged" in resp.json()["detail"]
    assert "duplicate" not in request["allowed_next_statuses"]


def test_archiving_hides_a_request_from_the_list_and_blocks_status_changes(client, admin_token):
    _, project, token = setup(client, admin_token, "Feedback Archive Co")
    base = project_base(project["id"])
    request = create_request(client, token, project["id"])
    resp = client.post(f"{base}/requests/{request['id']}/archive", headers=auth_headers(token))
    assert resp.status_code == 200 and resp.json()["is_archived"] is True
    assert client.get(base + "/requests", headers=auth_headers(token)).json() == []
    assert len(client.get(base + "/requests", params={"include_archived": "true"}, headers=auth_headers(token)).json()) == 1
    assert transition(client, token, base, request["id"], "under_review").status_code == 409
    resp = client.post(f"{base}/requests/{request['id']}/unarchive", headers=auth_headers(token))
    assert resp.json()["is_archived"] is False
    assert transition(client, token, base, request["id"], "under_review").status_code == 200


def test_the_list_filters_by_status_open_only_and_search(client, admin_token):
    _, project, token = setup(client, admin_token, "Feedback Filter Co")
    base = project_base(project["id"])
    a = create_request(client, token, project["id"], title="Alpha exporter")
    b = create_request(client, token, project["id"], title="Beta importer", description="zzmatch")
    c = create_request(client, token, project["id"], title="Gamma")
    transition(client, token, base, b["id"], "declined", "No.")
    transition(client, token, base, c["id"], "under_review")

    def ids(**params) -> set:
        resp = client.get(base + "/requests", params=params, headers=auth_headers(token))
        assert resp.status_code == 200, resp.text
        return {r["id"] for r in resp.json()}

    assert ids() == {a["id"], b["id"], c["id"]}
    assert ids(status="declined") == {b["id"]}
    assert ids(open_only="true") == {a["id"], c["id"]}
    assert ids(search="ZZMATCH") == {b["id"]}
    assert ids(search=a["unique_code"]) == {a["id"]}


def test_a_member_submits_and_comments_but_only_a_triager_edits_and_moves(client, admin_token):
    org, project, admin = setup(client, admin_token, "Feedback Gate Co")
    _, member = add_member(client, admin, org["id"], project["id"], "member.gate@example.com")
    triager_id, triager = add_member(client, admin, org["id"], project["id"], "triager.gate@example.com")
    grant_project_role(client, admin, project["id"], triager_id, "feedback_triager")
    base = project_base(project["id"])

    request = create_request(client, member, project["id"], title="From a member")
    path = f"{base}/requests/{request['id']}"
    assert client.get(path, headers=auth_headers(member)).status_code == 200
    assert client.put(path, json={"title": "Hijack"}, headers=auth_headers(member)).status_code == 403
    assert transition(client, member, base, request["id"], "under_review").status_code == 403
    assert client.post(f"{path}/archive", headers=auth_headers(member)).status_code == 403
    assert client.post(f"{path}/comments", json={"body": "Me too"}, headers=auth_headers(member)).status_code == 201

    assert client.put(path, json={"title": "Reworded"}, headers=auth_headers(triager)).status_code == 200
    assert transition(client, triager, base, request["id"], "under_review").status_code == 200


def test_comments_can_be_added_edited_by_their_author_only_and_listed(client, admin_token):
    org, project, admin = setup(client, admin_token, "Feedback Comment Co")
    _, member = add_member(client, admin, org["id"], project["id"], "commenter.fb@example.com")
    request = create_request(client, admin, project["id"])
    path = f"{project_base(project['id'])}/requests/{request['id']}/comments"
    comment = client.post(path, json={"body": "First"}, headers=auth_headers(member)).json()
    assert comment["body"] == "First" and comment["request_id"] == request["id"]
    assert client.patch(f"{path}/{comment['id']}", json={"body": "Edited"}, headers=auth_headers(admin)).status_code == 403
    edited = client.patch(f"{path}/{comment['id']}", json={"body": "Edited"}, headers=auth_headers(member)).json()
    assert edited["body"] == "Edited" and edited["edited_at"] is not None
    assert [c["body"] for c in client.get(path, headers=auth_headers(admin)).json()] == ["Edited"]


def test_evidence_files_attach_list_and_unlink_for_a_triager_only(client, admin_token):
    org, project, admin = setup(client, admin_token, "Feedback Files Co")
    _, member = add_member(client, admin, org["id"], project["id"], "filer.fb@example.com")
    request = create_request(client, admin, project["id"])
    path = f"{project_base(project['id'])}/requests/{request['id']}/files"
    upload = {"file": ("note.txt", b"evidence", "text/plain")}
    assert client.post(path, files=upload, headers=auth_headers(member)).status_code == 403
    resp = client.post(path, files=upload, headers=auth_headers(admin))
    assert resp.status_code == 201, resp.text
    file_id = resp.json()["id"]
    assert [f["id"] for f in client.get(path, headers=auth_headers(member)).json()] == [file_id]
    download = client.get(f"/api/v1/files/{file_id}", headers=auth_headers(member))
    assert download.status_code == 200 and download.content == b"evidence"
    assert client.delete(f"{path}/{file_id}", headers=auth_headers(member)).status_code == 403
    assert client.delete(f"{path}/{file_id}", headers=auth_headers(admin)).status_code == 204


def test_another_projects_request_looks_absent(client, admin_token):
    org, project, token = setup(client, admin_token, "Feedback Tenant Co")
    from tests.conftest import create_project

    other = create_project(client, token, org["id"], "Other project")
    request = create_request(client, token, project["id"])
    resp = client.get(f"{project_base(other['id'])}/requests/{request['id']}", headers=auth_headers(token))
    assert resp.status_code == 404
    assert client.get(f"{project_base(project['id'])}/requests/{uuid.uuid4()}", headers=auth_headers(token)).status_code == 404


def test_a_disabled_module_answers_404(client, admin_token):
    org, project, token = setup(client, admin_token, "Feedback Off Co")
    create_request(client, token, project["id"])
    resp = client.put(f"/api/v1/orgs/{org['id']}/modules/product_feedback", json={"enabled": False}, headers=auth_headers(token))
    assert resp.status_code == 200
    assert client.get(project_base(project["id"]) + "/requests", headers=auth_headers(token)).status_code == 404


def test_every_mutation_is_audit_logged_against_the_request(client, admin_token):
    from sqlalchemy import select

    from app.database import SessionLocal
    from app.models.audit import AuditEvent

    _, project, token = setup(client, admin_token, "Feedback Audit Co")
    h = auth_headers(token)
    base = project_base(project["id"])
    request = create_request(client, token, project["id"])
    path = f"{base}/requests/{request['id']}"
    client.put(path, json={"description": "Changed."}, headers=h)
    transition(client, token, base, request["id"], "declined", "Not now.")
    client.post(f"{path}/archive", headers=h)
    client.post(f"{path}/unarchive", headers=h)
    client.post(f"{path}/comments", json={"body": "Hello"}, headers=h)
    with SessionLocal() as db:
        events = list(db.scalars(
            select(AuditEvent).where(AuditEvent.entity_type == "enhancement_request", AuditEvent.entity_id == request["id"])
            .order_by(AuditEvent.created_at)
        ))
    assert [e.action for e in events] == ["created", "updated", "status_changed", "archived", "unarchived", "comment_added"]
    assert all(str(e.project_id) == project["id"] for e in events)
    assert events[2].detail == {"from": "new", "to": "declined", "comment": "Not now."}
    assert "Changed." not in str([e.detail for e in events])  # content is never put in the audit trail


def test_the_delivery_tool_link_must_be_an_http_url(client, admin_token):
    """The reference is rendered as a link, so a `javascript:` URL is refused on create and update (and on import,
    which builds the same payload)."""
    _, project, token = setup(client, admin_token, "Feedback Url Co")
    base = project_base(project["id"]) + "/requests"
    for bad in ("javascript:alert(1)", "data:text/html,x", "ftp://files.example/a", "//no-scheme.example", "https://"):
        refused = client.post(base, json={"title": "Bad link", "external_ref_url": bad}, headers=auth_headers(token))
        assert refused.status_code == 422, bad
    request = create_request(client, token, project["id"], external_ref_url=" https://jira.example/PROJ-9 ")
    assert [r["url"] for r in request["external_refs"]] == ["https://jira.example/PROJ-9"]
    refused = client.put(
        f"{base}/{request['id']}", json={"external_ref_url": "javascript:alert(1)"}, headers=auth_headers(token),
    )
    assert refused.status_code == 422
    cleared = client.put(f"{base}/{request['id']}", json={"external_ref_url": None}, headers=auth_headers(token))
    assert cleared.status_code == 200 and cleared.json()["external_refs"] == []
