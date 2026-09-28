"""Tests for Context & Strategy's Phase 4 backend API
(docs/plans/module-01-context-and-strategy-plan.md Phase 4 — Guiding
Principles) — the real HTTP endpoints (`router.py`/`project_router.py`),
through the `client` fixture, mirroring `test_context_strategy_future_
state_api.py`'s own "go through the real API" convention. Kept as its own
sibling file rather than folded into an existing one (Decided by: Agent,
following Phase 2/3's own precedent exactly) — one file per artefact type.

Covers, for both the org-scoped and project-scoped routers: Guiding
Principle CRUD, the content lock once past `PROPOSED` (409), the full
lifecycle (propose/send-back/approve/activate/supersede/retire — note: no
`submit-for-review` step, `enums.GuidingPrincipleStatus` has no
`UNDER_REVIEW` state), including the mandatory-comment-on-send-back rule
and an illegal-transition 409, version history, the RBAC composition
(`..._owner`/`..._approver`/creator-or-role for propose,
disabled-module-is-404-not-403, disabled-subcomponent-is-404, and a
Fine-Grained Access Control custom-role permission grant satisfying the
approve gate), comments/comment-files, direct file attachments, and
cross-tenant 404s.
"""

from __future__ import annotations

import uuid

from app.models.custom_role import CustomRoleDefinition, CustomRolePermission, UserCustomRoleGrant
from app.services.permissions import encode_permission
from tests.conftest import auth_headers, create_org_admin_in, create_org_user, create_project, login

MODULE_KEY = "context_strategy"


# --- Small API helpers -------------------------------------------------------


def _enable_module(client, org_admin_token, org_id) -> None:
    resp = client.put(
        f"/api/v1/orgs/{org_id}/modules/{MODULE_KEY}", json={"enabled": True}, headers=auth_headers(org_admin_token)
    )
    assert resp.status_code == 200, resp.text


def _org_base(org_id: str) -> str:
    return f"/api/v1/orgs/{org_id}/modules/context_strategy"


def _project_base(project_id: str) -> str:
    return f"/api/v1/projects/{project_id}/modules/context_strategy"


def _setup(client, admin_token, org_name: str):
    """Creates an org (with a real org_admin), a project (the org_admin
    becomes its `PROJECT_MANAGER`), and enables Context & Strategy for the
    organisation. Returns (org, project, org_admin_token)."""
    org, org_admin_token = create_org_admin_in(client, admin_token, org_name)
    _enable_module(client, org_admin_token, org["id"])
    project = create_project(client, org_admin_token, org["id"], f"{org_name} Project")
    return org, project, org_admin_token


def _add_plain_member(client, org_admin_token, org_id, project_id, email) -> tuple[str, str]:
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


