"""Tests for the AI-approval-via-MCP gate as applied to Decision
Management's own `approve_decision_endpoint`/`reject_decision_endpoint`
(`project_router.py`), added 2026-09-22 alongside the "Decision Management
MCP approval gate" entry (docs/decisions.md) — the user's explicit
follow-up ("Yes, apply the same treatment") to the "Compliance MCP write
tools + generalized AI approval gate" entry, which had left this module's
approve/reject as the one architecturally-identical case still excluded
via `APPROVAL_ACTION_ROUTE_EXTRA`.

Mirrors `backend/app/modules/compliance/tests/test_compliance_ai_
approvals_via_mcp.py`'s exact 7-test shape, itself mirroring `backend/
tests/test_ai_approvals_via_mcp.py`'s pattern for the three core
endpoints: an MCP-originated call (`X-Reqtrack-Client: mcp-server`, see
`app.deps.get_request_channel`) is rejected unless both the project's and
its organisation's `allow_ai_approvals` flags are true, a plain UI/API
call is entirely unaffected by either flag, and the calling account's own
`decision_approver`/`PROJECT_MANAGER` role is still required regardless of
either flag (the gate only narrows, it never widens, real RBAC).

`propose`/`submit-for-review` are also proven unaffected by the gate — they
never carried `APPROVAL_ACTION_ROUTE_EXTRA` and need no `allow_ai_
approvals` opt-in, since neither one decides anything (mirroring
Compliance's own `submit_requirement_for_approval` treatment).
"""

from __future__ import annotations

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.modules.decisions.tests.test_decisions_api import (
    _add_plain_member,
    _advance_to_under_review,
    _base,
    _create_decision,
    _first_decision_type_id,
    _setup,
)
from tests.conftest import auth_headers
from tests.test_ai_approvals_via_mcp import _mcp_headers, _set_org_ai_approvals, _set_project_ai_approvals


def _latest_audit_event(decision_id: str, action: str) -> AuditEvent | None:
    """Decision Management has no per-decision `/history` HTTP endpoint
    (unlike Compliance's `get_requirement_history`), so these tests read
    the underlying `AuditEvent` row directly to check the `via`/`mcp`
    marker `_transition_status` (`service.py`) records."""
    db = SessionLocal()
    try:
        return (
            db.query(AuditEvent)
            .filter(AuditEvent.entity_type == "decision", AuditEvent.entity_id == decision_id, AuditEvent.action == action)
            .order_by(AuditEvent.created_at.desc())
            .first()
        )
    finally:
        db.close()


def _setup_under_review_decision(client, admin_token, org_name: str):
    """Creates a fresh org+project with Decision Management enabled, and a
    Decision already advanced to `UNDER_REVIEW` (the precondition for
    `approve`/`reject`). Returns (org, project, org_admin_token, decision_id)."""
    org, project, org_admin_token = _setup(client, admin_token, org_name)
    decision_type_id = _first_decision_type_id(client, org_admin_token, project["id"])
    decision = _create_decision(client, org_admin_token, project["id"], decision_type_id)
    _advance_to_under_review(client, org_admin_token, project["id"], decision["id"])
    return org, project, org_admin_token, decision["id"]


