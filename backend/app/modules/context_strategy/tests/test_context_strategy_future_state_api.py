"""Tests for Context & Strategy's Phase 2 backend API
(docs/plans/module-01-context-and-strategy-plan.md Phase 2 — Future
State) — the real HTTP endpoints (`router.py`/`project_router.py`),
through the `client` fixture, mirroring `test_context_strategy_api.py`'s
own "go through the real API" convention for Strategy. Kept as its own
sibling file rather than folded into that one (Decided by: Agent) — this
module now covers two artefact types, and Future State's own test suite is
already the same size Strategy's was on its own, so one file per artefact
type reads more cleanly than a single ever-growing combined file, while
both files share the same `tests/` package and API-helper conventions.

Covers, for both the org-scoped and project-scoped routers: Future State
CRUD, the content lock once past `UNDER_REVIEW` (409), the full lifecycle
(propose/submit-for-review/send-back/approve/activate/supersede/retire,
including the mandatory-comment-on-send-back rule and an illegal-
transition 409), version history, the RBAC composition (`..._owner`/
`..._approver`/creator-or-role for propose, disabled-module-is-404-not-403,
and a Fine-Grained Access Control custom-role permission grant satisfying
the approve gate), comments/comment-files, direct file attachments, and
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
    "title": "Populated-corridor inspection contracts, certified and won",
    "current_state": "Single-controller platform flying test routes over unpopulated terrain only.",
    "desired_state": "Dual-redundant platform certified and contracted for populated-corridor routes.",
    "target_date": "2027-06-30",
    "outcomes": "Signed populated-corridor inspection contract within the next fiscal year.",
    "success_measures": "Certification sign-off date; contract value signed.",
    "constraints": "Airframe payload budget limits redundancy to dual, not triple, modular redundancy.",
    "assumptions": "Regulatory approval timelines do not materially worsen from current guidance.",
}


def _create_org_future_state(client, token, org_id, **extra) -> dict:
    resp = client.post(_org_base(org_id) + "/future-states", json={**_PAYLOAD, **extra}, headers=auth_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_project_future_state(client, token, project_id, **extra) -> dict:
    resp = client.post(
        _project_base(project_id) + "/future-states", json={**_PAYLOAD, **extra}, headers=auth_headers(token)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _advance_project_future_state_to_under_review(client, token, project_id, future_state_id) -> dict:
    resp = client.post(
        f"{_project_base(project_id)}/future-states/{future_state_id}/propose", headers=auth_headers(token)
    )
    assert resp.status_code == 200, resp.text
    resp = client.post(
        f"{_project_base(project_id)}/future-states/{future_state_id}/submit-for-review", headers=auth_headers(token)
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# --- Create / list / get / update -------------------------------------------


def test_create_and_get_project_future_state(client, admin_token):
    _, project, org_admin_token = _setup(client, admin_token, "CtxFutureState Create Co")
    future_state = _create_project_future_state(client, org_admin_token, project["id"])

    assert future_state["scope"] == "project"
    assert future_state["project_id"] == project["id"]
    assert future_state["organization_id"] is None
    assert future_state["status"] == "draft"
    assert future_state["version_number"] == 1
    assert future_state["is_locked"] is False
    assert future_state["target_date"] == "2027-06-30"

    resp = client.get(
        f"{_project_base(project['id'])}/future-states/{future_state['id']}", headers=auth_headers(org_admin_token)
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == future_state["id"]


def test_create_and_get_org_future_state(client, admin_token):
    org, _, org_admin_token = _setup(client, admin_token, "CtxFutureState Org Create Co")
    future_state = _create_org_future_state(client, org_admin_token, org["id"])

    assert future_state["scope"] == "organization"
    assert future_state["organization_id"] == org["id"]
    assert future_state["project_id"] is None
    assert future_state["status"] == "draft"


def test_any_project_member_may_create_a_future_state_no_owner_role_required(client, admin_token):
    org, project, org_admin_token = _setup(client, admin_token, "CtxFutureState Any Member Co")
    _, member_token = _add_plain_member(
        client, org_admin_token, org["id"], project["id"], "plain_member_fs@example.com"
    )
    resp = client.post(
        _project_base(project["id"]) + "/future-states", json=_PAYLOAD, headers=auth_headers(member_token)
    )
    assert resp.status_code == 201, resp.text


def test_update_project_future_state_creates_a_new_version(client, admin_token):
    _, project, org_admin_token = _setup(client, admin_token, "CtxFutureState Update Co")
    future_state = _create_project_future_state(client, org_admin_token, project["id"])

    payload = {**_PAYLOAD, "title": "Revised future state", "change_note": "Refined after stakeholder feedback."}
    resp = client.put(
        f"{_project_base(project['id'])}/future-states/{future_state['id']}", json=payload,
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 200, resp.text
    updated = resp.json()
    assert updated["title"] == "Revised future state"
    assert updated["version_number"] == 2

    resp = client.get(
        f"{_project_base(project['id'])}/future-states/{future_state['id']}/versions",
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 200, resp.text
    versions = resp.json()
    assert len(versions) == 2
    assert versions[0]["valid_to"] is not None
    assert versions[1]["valid_to"] is None


def test_update_project_future_state_can_clear_target_date(client, admin_token):
    """`target_date` is nullable, so explicitly clearing it (not just
    leaving it unspecified) must actually persist as `None` — the
    `target_date_explicitly_set` disambiguation this field alone needs
    (see `service.apply_future_state_new_version`'s own docstring)."""
    _, project, org_admin_token = _setup(client, admin_token, "CtxFutureState Clear Date Co")
    future_state = _create_project_future_state(client, org_admin_token, project["id"])

    payload = {**_PAYLOAD, "target_date": None}
    resp = client.put(
        f"{_project_base(project['id'])}/future-states/{future_state['id']}", json=payload,
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["target_date"] is None


def test_plain_member_cannot_edit_a_future_state(client, admin_token):
    org, project, org_admin_token = _setup(client, admin_token, "CtxFutureState Edit RBAC Co")
    future_state = _create_project_future_state(client, org_admin_token, project["id"])
    _, member_token = _add_plain_member(
        client, org_admin_token, org["id"], project["id"], "fs_editor_denied@example.com"
    )
    resp = client.put(
        f"{_project_base(project['id'])}/future-states/{future_state['id']}", json=_PAYLOAD,
        headers=auth_headers(member_token),
    )
    assert resp.status_code == 403, resp.text


# --- Lifecycle ---------------------------------------------------------------


def test_full_lifecycle_project_future_state_propose_through_active(client, admin_token):
    org, project, org_admin_token = _setup(client, admin_token, "CtxFutureState Lifecycle Co")
    user_id, approver_token = _add_plain_member(
        client, org_admin_token, org["id"], project["id"], "fs_approver@example.com"
    )
    _grant_project_module_role(client, org_admin_token, project["id"], user_id, "future_state_approver")

    future_state = _create_project_future_state(client, org_admin_token, project["id"])
    _advance_project_future_state_to_under_review(client, org_admin_token, project["id"], future_state["id"])

    resp = client.post(
        f"{_project_base(project['id'])}/future-states/{future_state['id']}/approve", json={"comment": "Looks good."},
        headers=auth_headers(approver_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "approved"
    assert resp.json()["is_locked"] is True

    resp = client.post(
        f"{_project_base(project['id'])}/future-states/{future_state['id']}/activate", json={},
        headers=auth_headers(approver_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "active"

    resp = client.post(
        f"{_project_base(project['id'])}/future-states/{future_state['id']}/retire",
        json={"comment": "Superseded by a new plan."}, headers=auth_headers(approver_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "retired"


def test_send_back_requires_a_comment_and_returns_to_draft(client, admin_token):
    org, project, org_admin_token = _setup(client, admin_token, "CtxFutureState SendBack Co")
    user_id, approver_token = _add_plain_member(
        client, org_admin_token, org["id"], project["id"], "fs_sendback_approver@example.com"
    )
    _grant_project_module_role(client, org_admin_token, project["id"], user_id, "future_state_approver")
    future_state = _create_project_future_state(client, org_admin_token, project["id"])
    _advance_project_future_state_to_under_review(client, org_admin_token, project["id"], future_state["id"])

    resp = client.post(
        f"{_project_base(project['id'])}/future-states/{future_state['id']}/send-back", json={"comment": ""},
        headers=auth_headers(approver_token),
    )
    assert resp.status_code == 400, resp.text

    resp = client.post(
        f"{_project_base(project['id'])}/future-states/{future_state['id']}/send-back",
        json={"comment": "Needs a firmer target date."}, headers=auth_headers(approver_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "draft"


def test_illegal_transition_is_409(client, admin_token):
    _, project, org_admin_token = _setup(client, admin_token, "CtxFutureState Illegal Co")
    future_state = _create_project_future_state(client, org_admin_token, project["id"])

    # DRAFT cannot go straight to APPROVED.
    resp = client.post(
        f"{_project_base(project['id'])}/future-states/{future_state['id']}/approve", json={},
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 409, resp.text


def test_owner_role_cannot_approve_without_approver_role_or_permission(client, admin_token):
    org, project, org_admin_token = _setup(client, admin_token, "CtxFutureState Owner Not Approver Co")
    user_id, owner_token = _add_plain_member(
        client, org_admin_token, org["id"], project["id"], "fs_owner_only@example.com"
    )
    _grant_project_module_role(client, org_admin_token, project["id"], user_id, "future_state_owner")
    future_state = _create_project_future_state(client, org_admin_token, project["id"])
    _advance_project_future_state_to_under_review(client, org_admin_token, project["id"], future_state["id"])

    resp = client.post(
        f"{_project_base(project['id'])}/future-states/{future_state['id']}/approve", json={},
        headers=auth_headers(owner_token),
    )
    assert resp.status_code == 403, resp.text


def test_approve_reachable_via_custom_role_grant_of_approve_baseline_permission(client, admin_token):
    org, project, org_admin_token = _setup(client, admin_token, "CtxFutureState Custom Role Co")
    user_id, member_token = _add_plain_member(
        client, org_admin_token, org["id"], project["id"], "fs_custom_role_approver@example.com"
    )
    future_state = _create_project_future_state(client, org_admin_token, project["id"])
    _advance_project_future_state_to_under_review(client, org_admin_token, project["id"], future_state["id"])

    resp = client.post(
        f"{_project_base(project['id'])}/future-states/{future_state['id']}/approve", json={},
        headers=auth_headers(member_token),
    )
    assert resp.status_code == 403, resp.text

    from app.database import SessionLocal

    db = SessionLocal()
    try:
        role = CustomRoleDefinition(
            organization_id=uuid.UUID(org["id"]), name="Future State Approver (Custom)",
            description="Custom test role.", scope="project",
        )
        db.add(role)
        db.flush()
        db.add(
            CustomRolePermission(
                custom_role_id=role.id, permission=encode_permission("future_state", "approve_baseline"),
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
        f"{_project_base(project['id'])}/future-states/{future_state['id']}/approve", json={},
        headers=auth_headers(member_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "approved"


def test_org_scoped_lifecycle_requires_org_future_state_approver_role(client, admin_token):
    org, _, org_admin_token = _setup(client, admin_token, "CtxFutureState Org Lifecycle Co")
    user_id = create_org_user(client, org_admin_token, org["id"], "fs_org_approver@example.com")
    approver_token = login(client, "fs_org_approver@example.com", "Password123!")
    _grant_org_module_role(client, org_admin_token, org["id"], user_id, "org_future_state_approver")

    future_state = _create_org_future_state(client, org_admin_token, org["id"])
    resp = client.post(
        f"{_org_base(org['id'])}/future-states/{future_state['id']}/propose", headers=auth_headers(org_admin_token)
    )
    assert resp.status_code == 200, resp.text
    resp = client.post(
        f"{_org_base(org['id'])}/future-states/{future_state['id']}/submit-for-review",
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 200, resp.text

    resp = client.post(
        f"{_org_base(org['id'])}/future-states/{future_state['id']}/approve", json={},
        headers=auth_headers(approver_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "approved"


# --- Disabled module / cross-tenant isolation -------------------------------


def test_disabled_module_is_404_not_403(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "CtxFutureState Disabled Co")
    project = create_project(client, org_admin_token, org["id"], "CtxFutureState Disabled Co Project")
    # Module never enabled for this org.
    resp = client.get(_project_base(project["id"]) + "/future-states", headers=auth_headers(org_admin_token))
    assert resp.status_code == 404, resp.text


def test_disabled_future_state_subcomponent_is_404_project_scoped(client, admin_token):
    """Disabling the org's default for the `"future_state"` sub-component of
    `context_strategy` (with the whole module still enabled) 404s the
    project-scoped Future State endpoints, same posture as the whole
    module being disabled — Future State's own real end-to-end consumer of
    Module 0 Phase 4's sub-component enablement, alongside Strategy's."""
    org, project, org_admin_token = _setup(client, admin_token, "CtxFutureState Subcomponent Disabled Co")
    resp = client.put(
        f"/api/v1/orgs/{org['id']}/modules/{MODULE_KEY}/subcomponents/future_state",
        json={"enabled": False}, headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 200, resp.text

    resp = client.get(_project_base(project["id"]) + "/future-states", headers=auth_headers(org_admin_token))
    assert resp.status_code == 404, resp.text


def test_disabled_future_state_subcomponent_is_404_org_scoped(client, admin_token):
    """Org-scoped sibling of the project-scoped test above."""
    org, org_admin_token = create_org_admin_in(client, admin_token, "CtxFutureState Org Subcomponent Disabled Co")
    _enable_module(client, org_admin_token, org["id"])
    resp = client.put(
        f"/api/v1/orgs/{org['id']}/modules/{MODULE_KEY}/subcomponents/future_state",
        json={"enabled": False}, headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 200, resp.text

    resp = client.get(_org_base(org["id"]) + "/future-states", headers=auth_headers(org_admin_token))
    assert resp.status_code == 404, resp.text


def test_future_state_from_another_project_is_404(client, admin_token):
    _, project_a, org_admin_token = _setup(client, admin_token, "CtxFutureState Isolation A Co")
    future_state = _create_project_future_state(client, org_admin_token, project_a["id"])

    org_b, org_b_admin_token = create_org_admin_in(client, admin_token, "CtxFutureState Isolation B Co")
    _enable_module(client, org_b_admin_token, org_b["id"])
    project_b = create_project(client, org_b_admin_token, org_b["id"], "CtxFutureState Isolation B Project")

    resp = client.get(
        f"{_project_base(project_b['id'])}/future-states/{future_state['id']}", headers=auth_headers(org_b_admin_token)
    )
    assert resp.status_code == 404, resp.text


# --- Comments and files ------------------------------------------------------


def test_comment_add_list_and_author_only_edit(client, admin_token):
    org, project, org_admin_token = _setup(client, admin_token, "CtxFutureState Comments Co")
    future_state = _create_project_future_state(client, org_admin_token, project["id"])
    _, other_token = _add_plain_member(
        client, org_admin_token, org["id"], project["id"], "fs_commenter_two@example.com"
    )

    resp = client.post(
        f"{_project_base(project['id'])}/future-states/{future_state['id']}/comments",
        json={"body": "Initial thoughts."}, headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 201, resp.text
    comment = resp.json()
    assert comment["edited_at"] is None

    resp = client.get(
        f"{_project_base(project['id'])}/future-states/{future_state['id']}/comments",
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert len(resp.json()) == 1

    # Non-author cannot edit.
    resp = client.patch(
        f"{_project_base(project['id'])}/future-states/{future_state['id']}/comments/{comment['id']}",
        json={"body": "Edited by someone else"}, headers=auth_headers(other_token),
    )
    assert resp.status_code == 403, resp.text

    resp = client.patch(
        f"{_project_base(project['id'])}/future-states/{future_state['id']}/comments/{comment['id']}",
        json={"body": "Edited by the author"}, headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["edited_at"] is not None


def test_direct_file_attachment_upload_list_unlink_and_lock(client, admin_token):
    org, project, org_admin_token = _setup(client, admin_token, "CtxFutureState Files Co")
    user_id, approver_token = _add_plain_member(
        client, org_admin_token, org["id"], project["id"], "fs_file_approver@example.com"
    )
    _grant_project_module_role(client, org_admin_token, project["id"], user_id, "future_state_approver")
    future_state = _create_project_future_state(client, org_admin_token, project["id"])

    resp = client.post(
        f"{_project_base(project['id'])}/future-states/{future_state['id']}/files",
        files={"file": ("future_state.txt", b"future state content", "text/plain")},
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 201, resp.text
    file_id = resp.json()["id"]

    resp = client.get(
        f"{_project_base(project['id'])}/future-states/{future_state['id']}/files",
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert len(resp.json()) == 1

    resp = client.delete(
        f"{_project_base(project['id'])}/future-states/{future_state['id']}/files/{file_id}",
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 204, resp.text

    # Lock check: once approved, new attachments are rejected.
    _advance_project_future_state_to_under_review(client, org_admin_token, project["id"], future_state["id"])
    resp = client.post(
        f"{_project_base(project['id'])}/future-states/{future_state['id']}/approve", json={},
        headers=auth_headers(approver_token),
    )
    assert resp.status_code == 200, resp.text

    resp = client.post(
        f"{_project_base(project['id'])}/future-states/{future_state['id']}/files",
        files={"file": ("future_state2.txt", b"more content", "text/plain")}, headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 409, resp.text
