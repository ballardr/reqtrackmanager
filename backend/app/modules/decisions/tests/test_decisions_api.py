"""Tests for Decision Management's Phase 4 backend API
(docs/plans/module-04-decision-management-plan.md Phase 4) — the real HTTP
endpoints (`project_router.py`/`router.py`), through the `client` fixture,
mirroring `test_compliance_standards_api.py`'s own "go through the real API,
not direct ORM manipulation" convention now that one exists for this module.

Covers: Decision CRUD, list/filter, the content lock once `APPROVED`/
`SUPERSEDED` (409), lifecycle-transition endpoints (including the
mandatory-comment-on-reject rule and an illegal-transition 409), the RBAC
composition (`decision_owner`/`decision_approver`/owner-or-role for
propose, disabled-module-is-404-not-403 vs. wrong-role-is-403), relationship
endpoints (supersession, Decision<->Requirement, Decision<->Decision),
comments/comment-files, direct file attachments (with the same lock
check), Decision Type CRUD + delete-with-reassignment, cross-project 404s,
and the org-scoped Decision Template CRUD.
"""

from __future__ import annotations

import uuid

from app.database import SessionLocal
from app.modules.decisions.models import Decision
from tests.conftest import auth_headers, create_component_and_category, create_org_admin_in, create_project

MODULE_KEY = "decisions"


# --- Small API helpers -------------------------------------------------------