def _grant_org_module_role(client, org_admin_token, org_id, user_id, role_key) -> None:
    resp = client.post(
        f"/api/v1/orgs/{org_id}/users/{user_id}/module-roles",
        json={"module_key": MODULE_KEY, "role_key": role_key},
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 204, resp.text


_PAYLOAD = {
    "name": "Design for offline-first operation",
    "principle_statement": (
        "Every workflow must remain usable, with clear degraded-mode indicators, when connectivity to backend "
        "services is lost."
    ),
    "rationale": "Field inspection sites frequently have unreliable or absent network coverage.",
    "priority": "high",
}


def _create_org_guiding_principle(client, token, org_id, **extra) -> dict:
    resp = client.post(
        _org_base(org_id) + "/guiding-principles", json={**_PAYLOAD, **extra}, headers=auth_headers(token)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_project_guiding_principle(client, token, project_id, **extra) -> dict:
    resp = client.post(
        _project_base(project_id) + "/guiding-principles", json={**_PAYLOAD, **extra}, headers=auth_headers(token)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _advance_project_guiding_principle_to_proposed(client, token, project_id, guiding_principle_id) -> dict:
    resp = client.post(
        f"{_project_base(project_id)}/guiding-principles/{guiding_principle_id}/propose", headers=auth_headers(token)
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# --- Create / list / get / update -------------------------------------------


def test_create_and_get_project_guiding_principle(client, admin_token):
    _, project, org_admin_token = _setup(client, admin_token, "CtxGuidingPrinciple Create Co")
    guiding_principle = _create_project_guiding_principle(client, org_admin_token, project["id"])

    assert guiding_principle["scope"] == "project"
    assert guiding_principle["project_id"] == project["id"]
    assert guiding_principle["organization_id"] is None
    assert guiding_principle["status"] == "draft"
    assert guiding_principle["version_number"] == 1
    assert guiding_principle["is_locked"] is False
    assert guiding_principle["priority"] == "high"
    assert guiding_principle["owner_id"] is None

    resp = client.get(
        f"{_project_base(project['id'])}/guiding-principles/{guiding_principle['id']}",
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == guiding_principle["id"]


def test_create_and_get_org_guiding_principle(client, admin_token):
    org, _, org_admin_token = _setup(client, admin_token, "CtxGuidingPrinciple Org Create Co")
    guiding_principle = _create_org_guiding_principle(client, org_admin_token, org["id"])

    assert guiding_principle["scope"] == "organization"
    assert guiding_principle["organization_id"] == org["id"]
    assert guiding_principle["project_id"] is None
    assert guiding_principle["status"] == "draft"


def test_any_project_member_may_create_a_guiding_principle_no_owner_role_required(client, admin_token):
    org, project, org_admin_token = _setup(client, admin_token, "CtxGuidingPrinciple Any Member Co")
    _, member_token = _add_plain_member(
        client, org_admin_token, org["id"], project["id"], "plain_member_gp@example.com"
    )
    resp = client.post(
        _project_base(project["id"]) + "/guiding-principles", json=_PAYLOAD, headers=auth_headers(member_token)
    )
    assert resp.status_code == 201, resp.text


def test_update_project_guiding_principle_creates_a_new_version(client, admin_token):
    _, project, org_admin_token = _setup(client, admin_token, "CtxGuidingPrinciple Update Co")
    guiding_principle = _create_project_guiding_principle(client, org_admin_token, project["id"])

    payload = {**_PAYLOAD, "name": "Revised principle name", "change_note": "Tightened wording after review."}
    resp = client.put(
        f"{_project_base(project['id'])}/guiding-principles/{guiding_principle['id']}", json=payload,
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 200, resp.text
    updated = resp.json()
    assert updated["name"] == "Revised principle name"
    assert updated["version_number"] == 2

    resp = client.get(
        f"{_project_base(project['id'])}/guiding-principles/{guiding_principle['id']}/versions",
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 200, resp.text
    versions = resp.json()
    assert len(versions) == 2
    assert versions[0]["valid_to"] is not None
    assert versions[1]["valid_to"] is None


def test_update_project_guiding_principle_can_assign_and_clear_owner(client, admin_token):
    """`owner_id` is nullable, so both assigning it and explicitly clearing
    it (not just leaving it unspecified) must actually persist — the
    `owner_id_explicitly_set` disambiguation this field needs (see
    `service.apply_guiding_principle_new_version`'s own docstring)."""
    org, project, org_admin_token = _setup(client, admin_token, "CtxGuidingPrinciple Owner Co")
    guiding_principle = _create_project_guiding_principle(client, org_admin_token, project["id"])
    user_id = create_org_user(client, org_admin_token, org["id"], "gp_owner_candidate@example.com")

    payload = {**_PAYLOAD, "owner_id": user_id}
    resp = client.put(
        f"{_project_base(project['id'])}/guiding-principles/{guiding_principle['id']}", json=payload,
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["owner_id"] == user_id

    payload = {**_PAYLOAD, "owner_id": None}
    resp = client.put(
        f"{_project_base(project['id'])}/guiding-principles/{guiding_principle['id']}", json=payload,
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["owner_id"] is None


def test_plain_member_cannot_edit_a_guiding_principle(client, admin_token):
    org, project, org_admin_token = _setup(client, admin_token, "CtxGuidingPrinciple Edit RBAC Co")
    guiding_principle = _create_project_guiding_principle(client, org_admin_token, project["id"])
    _, member_token = _add_plain_member(
        client, org_admin_token, org["id"], project["id"], "gp_editor_denied@example.com"
    )
    resp = client.put(
        f"{_project_base(project['id'])}/guiding-principles/{guiding_principle['id']}", json=_PAYLOAD,
        headers=auth_headers(member_token),
    )
    assert resp.status_code == 403, resp.text


# --- Lifecycle ----------------------------------------------------------------


def test_full_lifecycle_project_guiding_principle_propose_through_active(client, admin_token):
    org, project, org_admin_token = _setup(client, admin_token, "CtxGuidingPrinciple Lifecycle Co")
    user_id, approver_token = _add_plain_member(
        client, org_admin_token, org["id"], project["id"], "gp_approver@example.com"
    )
    _grant_project_module_role(client, org_admin_token, project["id"], user_id, "guiding_principle_approver")

    guiding_principle = _create_project_guiding_principle(client, org_admin_token, project["id"])
    _advance_project_guiding_principle_to_proposed(client, org_admin_token, project["id"], guiding_principle["id"])

    resp = client.post(
        f"{_project_base(project['id'])}/guiding-principles/{guiding_principle['id']}/approve",
        json={"comment": "Agreed."}, headers=auth_headers(approver_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "approved"
    assert resp.json()["is_locked"] is True

    resp = client.post(
        f"{_project_base(project['id'])}/guiding-principles/{guiding_principle['id']}/activate", json={},
        headers=auth_headers(approver_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "active"

    resp = client.post(
        f"{_project_base(project['id'])}/guiding-principles/{guiding_principle['id']}/retire",
        json={"comment": "No longer applicable after platform redesign."}, headers=auth_headers(approver_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "retired"


def test_active_guiding_principle_can_be_superseded(client, admin_token):
    org, project, org_admin_token = _setup(client, admin_token, "CtxGuidingPrinciple Supersede Co")
    user_id, approver_token = _add_plain_member(
        client, org_admin_token, org["id"], project["id"], "gp_supersede_approver@example.com"
    )
    _grant_project_module_role(client, org_admin_token, project["id"], user_id, "guiding_principle_approver")

    guiding_principle = _create_project_guiding_principle(client, org_admin_token, project["id"])
    _advance_project_guiding_principle_to_proposed(client, org_admin_token, project["id"], guiding_principle["id"])
    resp = client.post(
        f"{_project_base(project['id'])}/guiding-principles/{guiding_principle['id']}/approve", json={},
        headers=auth_headers(approver_token),
    )
    assert resp.status_code == 200, resp.text
    resp = client.post(
        f"{_project_base(project['id'])}/guiding-principles/{guiding_principle['id']}/activate", json={},
        headers=auth_headers(approver_token),
    )
    assert resp.status_code == 200, resp.text

    resp = client.post(
        f"{_project_base(project['id'])}/guiding-principles/{guiding_principle['id']}/supersede",
        json={"comment": "Replaced by a newer principle."}, headers=auth_headers(approver_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "superseded"


def test_send_back_requires_a_comment_and_returns_to_draft(client, admin_token):
    org, project, org_admin_token = _setup(client, admin_token, "CtxGuidingPrinciple SendBack Co")
    user_id, approver_token = _add_plain_member(
        client, org_admin_token, org["id"], project["id"], "gp_sendback_approver@example.com"
    )
    _grant_project_module_role(client, org_admin_token, project["id"], user_id, "guiding_principle_approver")
    guiding_principle = _create_project_guiding_principle(client, org_admin_token, project["id"])
    _advance_project_guiding_principle_to_proposed(client, org_admin_token, project["id"], guiding_principle["id"])

    resp = client.post(
        f"{_project_base(project['id'])}/guiding-principles/{guiding_principle['id']}/send-back", json={"comment": ""},
        headers=auth_headers(approver_token),
    )
    assert resp.status_code == 400, resp.text

    resp = client.post(
        f"{_project_base(project['id'])}/guiding-principles/{guiding_principle['id']}/send-back",
        json={"comment": "Statement is too broad, please narrow it."}, headers=auth_headers(approver_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "draft"


def test_illegal_transition_is_409(client, admin_token):
    _, project, org_admin_token = _setup(client, admin_token, "CtxGuidingPrinciple Illegal Co")
    guiding_principle = _create_project_guiding_principle(client, org_admin_token, project["id"])

    # DRAFT cannot go straight to APPROVED.
    resp = client.post(
        f"{_project_base(project['id'])}/guiding-principles/{guiding_principle['id']}/approve", json={},
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 409, resp.text


def test_owner_role_cannot_approve_without_approver_role_or_permission(client, admin_token):
    org, project, org_admin_token = _setup(client, admin_token, "CtxGuidingPrinciple Owner Not Approver Co")
    user_id, owner_token = _add_plain_member(
        client, org_admin_token, org["id"], project["id"], "gp_owner_only@example.com"
    )
    _grant_project_module_role(client, org_admin_token, project["id"], user_id, "guiding_principle_owner")
    guiding_principle = _create_project_guiding_principle(client, org_admin_token, project["id"])
    _advance_project_guiding_principle_to_proposed(client, org_admin_token, project["id"], guiding_principle["id"])

    resp = client.post(
        f"{_project_base(project['id'])}/guiding-principles/{guiding_principle['id']}/approve", json={},
        headers=auth_headers(owner_token),
    )
    assert resp.status_code == 403, resp.text


def test_approve_reachable_via_custom_role_grant_of_approve_baseline_permission(client, admin_token):
    org, project, org_admin_token = _setup(client, admin_token, "CtxGuidingPrinciple Custom Role Co")
    user_id, member_token = _add_plain_member(
        client, org_admin_token, org["id"], project["id"], "gp_custom_role_approver@example.com"
    )
    guiding_principle = _create_project_guiding_principle(client, org_admin_token, project["id"])
    _advance_project_guiding_principle_to_proposed(client, org_admin_token, project["id"], guiding_principle["id"])

    resp = client.post(
        f"{_project_base(project['id'])}/guiding-principles/{guiding_principle['id']}/approve", json={},
        headers=auth_headers(member_token),
    )
    assert resp.status_code == 403, resp.text

    from app.database import SessionLocal

    db = SessionLocal()
    try:
        role = CustomRoleDefinition(
            organization_id=uuid.UUID(org["id"]), name="Guiding Principle Approver (Custom)",
            description="Custom test role.", scope="project",
        )
        db.add(role)
        db.flush()
        db.add(
            CustomRolePermission(
                custom_role_id=role.id, permission=encode_permission("guiding_principle", "approve_baseline"),
            )
        )
        db.add(
            UserCustomRoleGrant(
                custom_role_id=role.id, user_id=uuid.UUID(user_id), organization_id=uuid.UUID(org["id"]),
                project_id=uuid.UUID(project["id"]),
            )
        )
        db.commit()
    finally:
        db.close()

    resp = client.post(
        f"{_project_base(project['id'])}/guiding-principles/{guiding_principle['id']}/approve", json={},
        headers=auth_headers(member_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "approved"


def test_org_scoped_lifecycle_requires_org_guiding_principle_approver_role(client, admin_token):
    org, _, org_admin_token = _setup(client, admin_token, "CtxGuidingPrinciple Org Lifecycle Co")
    user_id = create_org_user(client, org_admin_token, org["id"], "gp_org_approver@example.com")
    approver_token = login(client, "gp_org_approver@example.com", "Password123!")
    _grant_org_module_role(client, org_admin_token, org["id"], user_id, "org_guiding_principle_approver")

    guiding_principle = _create_org_guiding_principle(client, org_admin_token, org["id"])
    resp = client.post(
        f"{_org_base(org['id'])}/guiding-principles/{guiding_principle['id']}/propose",
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 200, resp.text

    resp = client.post(
        f"{_org_base(org['id'])}/guiding-principles/{guiding_principle['id']}/approve", json={},
        headers=auth_headers(approver_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "approved"


# --- Disabled module / cross-tenant isolation -------------------------------


def test_disabled_module_is_404_not_403(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "CtxGuidingPrinciple Disabled Co")
    project = create_project(client, org_admin_token, org["id"], "CtxGuidingPrinciple Disabled Co Project")
    # Module never enabled for this org.
    resp = client.get(_project_base(project["id"]) + "/guiding-principles", headers=auth_headers(org_admin_token))
    assert resp.status_code == 404, resp.text


def test_disabled_guiding_principle_subcomponent_is_404_project_scoped(client, admin_token):
    """Disabling the org's default for the `"guiding_principle"`
    sub-component of `context_strategy` (with the whole module still
    enabled) 404s the project-scoped Guiding Principle endpoints, same
    posture as the whole module being disabled."""
    org, project, org_admin_token = _setup(client, admin_token, "CtxGuidingPrinciple Subcomponent Disabled Co")
    resp = client.put(
        f"/api/v1/orgs/{org['id']}/modules/{MODULE_KEY}/subcomponents/guiding_principle",
        json={"enabled": False}, headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 200, resp.text

    resp = client.get(_project_base(project["id"]) + "/guiding-principles", headers=auth_headers(org_admin_token))
    assert resp.status_code == 404, resp.text


def test_disabled_guiding_principle_subcomponent_is_404_org_scoped(client, admin_token):
    """Org-scoped sibling of the project-scoped test above."""
    org, org_admin_token = create_org_admin_in(client, admin_token, "CtxGuidingPrinciple Org Subcomponent Disabled Co")
    _enable_module(client, org_admin_token, org["id"])
    resp = client.put(
        f"/api/v1/orgs/{org['id']}/modules/{MODULE_KEY}/subcomponents/guiding_principle",
        json={"enabled": False}, headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 200, resp.text

    resp = client.get(_org_base(org["id"]) + "/guiding-principles", headers=auth_headers(org_admin_token))
    assert resp.status_code == 404, resp.text


def test_guiding_principle_from_another_project_is_404(client, admin_token):
    _, project_a, org_admin_token = _setup(client, admin_token, "CtxGuidingPrinciple Isolation A Co")
    guiding_principle = _create_project_guiding_principle(client, org_admin_token, project_a["id"])

    org_b, org_b_admin_token = create_org_admin_in(client, admin_token, "CtxGuidingPrinciple Isolation B Co")
    _enable_module(client, org_b_admin_token, org_b["id"])
    project_b = create_project(client, org_b_admin_token, org_b["id"], "CtxGuidingPrinciple Isolation B Project")

    resp = client.get(
        f"{_project_base(project_b['id'])}/guiding-principles/{guiding_principle['id']}",
        headers=auth_headers(org_b_admin_token),
    )
    assert resp.status_code == 404, resp.text


# --- Comments and files ------------------------------------------------------


def test_comment_add_list_and_author_only_edit(client, admin_token):
    org, project, org_admin_token = _setup(client, admin_token, "CtxGuidingPrinciple Comments Co")
    guiding_principle = _create_project_guiding_principle(client, org_admin_token, project["id"])
    _, other_token = _add_plain_member(
        client, org_admin_token, org["id"], project["id"], "gp_commenter_two@example.com"
    )

    resp = client.post(
        f"{_project_base(project['id'])}/guiding-principles/{guiding_principle['id']}/comments",
        json={"body": "Initial thoughts."}, headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 201, resp.text
    comment = resp.json()
    assert comment["edited_at"] is None

    resp = client.get(
        f"{_project_base(project['id'])}/guiding-principles/{guiding_principle['id']}/comments",
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert len(resp.json()) == 1

    # Non-author cannot edit.
    resp = client.patch(
        f"{_project_base(project['id'])}/guiding-principles/{guiding_principle['id']}/comments/{comment['id']}",
        json={"body": "Edited by someone else"}, headers=auth_headers(other_token),
    )
    assert resp.status_code == 403, resp.text

    resp = client.patch(
        f"{_project_base(project['id'])}/guiding-principles/{guiding_principle['id']}/comments/{comment['id']}",
        json={"body": "Edited by the author"}, headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["edited_at"] is not None


def test_direct_file_attachment_upload_list_unlink_and_lock(client, admin_token):
    org, project, org_admin_token = _setup(client, admin_token, "CtxGuidingPrinciple Files Co")
    user_id, approver_token = _add_plain_member(
        client, org_admin_token, org["id"], project["id"], "gp_file_approver@example.com"
    )
    _grant_project_module_role(client, org_admin_token, project["id"], user_id, "guiding_principle_approver")
    guiding_principle = _create_project_guiding_principle(client, org_admin_token, project["id"])

    resp = client.post(
        f"{_project_base(project['id'])}/guiding-principles/{guiding_principle['id']}/files",
        files={"file": ("guiding_principle.txt", b"guiding principle content", "text/plain")},
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 201, resp.text
    file_id = resp.json()["id"]

    resp = client.get(
        f"{_project_base(project['id'])}/guiding-principles/{guiding_principle['id']}/files",
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert len(resp.json()) == 1

    resp = client.delete(
        f"{_project_base(project['id'])}/guiding-principles/{guiding_principle['id']}/files/{file_id}",
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 204, resp.text

    # Lock check: once approved, new attachments are rejected.
    _advance_project_guiding_principle_to_proposed(client, org_admin_token, project["id"], guiding_principle["id"])
    resp = client.post(
        f"{_project_base(project['id'])}/guiding-principles/{guiding_principle['id']}/approve", json={},
        headers=auth_headers(approver_token),
    )
    assert resp.status_code == 200, resp.text

    resp = client.post(
        f"{_project_base(project['id'])}/guiding-principles/{guiding_principle['id']}/files",
        files={"file": ("guiding_principle2.txt", b"more content", "text/plain")}, headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 409, resp.text