def test_mcp_propose_and_submit_for_review_are_unaffected_by_the_gate(client, admin_token):
    """`propose`/`submit-for-review` never carried an approval-type gate —
    they only queue a decision for review, they don't decide anything — and
    still don't need one after this change."""
    org, project, org_admin_token = _setup(client, admin_token, "Decisions MCP Propose Org")
    decision_type_id = _first_decision_type_id(client, org_admin_token, project["id"])
    decision = _create_decision(client, org_admin_token, project["id"], decision_type_id)

    resp = client.post(f"{_base(project['id'])}/{decision['id']}/propose", headers=_mcp_headers(org_admin_token))
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "proposed"

    resp = client.post(
        f"{_base(project['id'])}/{decision['id']}/submit-for-review", headers=_mcp_headers(org_admin_token)
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "under_review"


def test_mcp_approve_decision_blocked_when_both_flags_off(client, admin_token):
    org, project, org_admin_token, decision_id = _setup_under_review_decision(
        client, admin_token, "Decisions MCP Approve Off Org"
    )

    resp = client.post(
        f"{_base(project['id'])}/{decision_id}/approve", json={"comment": None}, headers=_mcp_headers(org_admin_token)
    )
    assert resp.status_code == 403
    assert "AI approval is not enabled" in resp.text


def test_mcp_approve_decision_blocked_when_only_one_flag_is_on(client, admin_token):
    org, project, org_admin_token, decision_id = _setup_under_review_decision(
        client, admin_token, "Decisions MCP Approve Partial Org"
    )

    _set_org_ai_approvals(client, org_admin_token, org["id"], True)
    resp = client.post(
        f"{_base(project['id'])}/{decision_id}/approve", json={"comment": None}, headers=_mcp_headers(org_admin_token)
    )
    assert resp.status_code == 403

    _set_org_ai_approvals(client, org_admin_token, org["id"], False)
    _set_project_ai_approvals(client, org_admin_token, project["id"], True)
    resp = client.post(
        f"{_base(project['id'])}/{decision_id}/approve", json={"comment": None}, headers=_mcp_headers(org_admin_token)
    )
    assert resp.status_code == 403


def test_mcp_approve_decision_allowed_when_both_flags_on_and_marks_via_mcp(client, admin_token):
    org, project, org_admin_token, decision_id = _setup_under_review_decision(
        client, admin_token, "Decisions MCP Approve On Org"
    )
    _set_org_ai_approvals(client, org_admin_token, org["id"], True)
    _set_project_ai_approvals(client, org_admin_token, project["id"], True)

    resp = client.post(
        f"{_base(project['id'])}/{decision_id}/approve",
        json={"comment": "Reviewed via AI assistant."}, headers=_mcp_headers(org_admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "approved"

    event = _latest_audit_event(decision_id, "approved")
    assert event is not None
    assert event.detail["via"] == "mcp"


def test_mcp_reject_decision_blocked_then_allowed(client, admin_token):
    org, project, org_admin_token, decision_id = _setup_under_review_decision(
        client, admin_token, "Decisions MCP Reject Org"
    )

    blocked = client.post(
        f"{_base(project['id'])}/{decision_id}/reject",
        json={"comment": "Not sufficient."}, headers=_mcp_headers(org_admin_token),
    )
    assert blocked.status_code == 403

    _set_org_ai_approvals(client, org_admin_token, org["id"], True)
    _set_project_ai_approvals(client, org_admin_token, project["id"], True)
    allowed = client.post(
        f"{_base(project['id'])}/{decision_id}/reject",
        json={"comment": "Not sufficient."}, headers=_mcp_headers(org_admin_token),
    )
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["status"] == "rejected"

    event = _latest_audit_event(decision_id, "rejected")
    assert event is not None
    assert event.detail["via"] == "mcp"


def test_ui_channel_approve_decision_unaffected_by_flags_being_off(client, admin_token):
    """Regression guard: the gate must never affect a plain UI/API call (no
    X-Reqtrack-Client header) — a human with the right role can still
    approve directly, regardless of either flag's value."""
    org, project, org_admin_token, decision_id = _setup_under_review_decision(
        client, admin_token, "Decisions UI Approve Org"
    )

    resp = client.post(
        f"{_base(project['id'])}/{decision_id}/approve", json={"comment": None}, headers=auth_headers(org_admin_token)
    )
    assert resp.status_code == 200, resp.text

    event = _latest_audit_event(decision_id, "approved")
    assert event is not None
    assert event.detail is None or "via" not in event.detail


def test_mcp_approve_still_requires_real_rbac_role_even_with_both_flags_on(client, admin_token):
    """The gate only narrows access, it never widens it: a plain project
    member (no decision_approver grant, no PROJECT_MANAGER) is still 403'd
    through MCP even once both AI-approval flags are enabled."""
    org, project, org_admin_token, decision_id = _setup_under_review_decision(
        client, admin_token, "Decisions MCP RBAC Org"
    )
    _set_org_ai_approvals(client, org_admin_token, org["id"], True)
    _set_project_ai_approvals(client, org_admin_token, project["id"], True)

    plain_id, plain_token = _add_plain_member(
        client, org_admin_token, org["id"], project["id"], "decisions.mcp.plain@example.com"
    )

    resp = client.post(
        f"{_base(project['id'])}/{decision_id}/approve", json={"comment": None}, headers=_mcp_headers(plain_token)
    )
    assert resp.status_code == 403
    assert "AI approval" not in resp.text