def _current_user_id(client, token: str) -> str:
    resp = client.get("/api/v1/auth/me", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def _enable_decisions_module(client, org_admin_token, org_id) -> None:
    resp = client.put(
        f"/api/v1/orgs/{org_id}/modules/{MODULE_KEY}", json={"enabled": True}, headers=auth_headers(org_admin_token)
    )
    assert resp.status_code == 200, resp.text


def _base(project_id: str) -> str:
    return f"/api/v1/projects/{project_id}/modules/{MODULE_KEY}"


def _org_base(org_id: str) -> str:
    return f"/api/v1/orgs/{org_id}/modules/{MODULE_KEY}"


def _first_decision_type_id(client, token, project_id: str) -> str:
    resp = client.get(f"{_base(project_id)}/decision-types", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()[0]["id"]


def _setup(client, admin_token, org_name: str):
    """Creates an org (with a real org_admin, per every other test's
    `create_org_admin_in` convention), a project (the org_admin becomes
    its `PROJECT_MANAGER`, per `create_project`'s own C-U-10 behaviour),
    and enables Decision Management for the organisation. Returns
    (org, project, org_admin_token)."""
    org, org_admin_token = create_org_admin_in(client, admin_token, org_name)
    _enable_decisions_module(client, org_admin_token, org["id"])
    project = create_project(client, org_admin_token, org["id"], f"{org_name} Project")
    return org, project, org_admin_token


def _add_plain_member(client, org_admin_token, org_id, project_id, email) -> tuple[str, str]:
    """Creates a fresh org user with no org-level privilege, grants them
    `ProjectRole.MEMBER` (view-only) on `project_id`, and returns
    (user_id, token)."""
    from tests.conftest import create_org_user, login

    user_id = create_org_user(client, org_admin_token, org_id, email)
    resp = client.post(
        f"/api/v1/projects/{project_id}/roles", json={"user_id": user_id, "role": "member"},
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 204, resp.text
    return user_id, login(client, email, "Password123!")


def _grant_project_module_role(client, org_admin_token, project_id, user_id, role_key) -> None:
    resp = client.post(
        f"/api/v1/projects/{project_id}/members/{user_id}/module-roles",
        json={"module_key": MODULE_KEY, "role_key": role_key},
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 204, resp.text


def _create_decision(client, token, project_id, decision_type_id, **extra) -> dict:
    payload = {
        "title": "Use Postgres for the primary datastore",
        "decision_statement": "We will use PostgreSQL.",
        "decision_type_id": decision_type_id,
        **extra,
    }
    resp = client.post(_base(project_id), json=payload, headers=auth_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _advance_to_under_review(client, token, project_id, decision_id) -> dict:
    resp = client.post(f"{_base(project_id)}/{decision_id}/propose", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    resp = client.post(f"{_base(project_id)}/{decision_id}/submit-for-review", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _approve(client, token, project_id, decision_id, comment=None) -> dict:
    resp = client.post(
        f"{_base(project_id)}/{decision_id}/approve", json={"comment": comment}, headers=auth_headers(token)
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# --- CRUD, filtering, and the content lock -----------------------------------


def test_create_get_list_update_and_lock_after_approval(client, admin_token):
    _org, project, token = _setup(client, admin_token, "Decision API CRUD Co")
    decision_type_id = _first_decision_type_id(client, token, project["id"])

    created = _create_decision(client, token, project["id"], decision_type_id)
    assert created["status"] == "draft"
    assert created["unique_code"].startswith("DEC-")
    assert created["is_locked"] is False
    assert created["owner_id"] == _current_user_id(client, token)

    fetched = client.get(f"{_base(project['id'])}/{created['id']}", headers=auth_headers(token))
    assert fetched.status_code == 200
    assert fetched.json()["id"] == created["id"]

    listed = client.get(_base(project["id"]), headers=auth_headers(token))
    assert listed.status_code == 200
    assert any(d["id"] == created["id"] for d in listed.json())

    filtered = client.get(
        _base(project["id"]), params={"search": "postgres"}, headers=auth_headers(token)
    )
    assert filtered.status_code == 200
    assert any(d["id"] == created["id"] for d in filtered.json())
    filtered_out = client.get(
        _base(project["id"]), params={"search": "nonexistent-term-xyz"}, headers=auth_headers(token)
    )
    assert filtered_out.json() == []

    update_payload = {**created, "title": "Use Postgres 17"}
    updated = client.put(f"{_base(project['id'])}/{created['id']}", json=update_payload, headers=auth_headers(token))
    assert updated.status_code == 200, updated.text
    assert updated.json()["title"] == "Use Postgres 17"

    _advance_to_under_review(client, token, project["id"], created["id"])
    approved = _approve(client, token, project["id"], created["id"], comment="Looks good.")
    assert approved["status"] == "approved"
    assert approved["is_locked"] is True

    locked_update = client.put(f"{_base(project['id'])}/{created['id']}", json=update_payload, headers=auth_headers(token))
    assert locked_update.status_code == 409

    archived = client.post(f"{_base(project['id'])}/{created['id']}/archive", headers=auth_headers(token))
    assert archived.status_code == 200
    assert archived.json()["is_archived"] is True

    default_listing = client.get(_base(project["id"]), headers=auth_headers(token))
    assert all(d["id"] != created["id"] for d in default_listing.json())
    with_archived = client.get(_base(project["id"]), params={"include_archived": True}, headers=auth_headers(token))
    assert any(d["id"] == created["id"] for d in with_archived.json())

    unarchived = client.post(f"{_base(project['id'])}/{created['id']}/unarchive", headers=auth_headers(token))
    assert unarchived.status_code == 200
    assert unarchived.json()["is_archived"] is False


def test_creating_a_decision_404s_when_the_module_is_disabled(client, admin_token):
    """Disabled/non-entitled module -> 404, not 403 (this codebase's
    established convention, `require_project_module_enabled`'s own
    docstring)."""
    org, org_admin_token = create_org_admin_in(client, admin_token, "Decision API Disabled Module Co")
    project = create_project(client, org_admin_token, org["id"], "Disabled Module Project")
    # The module is never enabled for this org (unlike `_setup`), so even
    # the `decision-types` listing itself 404s — a decision_type_id isn't
    # needed since the request never reaches that far.
    types_listing = client.get(f"{_base(project['id'])}/decision-types", headers=auth_headers(org_admin_token))
    assert types_listing.status_code == 404

    resp = client.post(
        _base(project["id"]),
        json={"title": "T", "decision_statement": "S", "decision_type_id": str(uuid.uuid4())},
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 404


def test_illegal_transition_returns_409(client, admin_token):
    _org, project, token = _setup(client, admin_token, "Decision API Illegal Transition Co")
    decision_type_id = _first_decision_type_id(client, token, project["id"])
    decision = _create_decision(client, token, project["id"], decision_type_id)

    resp = client.post(f"{_base(project['id'])}/{decision['id']}/approve", json={}, headers=auth_headers(token))
    assert resp.status_code == 409


def test_reject_requires_a_comment(client, admin_token):
    _org, project, token = _setup(client, admin_token, "Decision API Reject Comment Co")
    decision_type_id = _first_decision_type_id(client, token, project["id"])
    decision = _create_decision(client, token, project["id"], decision_type_id)
    _advance_to_under_review(client, token, project["id"], decision["id"])

    missing_comment = client.post(
        f"{_base(project['id'])}/{decision['id']}/reject", json={}, headers=auth_headers(token)
    )
    assert missing_comment.status_code == 400

    rejected = client.post(
        f"{_base(project['id'])}/{decision['id']}/reject", json={"comment": "Not aligned."}, headers=auth_headers(token)
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"


def test_cross_project_access_is_404(client, admin_token):
    _org, project_a, token = _setup(client, admin_token, "Decision API Cross Project A Co")
    decision_type_id = _first_decision_type_id(client, token, project_a["id"])
    decision = _create_decision(client, token, project_a["id"], decision_type_id)

    _org_b, project_b, token_b = _setup(client, admin_token, "Decision API Cross Project B Co")
    resp = client.get(f"{_base(project_b['id'])}/{decision['id']}", headers=auth_headers(token_b))
    assert resp.status_code == 404


# --- RBAC: ordinary member propose-own vs. decision_owner/decision_approver --


def test_ordinary_member_can_propose_own_decision_but_not_edit_it(client, admin_token):
    org, project, org_admin_token = _setup(client, admin_token, "Decision API Member RBAC Co")
    decision_type_id = _first_decision_type_id(client, org_admin_token, project["id"])
    _member_id, member_token = _add_plain_member(
        client, org_admin_token, org["id"], project["id"], "decisions_member_a@example.com"
    )

    own_decision = _create_decision(client, member_token, project["id"], decision_type_id)
    assert own_decision["status"] == "draft"

    proposed = client.post(f"{_base(project['id'])}/{own_decision['id']}/propose", headers=auth_headers(member_token))
    assert proposed.status_code == 200, proposed.text
    assert proposed.json()["status"] == "proposed"

    edit_attempt = client.put(
        f"{_base(project['id'])}/{own_decision['id']}", json={**proposed.json(), "title": "New title"},
        headers=auth_headers(member_token),
    )
    assert edit_attempt.status_code == 403


def test_ordinary_member_cannot_propose_someone_elses_decision(client, admin_token):
    org, project, org_admin_token = _setup(client, admin_token, "Decision API Member Propose Others Co")
    decision_type_id = _first_decision_type_id(client, org_admin_token, project["id"])
    _member_id, member_token = _add_plain_member(
        client, org_admin_token, org["id"], project["id"], "decisions_member_b@example.com"
    )
    pm_owned_decision = _create_decision(client, org_admin_token, project["id"], decision_type_id)

    resp = client.post(
        f"{_base(project['id'])}/{pm_owned_decision['id']}/propose", headers=auth_headers(member_token)
    )
    assert resp.status_code == 403


def test_approve_and_reject_require_decision_approver_role(client, admin_token):
    org, project, org_admin_token = _setup(client, admin_token, "Decision API Approver RBAC Co")
    decision_type_id = _first_decision_type_id(client, org_admin_token, project["id"])
    member_id, member_token = _add_plain_member(
        client, org_admin_token, org["id"], project["id"], "decisions_approver_candidate@example.com"
    )
    decision = _create_decision(client, org_admin_token, project["id"], decision_type_id)
    _advance_to_under_review(client, org_admin_token, project["id"], decision["id"])

    forbidden = client.post(
        f"{_base(project['id'])}/{decision['id']}/approve", json={}, headers=auth_headers(member_token)
    )
    assert forbidden.status_code == 403

    _grant_project_module_role(client, org_admin_token, project["id"], member_id, "decision_approver")
    approved = client.post(
        f"{_base(project['id'])}/{decision['id']}/approve", json={"comment": "OK"}, headers=auth_headers(member_token)
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"


def test_decision_type_management_requires_decision_owner_role(client, admin_token):
    org, project, org_admin_token = _setup(client, admin_token, "Decision API Owner RBAC Co")
    _member_id, member_token = _add_plain_member(
        client, org_admin_token, org["id"], project["id"], "decisions_owner_candidate@example.com"
    )

    forbidden = client.post(
        f"{_base(project['id'])}/decision-types", json={"name": "Regulatory"}, headers=auth_headers(member_token)
    )
    assert forbidden.status_code == 403

    created = client.post(
        f"{_base(project['id'])}/decision-types", json={"name": "Regulatory"}, headers=auth_headers(org_admin_token)
    )
    assert created.status_code == 201, created.text


# --- Decision Type CRUD + delete-with-reassignment ---------------------------


def test_decision_type_crud_and_delete_with_reassignment(client, admin_token):
    _org, project, token = _setup(client, admin_token, "Decision API Types Co")
    listed = client.get(f"{_base(project['id'])}/decision-types", headers=auth_headers(token))
    assert listed.status_code == 200
    default_types = listed.json()
    assert len(default_types) == 5

    created = client.post(
        f"{_base(project['id'])}/decision-types", json={"name": "Custom Type"}, headers=auth_headers(token)
    )
    assert created.status_code == 201
    new_type_id = created.json()["id"]

    renamed = client.patch(
        f"{_base(project['id'])}/decision-types/{new_type_id}", json={"name": "Renamed Type"},
        headers=auth_headers(token),
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Renamed Type"

    moved = client.post(
        f"{_base(project['id'])}/decision-types/{new_type_id}/move", json={"direction": "up"},
        headers=auth_headers(token),
    )
    assert moved.status_code == 200

    # Unused: deletes outright.
    deleted = client.delete(f"{_base(project['id'])}/decision-types/{new_type_id}", headers=auth_headers(token))
    assert deleted.status_code == 204

    # In use: 409 without reassign_to_id, 204 with it, and the referencing
    # Decision is reassigned.
    in_use_type_id = default_types[0]["id"]
    other_type_id = default_types[1]["id"]
    decision = _create_decision(client, token, project["id"], in_use_type_id)

    blocked = client.delete(f"{_base(project['id'])}/decision-types/{in_use_type_id}", headers=auth_headers(token))
    assert blocked.status_code == 409

    reassigned = client.delete(
        f"{_base(project['id'])}/decision-types/{in_use_type_id}", params={"reassign_to_id": other_type_id},
        headers=auth_headers(token),
    )
    assert reassigned.status_code == 204

    db = SessionLocal()
    try:
        refreshed = db.get(Decision, uuid.UUID(decision["id"]))
        assert str(refreshed.decision_type_id) == other_type_id
    finally:
        db.close()


# --- Relationships ------------------------------------------------------------


def test_supersession_via_api(client, admin_token):
    _org, project, token = _setup(client, admin_token, "Decision API Supersession Co")
    decision_type_id = _first_decision_type_id(client, token, project["id"])
    old_decision = _create_decision(client, token, project["id"], decision_type_id)
    new_decision = _create_decision(client, token, project["id"], decision_type_id, title="Replacement decision")
    for d in (old_decision, new_decision):
        _advance_to_under_review(client, token, project["id"], d["id"])
        _approve(client, token, project["id"], d["id"])

    created = client.post(
        f"{_base(project['id'])}/{new_decision['id']}/supersessions",
        json={"old_decision_id": old_decision["id"]}, headers=auth_headers(token),
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["direction"] == "outgoing"
    assert body["display_name"] == "Supersedes"
    assert body["other_id"] == old_decision["id"]
    assert body["other_display_code"] == old_decision["unique_code"]

    duplicate = client.post(
        f"{_base(project['id'])}/{new_decision['id']}/supersessions",
        json={"old_decision_id": old_decision["id"]}, headers=auth_headers(token),
    )
    assert duplicate.status_code == 409

    old_after = client.get(f"{_base(project['id'])}/{old_decision['id']}", headers=auth_headers(token))
    assert old_after.json()["status"] == "superseded"

    relationships = client.get(
        f"{_base(project['id'])}/{old_decision['id']}/relationships", headers=auth_headers(token)
    )
    assert relationships.status_code == 200
    assert any(r["direction"] == "incoming" and r["other_id"] == new_decision["id"] for r in relationships.json())


def test_decision_requirement_and_decision_decision_links_via_api(client, admin_token):
    _org, project, token = _setup(client, admin_token, "Decision API Links Co")
    decision_type_id = _first_decision_type_id(client, token, project["id"])
    decision_a = _create_decision(client, token, project["id"], decision_type_id)
    decision_b = _create_decision(client, token, project["id"], decision_type_id, title="Second decision")

    component_id, category_id = create_component_and_category(client, token, project["id"])
    requirement = client.post(
        f"/api/v1/projects/{project['id']}/requirements",
        json={"name": "Must use durable storage", "component_id": component_id, "category_id": category_id},
        headers=auth_headers(token),
    ).json()

    req_link = client.post(
        f"{_base(project['id'])}/{decision_a['id']}/requirement-links",
        json={"requirement_id": requirement["id"], "kind": "implements"}, headers=auth_headers(token),
    )
    assert req_link.status_code == 201, req_link.text
    assert req_link.json()["display_name"] == "Implements"
    assert req_link.json()["other_display_code"] == requirement["unique_code"]

    duplicate_req_link = client.post(
        f"{_base(project['id'])}/{decision_a['id']}/requirement-links",
        json={"requirement_id": requirement["id"], "kind": "implements"}, headers=auth_headers(token),
    )
    assert duplicate_req_link.status_code == 409

    dec_link = client.post(
        f"{_base(project['id'])}/{decision_a['id']}/decision-links",
        json={"target_decision_id": decision_b["id"], "kind": "depends_on"}, headers=auth_headers(token),
    )
    assert dec_link.status_code == 201, dec_link.text
    assert dec_link.json()["display_name"] == "Depends on"
    assert dec_link.json()["other_display_code"] == decision_b["unique_code"]

    self_link = client.post(
        f"{_base(project['id'])}/{decision_a['id']}/decision-links",
        json={"target_decision_id": decision_a["id"], "kind": "depends_on"}, headers=auth_headers(token),
    )
    assert self_link.status_code == 409


# --- Comments and files -------------------------------------------------------


def test_comments_and_comment_files(client, admin_token):
    org, project, org_admin_token = _setup(client, admin_token, "Decision API Comments Co")
    decision_type_id = _first_decision_type_id(client, org_admin_token, project["id"])
    decision = _create_decision(client, org_admin_token, project["id"], decision_type_id)
    _member_id, member_token = _add_plain_member(
        client, org_admin_token, org["id"], project["id"], "decisions_commenter@example.com"
    )

    comment = client.post(
        f"{_base(project['id'])}/{decision['id']}/comments", json={"body": "Have we considered SQLite?"},
        headers=auth_headers(member_token),
    )
    assert comment.status_code == 201, comment.text
    comment_id = comment.json()["id"]

    listed = client.get(f"{_base(project['id'])}/{decision['id']}/comments", headers=auth_headers(org_admin_token))
    assert listed.status_code == 200
    assert any(c["id"] == comment_id for c in listed.json())

    forbidden_edit = client.patch(
        f"{_base(project['id'])}/{decision['id']}/comments/{comment_id}", json={"body": "edited"},
        headers=auth_headers(org_admin_token),
    )
    assert forbidden_edit.status_code == 403

    own_edit = client.patch(
        f"{_base(project['id'])}/{decision['id']}/comments/{comment_id}", json={"body": "Edited: what about SQLite?"},
        headers=auth_headers(member_token),
    )
    assert own_edit.status_code == 200
    assert own_edit.json()["edited_at"] is not None

    upload = client.post(
        f"{_base(project['id'])}/{decision['id']}/comments/{comment_id}/files",
        files={"file": ("note.txt", b"hello", "text/plain")}, headers=auth_headers(member_token),
    )
    assert upload.status_code == 201, upload.text
    file_id = upload.json()["id"]

    forbidden_upload = client.post(
        f"{_base(project['id'])}/{decision['id']}/comments/{comment_id}/files",
        files={"file": ("note2.txt", b"hi", "text/plain")}, headers=auth_headers(org_admin_token),
    )
    assert forbidden_upload.status_code == 403

    removed = client.delete(
        f"{_base(project['id'])}/{decision['id']}/comments/{comment_id}/files/{file_id}",
        headers=auth_headers(member_token),
    )
    assert removed.status_code == 204


def test_decision_file_attachment_and_lock(client, admin_token):
    _org, project, token = _setup(client, admin_token, "Decision API Files Co")
    decision_type_id = _first_decision_type_id(client, token, project["id"])
    decision = _create_decision(client, token, project["id"], decision_type_id)

    upload = client.post(
        f"{_base(project['id'])}/{decision['id']}/files",
        files={"file": ("spec.pdf", b"%PDF-1.4", "application/pdf")}, headers=auth_headers(token),
    )
    assert upload.status_code == 201, upload.text
    file_id = upload.json()["id"]

    listed = client.get(f"{_base(project['id'])}/{decision['id']}/files", headers=auth_headers(token))
    assert listed.status_code == 200
    assert any(f["id"] == file_id for f in listed.json())

    unlinked = client.delete(f"{_base(project['id'])}/{decision['id']}/files/{file_id}", headers=auth_headers(token))
    assert unlinked.status_code == 204

    _advance_to_under_review(client, token, project["id"], decision["id"])
    _approve(client, token, project["id"], decision["id"])

    blocked_upload = client.post(
        f"{_base(project['id'])}/{decision['id']}/files",
        files={"file": ("late.pdf", b"%PDF-1.4", "application/pdf")}, headers=auth_headers(token),
    )
    assert blocked_upload.status_code == 409


# --- Org-scoped Decision Template CRUD ---------------------------------------


def test_decision_template_crud_requires_org_admin(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "Decision API Templates Co")
    _enable_decisions_module(client, org_admin_token, org["id"])

    from tests.conftest import create_org_user, login

    create_org_user(client, org_admin_token, org["id"], "decisions_template_member@example.com")
    member_token = login(client, "decisions_template_member@example.com", "Password123!")

    forbidden = client.post(
        f"{_org_base(org['id'])}/templates", json={"name": "Custom Template"}, headers=auth_headers(member_token)
    )
    assert forbidden.status_code == 403

    created = client.post(
        f"{_org_base(org['id'])}/templates", json={"name": "Custom Template", "context_prompt": "Why?"},
        headers=auth_headers(org_admin_token),
    )
    assert created.status_code == 201, created.text
    template_id = created.json()["id"]

    listed = client.get(f"{_org_base(org['id'])}/templates", headers=auth_headers(member_token))
    assert listed.status_code == 200
    assert any(t["id"] == template_id for t in listed.json())

    updated = client.patch(
        f"{_org_base(org['id'])}/templates/{template_id}", json={"name": "Renamed Template"},
        headers=auth_headers(org_admin_token),
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Renamed Template"

    deleted = client.delete(f"{_org_base(org['id'])}/templates/{template_id}", headers=auth_headers(org_admin_token))
    assert deleted.status_code == 204

    # Cross-org isolation: a second organisation cannot reach the first's templates.
    other_org, other_admin_token = create_org_admin_in(client, admin_token, "Decision API Templates Other Co")
    _enable_decisions_module(client, other_admin_token, other_org["id"])
    created_2 = client.post(
        f"{_org_base(org['id'])}/templates", json={"name": "Org 1 Template"}, headers=auth_headers(org_admin_token)
    ).json()
    cross_org = client.get(
        f"{_org_base(other_org['id'])}/templates/{created_2['id']}", headers=auth_headers(other_admin_token)
    )
    assert cross_org.status_code in (404, 405)  # no GET-by-id endpoint exists; ensures no leakage either way


# --- resolve_file_owner_project_id hook (Phase 4) -----------------------------


def test_resolve_decision_file_project_id_hook(client, admin_token):
    from app.modules.decisions.service import resolve_decision_file_project_id

    _org, project, token = _setup(client, admin_token, "Decision API File Hook Co")
    decision_type_id = _first_decision_type_id(client, token, project["id"])
    decision = _create_decision(client, token, project["id"], decision_type_id)
    upload = client.post(
        f"{_base(project['id'])}/{decision['id']}/files",
        files={"file": ("evidence.txt", b"data", "text/plain")}, headers=auth_headers(token),
    )
    assert upload.status_code == 201
    file_id = upload.json()["id"]

    db = SessionLocal()
    try:
        resolved_project_id = resolve_decision_file_project_id(db, uuid.UUID(file_id))
        assert resolved_project_id == uuid.UUID(project["id"])
        assert resolve_decision_file_project_id(db, uuid.uuid4()) is None
    finally:
        db.close()

    # The core download endpoint can serve it without any decisions-module import.
    download = client.get(f"/api/v1/files/{file_id}", headers=auth_headers(token))
    assert download.status_code == 200
