"""Tests for Context & Strategy's Phase 1 backend API
(docs/plans/module-01-context-and-strategy-plan.md Phase 1 — Organisation
& Project Strategy) — the real HTTP endpoints (`router.py`/
`project_router.py`), through the `client` fixture, mirroring
`modules.decisions.tests.test_decisions_api`'s own "go through the real
API" convention.

Covers, for both the org-scoped and project-scoped routers: Strategy
CRUD, the content lock once past `UNDER_REVIEW` (409), the full lifecycle
(propose/submit-for-review/send-back/approve/activate/supersede/retire,
including the mandatory-comment-on-send-back rule and an illegal-
transition 409), version history, the RBAC composition (`..._owner`/
`..._approver`/creator-or-role for propose, disabled-module-is-404-not-403
vs. wrong-role-is-403, and a Fine-Grained Access Control custom-role
permission grant satisfying the approve gate), comments/comment-files,
direct file attachments, and cross-tenant 404s.
"""

from __future__ import annotations

import uuid

from app.models.custom_role import CustomRoleDefinition, CustomRolePermission, UserCustomRoleGrant
from app.modules.registry import ModuleNavEntry, get_frontend_manifest
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
    "title": "Become the market leader in requirements traceability",
    "objective": "Grow market share through a best-in-class traceability offering.",
    "current_state": "Third in market share.",
    "desired_future_state": "First in market share within three years.",
    "rationale": "Traceability is our strongest differentiator.",
    "expected_outcomes": "Increased win rate on competitive deals.",
    "constraints": "Limited engineering headcount.",
    "measures_of_success": "Win-rate percentage, NPS.",
    "priority": "high",
    "time_horizon": "long_term",
}


