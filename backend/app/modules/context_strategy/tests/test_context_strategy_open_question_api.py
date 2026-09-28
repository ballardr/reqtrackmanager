"""Tests for Context & Strategy's Phase 5 backend API
(docs/plans/module-01-context-and-strategy-plan.md Phase 5 — Open
Questions) — the real HTTP endpoints (`project_router.py`'s project-scoped
Open Question surface; there is no org-scoped Open Question resource, and
no org-scoped `router.py` change to test — see that phase's own notes),
through the `client` fixture, mirroring `test_context_strategy_pain_point_
api.py`'s own "go through the real API" convention. A new sibling file
rather than appending to an existing one (Decided by: Agent), matching
Phase 2-4's own precedent exactly.

Covers: Open Question create/get (project-scoped only), the broad-creation
permission model (any project member, §9.4), the branching lifecycle
(`Open -> Investigating -> {Withdrawn | Ready for Decision -> {Resolved |
Withdrawn}}`, both terminal outcomes reachable, an illegal transition 409,
mandatory comment on withdraw), the two-role split (`open_question_owner`
for "change status"-tier actions vs. `open_question_resolver` for `resolve`
alone — §9.4's distinct "Question Owner / Project Manager" vs. "Decision
Maker" tiers), a Fine-Grained Access Control custom-role permission grant
satisfying the resolve gate, disabled-module/sub-component 404s,
cross-project isolation, and comments/direct file attachments (including
the deliberately-broad "any member may add evidence" file-upload gate).
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


_PAYLOAD_FIELDS = {
    "question": "Should the drone fleet standardise on a single battery vendor?",
    "context": "Falcon-3 currently qualifies batteries from two vendors; a single-vendor policy would simplify"
    " spares logistics but increases supply-chain risk.",
    "evidence": "Procurement flagged a 6-week lead-time gap for Vendor B in the last quarter.",
    "priority": "high",
    "due_date": "2026-10-15",
}


def _create_open_question(client, token, project_id, **extra) -> dict:
    payload = {**_PAYLOAD_FIELDS, **extra}
    resp = client.post(_project_base(project_id) + "/open-questions", json=payload, headers=auth_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _advance_to_ready_for_decision(client, token, project_id, open_question_id) -> dict:
    base = f"{_project_base(project_id)}/open-questions/{open_question_id}"
    resp = client.post(f"{base}/investigate", json={}, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    resp = client.post(f"{base}/mark-ready-for-decision", json={}, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


# --- CRUD ---------------------------------------------------------------------


def test_create_and_get_open_question(client, admin_token):
    _, project, org_admin_token = _setup(client, admin_token, "OpenQuestion Create Co")
    open_question = _create_open_question(client, org_admin_token, project["id"])

    assert open_question["project_id"] == project["id"]
    assert open_question["status"] == "open"
    assert open_question["is_locked"] is False

    resp = client.get(
        f"{_project_base(project['id'])}/open-questions/{open_question['id']}", headers=auth_headers(org_admin_token)
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == open_question["id"]


def test_any_project_member_may_create_an_open_question_no_owner_role_required(client, admin_token):
    org, project, org_admin_token = _setup(client, admin_token, "OpenQuestion Broad Create Co")
    _, member_token = _add_plain_member(
        client, org_admin_token, org["id"], project["id"], "oq_broad_creator@example.com"
    )
    _create_open_question(client, member_token, project["id"])


def test_plain_member_cannot_update_an_open_question(client, admin_token):
    org, project, org_admin_token = _setup(client, admin_token, "OpenQuestion Update RBAC Co")
    open_question = _create_open_question(client, org_admin_token, project["id"])
    _, member_token = _add_plain_member(
        client, org_admin_token, org["id"], project["id"], "oq_update_denied@example.com"
    )
    payload = {**_PAYLOAD_FIELDS, "priority": "low"}
    resp = client.put(
        f"{_project_base(project['id'])}/open-questions/{open_question['id']}", json=payload,
        headers=auth_headers(member_token),
    )
    assert resp.status_code == 403, resp.text


def test_owner_can_update_an_open_question(client, admin_token):
    _, project, org_admin_token = _setup(client, admin_token, "OpenQuestion Update Owner Co")
    open_question = _create_open_question(client, org_admin_token, project["id"])
    payload = {**_PAYLOAD_FIELDS, "priority": "low", "question": "Revised question wording?"}
    resp = client.put(
        f"{_project_base(project['id'])}/open-questions/{open_question['id']}", json=payload,
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["question"] == "Revised question wording?"
    assert resp.json()["priority"] == "low"


# --- Branching lifecycle -------------------------------------------------------


def test_full_branch_ready_for_decision_through_resolved(client, admin_token):
    _, project, org_admin_token = _setup(client, admin_token, "OpenQuestion Resolve Branch Co")
    open_question = _create_open_question(client, org_admin_token, project["id"])
    _advance_to_ready_for_decision(client, org_admin_token, project["id"], open_question["id"])

    resp = client.post(
        f"{_project_base(project['id'])}/open-questions/{open_question['id']}/resolve", json={},
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "resolved"
    assert resp.json()["is_locked"] is True


def test_branch_withdrawn_from_ready_for_decision_requires_a_comment(client, admin_token):
    _, project, org_admin_token = _setup(client, admin_token, "OpenQuestion Withdraw Branch Co")
    open_question = _create_open_question(client, org_admin_token, project["id"])
    _advance_to_ready_for_decision(client, org_admin_token, project["id"], open_question["id"])

    resp = client.post(
        f"{_project_base(project['id'])}/open-questions/{open_question['id']}/withdraw", json={},
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 400, resp.text

    resp = client.post(
        f"{_project_base(project['id'])}/open-questions/{open_question['id']}/withdraw",
        json={"comment": "Superseded by a broader fleet-standardisation decision."},
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "withdrawn"
    assert resp.json()["is_locked"] is True


def test_branch_withdrawn_directly_from_investigating(client, admin_token):
    """Unlike `READY_FOR_DECISION`, `OPEN` cannot skip straight to
    `WITHDRAWN` — only `INVESTIGATING`/`READY_FOR_DECISION` can. Covers the
    mid-chain branch (`enums.OpenQuestionStatus`'s own docstring)."""
    _, project, org_admin_token = _setup(client, admin_token, "OpenQuestion Early Withdraw Co")
    open_question = _create_open_question(client, org_admin_token, project["id"])
    resp = client.post(
        f"{_project_base(project['id'])}/open-questions/{open_question['id']}/investigate", json={},
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "investigating"

    resp = client.post(
        f"{_project_base(project['id'])}/open-questions/{open_question['id']}/withdraw",
        json={"comment": "Already answered in an unrelated design review."}, headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "withdrawn"


def test_open_cannot_skip_directly_to_withdrawn(client, admin_token):
    _, project, org_admin_token = _setup(client, admin_token, "OpenQuestion No Skip Co")
    open_question = _create_open_question(client, org_admin_token, project["id"])
    resp = client.post(
        f"{_project_base(project['id'])}/open-questions/{open_question['id']}/withdraw",
        json={"comment": "Not relevant."}, headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 409, resp.text


def test_illegal_transition_is_409(client, admin_token):
    _, project, org_admin_token = _setup(client, admin_token, "OpenQuestion Illegal Transition Co")
    open_question = _create_open_question(client, org_admin_token, project["id"])

    resp = client.post(
        f"{_project_base(project['id'])}/open-questions/{open_question['id']}/resolve", json={},
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 409, resp.text


def test_plain_member_cannot_investigate(client, admin_token):
    org, project, org_admin_token = _setup(client, admin_token, "OpenQuestion Investigate RBAC Co")
    open_question = _create_open_question(client, org_admin_token, project["id"])
    _, member_token = _add_plain_member(
        client, org_admin_token, org["id"], project["id"], "oq_investigate_denied@example.com"
    )
    resp = client.post(
        f"{_project_base(project['id'])}/open-questions/{open_question['id']}/investigate", json={},
        headers=auth_headers(member_token),
    )
    assert resp.status_code == 403, resp.text


def test_open_question_owner_role_can_investigate(client, admin_token):
    org, project, org_admin_token = _setup(client, admin_token, "OpenQuestion Owner Role Co")
    user_id, owner_token = _add_plain_member(
        client, org_admin_token, org["id"], project["id"], "oq_owner@example.com"
    )
    _grant_project_module_role(client, org_admin_token, project["id"], user_id, "open_question_owner")
    open_question = _create_open_question(client, org_admin_token, project["id"])

    resp = client.post(
        f"{_project_base(project['id'])}/open-questions/{open_question['id']}/investigate", json={},
        headers=auth_headers(owner_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "investigating"


def test_open_question_owner_alone_cannot_resolve(client, admin_token):
    """§9.4's own three-tier split: `open_question_owner` covers "change
    status" but not `resolve` — that is `open_question_resolver`'s own,
    separate tier (`module.py`'s docstring)."""
    org, project, org_admin_token = _setup(client, admin_token, "OpenQuestion Owner Cannot Resolve Co")
    user_id, owner_token = _add_plain_member(
        client, org_admin_token, org["id"], project["id"], "oq_owner_only@example.com"
    )
    _grant_project_module_role(client, org_admin_token, project["id"], user_id, "open_question_owner")
    open_question = _create_open_question(client, org_admin_token, project["id"])
    _advance_to_ready_for_decision(client, org_admin_token, project["id"], open_question["id"])

    resp = client.post(
        f"{_project_base(project['id'])}/open-questions/{open_question['id']}/resolve", json={},
        headers=auth_headers(owner_token),
    )
    assert resp.status_code == 403, resp.text


def test_open_question_resolver_role_can_resolve(client, admin_token):
    org, project, org_admin_token = _setup(client, admin_token, "OpenQuestion Resolver Role Co")
    user_id, resolver_token = _add_plain_member(
        client, org_admin_token, org["id"], project["id"], "oq_resolver@example.com"
    )
    _grant_project_module_role(client, org_admin_token, project["id"], user_id, "open_question_resolver")
    open_question = _create_open_question(client, org_admin_token, project["id"])
    _advance_to_ready_for_decision(client, org_admin_token, project["id"], open_question["id"])

    resp = client.post(
        f"{_project_base(project['id'])}/open-questions/{open_question['id']}/resolve", json={},
        headers=auth_headers(resolver_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "resolved"


def test_resolve_reachable_via_custom_role_grant_of_approve_baseline_permission(client, admin_token):
    org, project, org_admin_token = _setup(client, admin_token, "OpenQuestion Custom Role Co")
    user_id, member_token = _add_plain_member(
        client, org_admin_token, org["id"], project["id"], "oq_custom_role@example.com"
    )
    open_question = _create_open_question(client, org_admin_token, project["id"])
    _advance_to_ready_for_decision(client, org_admin_token, project["id"], open_question["id"])

    resp = client.post(
        f"{_project_base(project['id'])}/open-questions/{open_question['id']}/resolve", json={},
        headers=auth_headers(member_token),
    )
    assert resp.status_code == 403, resp.text

    from app.database import SessionLocal

    db = SessionLocal()
    try:
        role = CustomRoleDefinition(
            organization_id=uuid.UUID(org["id"]), name="Open Question Decider (Custom)",
            description="Custom test role.", scope="project",
        )
        db.add(role)
        db.flush()
        db.add(
            CustomRolePermission(custom_role_id=role.id, permission=encode_permission("open_question", "approve_baseline"))
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
        f"{_project_base(project['id'])}/open-questions/{open_question['id']}/resolve", json={},
        headers=auth_headers(member_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "resolved"


# --- Disabled module / cross-tenant isolation -------------------------------


def test_disabled_module_is_404_not_403(client, admin_token):
    org, org_admin_token = create_org_admin_in(client, admin_token, "OpenQuestion Disabled Co")
    project = create_project(client, org_admin_token, org["id"], "OpenQuestion Disabled Co Project")
    resp = client.get(_project_base(project["id"]) + "/open-questions", headers=auth_headers(org_admin_token))
    assert resp.status_code == 404, resp.text


def test_disabled_open_question_subcomponent_is_404(client, admin_token):
    org, project, org_admin_token = _setup(client, admin_token, "OpenQuestion Subcomponent Disabled Co")
    resp = client.put(
        f"/api/v1/orgs/{org['id']}/modules/{MODULE_KEY}/subcomponents/open_question",
        json={"enabled": False}, headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 200, resp.text

    resp = client.get(_project_base(project["id"]) + "/open-questions", headers=auth_headers(org_admin_token))
    assert resp.status_code == 404, resp.text


def test_open_question_from_another_project_is_404(client, admin_token):
    _, project_a, org_admin_token = _setup(client, admin_token, "OpenQuestion Isolation Co A")
    _, project_b, _ = _setup(client, admin_token, "OpenQuestion Isolation Co B")
    open_question = _create_open_question(client, org_admin_token, project_a["id"])

    resp = client.get(
        f"{_project_base(project_b['id'])}/open-questions/{open_question['id']}", headers=auth_headers(org_admin_token)
    )
    assert resp.status_code == 404, resp.text


# --- Comments and evidence attachments ---------------------------------------


def test_comment_add_list_and_author_only_edit(client, admin_token):
    org, project, org_admin_token = _setup(client, admin_token, "OpenQuestion Comment Co")
    open_question = _create_open_question(client, org_admin_token, project["id"])
    _, member_token = _add_plain_member(
        client, org_admin_token, org["id"], project["id"], "oq_commenter@example.com"
    )

    resp = client.post(
        f"{_project_base(project['id'])}/open-questions/{open_question['id']}/comments",
        json={"body": "I'd suggest resolving this in favour of Vendor A given the lead-time data."},
        headers=auth_headers(member_token),
    )
    assert resp.status_code == 201, resp.text
    comment = resp.json()

    resp = client.get(
        f"{_project_base(project['id'])}/open-questions/{open_question['id']}/comments",
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert len(resp.json()) == 1

    resp = client.patch(
        f"{_project_base(project['id'])}/open-questions/{open_question['id']}/comments/{comment['id']}",
        json={"body": "Edited suggestion."}, headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 403, resp.text


def test_any_member_may_upload_evidence_file(client, admin_token):
    """§9.4's broad "Add evidence" — deliberately open to any project
    member, unlike Strategy/Future State/Guiding Principle's owner-gated
    direct file uploads (see `project_router.upload_project_open_question_
    file`'s own docstring)."""
    org, project, org_admin_token = _setup(client, admin_token, "OpenQuestion Evidence Co")
    _, member_token = _add_plain_member(
        client, org_admin_token, org["id"], project["id"], "oq_evidence_uploader@example.com"
    )
    open_question = _create_open_question(client, org_admin_token, project["id"])

    resp = client.post(
        f"{_project_base(project['id'])}/open-questions/{open_question['id']}/files",
        files={"file": ("evidence.txt", b"Vendor lead-time comparison attached.", "text/plain")},
        headers=auth_headers(member_token),
    )
    assert resp.status_code == 201, resp.text

    resp = client.get(
        f"{_project_base(project['id'])}/open-questions/{open_question['id']}/files",
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert len(resp.json()) == 1


def test_evidence_file_upload_locked_once_terminal(client, admin_token):
    _, project, org_admin_token = _setup(client, admin_token, "OpenQuestion Evidence Locked Co")
    open_question = _create_open_question(client, org_admin_token, project["id"])
    resp = client.post(
        f"{_project_base(project['id'])}/open-questions/{open_question['id']}/withdraw",
        json={"comment": "Not relevant."}, headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 409, resp.text  # OPEN cannot skip directly to WITHDRAWN (comment mandatory-check passes first)

    resp = client.post(
        f"{_project_base(project['id'])}/open-questions/{open_question['id']}/investigate", json={},
        headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 200, resp.text
    resp = client.post(
        f"{_project_base(project['id'])}/open-questions/{open_question['id']}/withdraw",
        json={"comment": "No longer relevant."}, headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 200, resp.text

    resp = client.post(
        f"{_project_base(project['id'])}/open-questions/{open_question['id']}/files",
        files={"file": ("late.txt", b"too late", "text/plain")}, headers=auth_headers(org_admin_token),
    )
    assert resp.status_code == 409, resp.text