def _create_org_strategy(client, token, org_id, **extra) -> dict:
    resp = client.post(_org_base(org_id) + "/strategies", json={**_PAYLOAD, **extra}, headers=auth_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_project_strategy(client, token, project_id, **extra) -> dict:
    resp = client.post(
        _project_base(project_id) + "/strategies", json={**_PAYLOAD, **extra}, headers=auth_headers(token)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _advance_project_strategy_to_under_review(client, token, project_id, strategy_id) -> dict:
    resp = client.post(f"{_project_base(project_id)}/strategies/{strategy_id}/propose", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    resp = client.post(
        f"{_project_base(project_id)}/strategies/{strategy_id}/submit-for-review", headers=auth_headers(token)
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# --- Create / list / get / update -------------------------------------------


def test_create_and_get_project_strategy(client, admin_token):
    _, project, org_admin_token = _setup(client, admin_token, "CtxStrategy Create Co")
    strategy = _create_project_strategy(client, org_admin_token, project["id"])

    assert strategy["scope"] == "project"
    assert strategy["project_id"] == project["id"]
    assert strategy["organization_id"] is None
    assert strategy["status"] == "draft"
    assert strategy["version_number"] == 1
    assert strategy["is_locked"] is False
    assert strategy["priority"] == "high"
    assert strategy["time_horizon"] == "long_term"

    resp = client.get(
        f"{_project_base(project['id'])}/strategies/{strategy['id']}", headers=auth_headers(org_admin_token)
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == strategy["id"]


def test_create_and_get_org_strategy(client, admin_token):
    org, _, org_admin_token = _setup(client, admin_token, "CtxStrategy Org Create Co")
    strategy = _create_org_strategy(client, org_admin_token, org["id"])

    assert strategy["scope"] == "organization"
    assert strategy["organization_id"] == org["id"]
    assert strategy["project_id"] is None
    assert strategy["status"] == "draft"


def test_any_project_member_may_create_a_strategy_no_owner_role_required(client, admin_token):
    org, project, org_admin_token = _setup(client, admin_token, "CtxStrategy Any Member Co")
    _, member_token = _add_plain_member(
        client, org_admin_token, org["id"], project["id"], "plain_member@example.com"
    )
    resp = client.post(
        _project_base(project["id"]) + "/strategies", json=_PAYLOAD, headers=auth_headers(member_token)
    )
    assert resp.status_code == 201, resp.text


def test_update_project_strategy_creates_a_new_version(client, admin_token):
    _, project, org_admin_token = _setup(client, admin_token, "CtxStrategy Update Co")
    strategy = _create_project_strategy(client, org_admin_token, project["id"])

    payload = {**_PAYLOAD, "title": "Revised objective", "change_note": "Refined after stakeholder feedback."}
    resp = client.put(
        f"{_project_base(project['id'])}/strategies/{strategy['id']}", json=payload,
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 200, resp.text
    updated = resp.json()
    assert updated["title"] == "Revised objective"
    assert updated["version_number"] == 2

    resp = client.get(
        f"{_project_base(project['id'])}/strategies/{strategy['id']}/versions", headers=auth_headers(org_admin_token)
    )
    assert resp.status_code == 200, resp.text
    versions = resp.json()
    assert len(versions) == 2
    assert versions[0]["valid_to"] is not None
    assert versions[1]["valid_to"] is None


def test_plain_member_cannot_edit_a_strategy(client, admin_token):
    org, project, org_admin_token = _setup(client, admin_token, "CtxStrategy Edit RBAC Co")
    strategy = _create_project_strategy(client, org_admin_token, project["id"])
    _, member_token = _add_plain_member(
        client, org_admin_token, org["id"], project["id"], "editor_denied@example.com"
    )
    resp = client.put(
        f"{_project_base(project['id'])}/strategies/{strategy['id']}", json=_PAYLOAD,
        headers=auth_headers(member_token),
    )
    assert resp.status_code == 403, resp.text


# --- Lifecycle ---------------------------------------------------------------


def test_full_lifecycle_project_strategy_propose_through_active(client, admin_token):
    org, project, org_admin_token = _setup(client, admin_token, "CtxStrategy Lifecycle Co")
    user_id, approver_token = _add_plain_member(
        client, org_admin_token, org["id"], project["id"], "strategy_approver@example.com"
    )
    _grant_project_module_role(client, org_admin_token, project["id"], user_id, "strategy_approver")

    strategy = _create_project_strategy(client, org_admin_token, project["id"])
    _advance_project_strategy_to_under_review(client, org_admin_token, project["id"], strategy["id"])

    resp = client.post(
        f"{_project_base(project['id'])}/strategies/{strategy['id']}/approve", json={"comment": "Looks good."},
        headers=auth_headers(approver_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "approved"
    assert resp.json()["is_locked"] is True

    resp = client.post(
        f"{_project_base(project['id'])}/strategies/{strategy['id']}/activate", json={},
        headers=auth_headers(approver_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "active"

    resp = client.post(
        f"{_project_base(project['id'])}/strategies/{strategy['id']}/retire", json={"comment": "Superseded by a new plan."},
        headers=auth_headers(approver_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "retired"


def test_send_back_requires_a_comment_and_returns_to_draft(client, admin_token):
    org, project, org_admin_token = _setup(client, admin_token, "CtxStrategy SendBack Co")
    user_id, approver_token = _add_plain_member(
        client, org_admin_token, org["id"], project["id"], "sendback_approver@example.com"
    )
    _grant_project_module_role(client, org_admin_token, project["id"], user_id, "strategy_approver")
    strategy = _create_project_strategy(client, org_admin_token, project["id"])
    _advance_project_strategy_to_under_review(client, org_admin_token, project["id"], strategy["id"])

    resp = client.post(
        f"{_project_base(project['id'])}/strategies/{strategy['id']}/send-back", json={"comment": ""},
        headers=auth_headers(approver_token),
    )
    assert resp.status_code == 400, resp.text

    resp = client.post(
        f"{_project_base(project['id'])}/strategies/{strategy['id']}/send-back",
        json={"comment": "Needs more detail on measures of success."}, headers=auth_headers(approver_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "draft"


def test_illegal_transition_is_409(client, admin_token):
    _, project, org_admin_token = _setup(client, admin_token, "CtxStrategy Illegal Co")
    strategy = _create_project_strategy(client, org_admin_token, project["id"])

    # DRAFT cannot go straight to APPROVED.
    resp = client.post(
        f"{_project_base(project['id'])}/strategies/{strategy['id']}/approve", json={},
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 409, resp.text


def test_owner_role_cannot_approve_without_approver_role_or_permission(client, admin_token):
    org, project, org_admin_token = _setup(client, admin_token, "CtxStrategy Owner Not Approver Co")
    user_id, owner_token = _add_plain_member(
        client, org_admin_token, org["id"], project["id"], "strategy_owner_only@example.com"
    )
    _grant_project_module_role(client, org_admin_token, project["id"], user_id, "strategy_owner")
    strategy = _create_project_strategy(client, org_admin_token, project["id"])
    _advance_project_strategy_to_under_review(client, org_admin_token, project["id"], strategy["id"])

    resp = client.post(
        f"{_project_base(project['id'])}/strategies/{strategy['id']}/approve", json={},
        headers=auth_headers(owner_token),
    )
    assert resp.status_code == 403, resp.text


def test_approve_reachable_via_custom_role_grant_of_approve_baseline_permission(client, admin_token):
    org, project, org_admin_token = _setup(client, admin_token, "CtxStrategy Custom Role Co")
    user_id, member_token = _add_plain_member(
        client, org_admin_token, org["id"], project["id"], "custom_role_approver@example.com"
    )
    strategy = _create_project_strategy(client, org_admin_token, project["id"])
    _advance_project_strategy_to_under_review(client, org_admin_token, project["id"], strategy["id"])

    resp = client.post(
        f"{_project_base(project['id'])}/strategies/{strategy['id']}/approve", json={},
        headers=auth_headers(member_token),
    )
    assert resp.status_code == 403, resp.text

    from app.database import SessionLocal

    db = SessionLocal()
    try:
        role = CustomRoleDefinition(
            organization_id=uuid.UUID(org["id"]), name="Strategy Approver (Custom)", description="Custom test role.",
            scope="project",
        )
        db.add(role)
        db.flush()
        db.add(
            CustomRolePermission(
                custom_role_id=role.id, permission=encode_permission("strategy", "approve_baseline"),
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
        f"{_project_base(project['id'])}/strategies/{strategy['id']}/approve", json={},
        headers=auth_headers(member_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "approved"


def test_org_scoped_lifecycle_requires_org_strategy_approver_role(client, admin_token):
    org, _, org_admin_token = _setup(client, admin_token, "CtxStrategy Org Lifecycle Co")
    user_id = create_org_user(client, org_admin_token, org["id"], "org_approver@example.com")
    approver_token = login(client, "org_approver@example.com", "Password123!")
    _grant_org_module_role(client, org_admin_token, org["id"], user_id, "org_strategy_approver")

    strategy = _create_org_strategy(client, org_admin_token, org["id"])
    resp = client.post(f"{_org_base(org['id'])}/strategies/{strategy['id']}/propose", headers=auth_headers(org_admin_token))
    assert resp.status_code == 200, resp.text
    resp = client.post(
        f"{_org_base(org['id'])}/strategies/{strategy['id']}/submit-for-review", headers=auth_headers(org_admin_token)
    )
    assert resp.status_code == 200, resp.text

    resp = client.post(
        f"{_org_base(org['id'])}/strategies/{strategy['id']}/approve", json={}, headers=auth_headers(approver_token)
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "approved"


# --- Disabled module / cross-tenant isolation -------------------------------


def test_disabled_module_is_404_not_403(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "CtxStrategy Disabled Co")
    project = create_project(client, org_admin_token, org["id"], "CtxStrategy Disabled Co Project")
    # Module never enabled for this org.
    resp = client.get(_project_base(project["id"]) + "/strategies", headers=auth_headers(org_admin_token))
    assert resp.status_code == 404, resp.text


def test_disabled_strategy_subcomponent_is_404_project_scoped(client, admin_token):
    """Module 0 (Platform Foundations) Phase 4's real end-to-end consumer:
    disabling the org's default for the `"strategy"` sub-component of
    `context_strategy` (with the whole module still enabled) 404s the
    project-scoped Strategy endpoints, same posture as the whole module
    being disabled."""
    org, project, org_admin_token = _setup(client, admin_token, "CtxStrategy Subcomponent Disabled Co")
    resp = client.put(
        f"/api/v1/orgs/{org['id']}/modules/{MODULE_KEY}/subcomponents/strategy",
        json={"enabled": False}, headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 200, resp.text

    resp = client.get(_project_base(project["id"]) + "/strategies", headers=auth_headers(org_admin_token))
    assert resp.status_code == 404, resp.text


def test_project_override_re_enables_strategy_subcomponent_over_org_default(client, admin_token):
    """A project admin's own override wins over the organisation's
    default — the project-level half of Phase 4's two-tier resolution,
    exercised against the real Strategy endpoints."""
    org, project, org_admin_token = _setup(client, admin_token, "CtxStrategy Subcomponent Override Co")
    resp = client.put(
        f"/api/v1/orgs/{org['id']}/modules/{MODULE_KEY}/subcomponents/strategy",
        json={"enabled": False}, headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 200, resp.text
    # Confirm the org default alone does 404 the project first.
    resp = client.get(_project_base(project["id"]) + "/strategies", headers=auth_headers(org_admin_token))
    assert resp.status_code == 404, resp.text

    resp = client.put(
        f"/api/v1/projects/{project['id']}/modules/{MODULE_KEY}/subcomponents/strategy",
        json={"enabled": True}, headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["effective_enabled"] is True
    assert body["org_default_enabled"] is False
    assert body["has_project_override"] is True

    resp = client.get(_project_base(project["id"]) + "/strategies", headers=auth_headers(org_admin_token))
    assert resp.status_code == 200, resp.text


def test_disabled_strategy_subcomponent_is_404_org_scoped(client, admin_token):
    """Org-scoped sibling of the project-scoped test above — an org-scoped
    Strategy has no project tier at all, so the org default alone is the
    effective gate (`require_org_subcomponent_enabled`)."""
    org, org_admin_token = create_org_admin_in(client, admin_token, "CtxStrategy Org Subcomponent Disabled Co")
    _enable_module(client, org_admin_token, org["id"])
    resp = client.put(
        f"/api/v1/orgs/{org['id']}/modules/{MODULE_KEY}/subcomponents/strategy",
        json={"enabled": False}, headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 200, resp.text

    resp = client.get(_org_base(org["id"]) + "/strategies", headers=auth_headers(org_admin_token))
    assert resp.status_code == 404, resp.text


def test_strategy_from_another_project_is_404(client, admin_token):
    _, project_a, org_admin_token = _setup(client, admin_token, "CtxStrategy Isolation A Co")
    strategy = _create_project_strategy(client, org_admin_token, project_a["id"])

    org_b, org_b_admin_token = create_org_admin_in(client, admin_token, "CtxStrategy Isolation B Co")
    _enable_module(client, org_b_admin_token, org_b["id"])
    project_b = create_project(client, org_b_admin_token, org_b["id"], "CtxStrategy Isolation B Project")

    resp = client.get(
        f"{_project_base(project_b['id'])}/strategies/{strategy['id']}", headers=auth_headers(org_b_admin_token)
    )
    assert resp.status_code == 404, resp.text


# --- Comments and files ------------------------------------------------------


def test_comment_add_list_and_author_only_edit(client, admin_token):
    org, project, org_admin_token = _setup(client, admin_token, "CtxStrategy Comments Co")
    strategy = _create_project_strategy(client, org_admin_token, project["id"])
    _, other_token = _add_plain_member(
        client, org_admin_token, org["id"], project["id"], "commenter_two@example.com"
    )

    resp = client.post(
        f"{_project_base(project['id'])}/strategies/{strategy['id']}/comments", json={"body": "Initial thoughts."},
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 201, resp.text
    comment = resp.json()
    assert comment["edited_at"] is None

    resp = client.get(
        f"{_project_base(project['id'])}/strategies/{strategy['id']}/comments", headers=auth_headers(org_admin_token)
    )
    assert resp.status_code == 200, resp.text
    assert len(resp.json()) == 1

    # Non-author cannot edit.
    resp = client.patch(
        f"{_project_base(project['id'])}/strategies/{strategy['id']}/comments/{comment['id']}",
        json={"body": "Edited by someone else"}, headers=auth_headers(other_token),
    )
    assert resp.status_code == 403, resp.text

    resp = client.patch(
        f"{_project_base(project['id'])}/strategies/{strategy['id']}/comments/{comment['id']}",
        json={"body": "Edited by the author"}, headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["edited_at"] is not None


def test_direct_file_attachment_upload_list_unlink_and_lock(client, admin_token):
    org, project, org_admin_token = _setup(client, admin_token, "CtxStrategy Files Co")
    user_id, approver_token = _add_plain_member(
        client, org_admin_token, org["id"], project["id"], "file_approver@example.com"
    )
    _grant_project_module_role(client, org_admin_token, project["id"], user_id, "strategy_approver")
    strategy = _create_project_strategy(client, org_admin_token, project["id"])

    resp = client.post(
        f"{_project_base(project['id'])}/strategies/{strategy['id']}/files",
        files={"file": ("plan.txt", b"strategy content", "text/plain")}, headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 201, resp.text
    file_id = resp.json()["id"]

    resp = client.get(
        f"{_project_base(project['id'])}/strategies/{strategy['id']}/files", headers=auth_headers(org_admin_token)
    )
    assert resp.status_code == 200, resp.text
    assert len(resp.json()) == 1

    resp = client.delete(
        f"{_project_base(project['id'])}/strategies/{strategy['id']}/files/{file_id}",
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 204, resp.text

    # Lock check: once approved, new attachments are rejected.
    _advance_project_strategy_to_under_review(client, org_admin_token, project["id"], strategy["id"])
    resp = client.post(
        f"{_project_base(project['id'])}/strategies/{strategy['id']}/approve", json={},
        headers=auth_headers(approver_token),
    )
    assert resp.status_code == 200, resp.text

    resp = client.post(
        f"{_project_base(project['id'])}/strategies/{strategy['id']}/files",
        files={"file": ("plan2.txt", b"more content", "text/plain")}, headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 409, resp.text


# --- Frontend manifest (Phase 7.1) -------------------------------------------


def test_frontend_manifest_registers_the_strategy_nav_entry():
    """Phase 7.1 (2026-09-29): this module's first `frontend_manifest` —
    Strategy's own primary nav entry. Phase 7.2 (2026-09-29) appended Future
    State's own entry via `additional_nav_entries`; Phase 7.3 (2026-09-29)
    appended Pain Point's; Phase 7.4 (2026-09-29) appended Guiding
    Principle's; Phase 7.5 (2026-09-29) appends Open Question's — the fifth
    and last of the five planned top-level nav-rail entries (Phase 0 Q7,
    see `module.py`'s own docstring and `docs/decisions.md`'s nav-manifest-
    extension entry)."""
    manifest = get_frontend_manifest(MODULE_KEY)
    assert manifest is not None
    assert manifest.tier == "installed"
    assert manifest.nav_label == "Strategy"
    assert manifest.nav_path == f"/projects/{{project_id}}/modules/{MODULE_KEY}/strategies"
    assert manifest.nav_icon == "compass"
    assert manifest.additional_nav_entries == (
        ModuleNavEntry(
            nav_label="Future State",
            nav_path=f"/projects/{{project_id}}/modules/{MODULE_KEY}/future-states",
            nav_icon="telescope",
        ),
        ModuleNavEntry(
            nav_label="Pain Point",
            nav_path=f"/projects/{{project_id}}/modules/{MODULE_KEY}/pain-points",
            nav_icon="alert-triangle",
        ),
        ModuleNavEntry(
            nav_label="Guiding Principle",
            nav_path=f"/projects/{{project_id}}/modules/{MODULE_KEY}/guiding-principles",
            nav_icon="anchor",
        ),
        ModuleNavEntry(
            nav_label="Open Question",
            nav_path=f"/projects/{{project_id}}/modules/{MODULE_KEY}/open-questions",
            nav_icon="circle-help",
        ),
    )
