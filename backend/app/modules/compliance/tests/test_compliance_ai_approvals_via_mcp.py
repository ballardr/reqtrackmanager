"""Tests for the AI-approval-via-MCP gate as applied to Compliance's own
`approve_requirement`/`reject_requirement` (`project_router.py`), added
2026-09-22 alongside the "Compliance MCP write tools + generalized AI
approval gate" reversal (docs/decisions.md) — mirrors `backend/tests/
test_ai_approvals_via_mcp.py`'s exact pattern for the three core endpoints,
proving `app.services.rbac.require_ai_approvals_enabled` behaves
identically when called from a module's own router: an MCP-originated call
(`X-Reqtrack-Client: mcp-server`, see `app.deps.get_request_channel`) is
rejected unless both the project's and its organisation's `allow_ai_
approvals` flags are true, a plain UI/API call is entirely unaffected by
either flag, and the calling account's own `compliance_officer`/
`PROJECT_MANAGER` role is still required regardless of either flag (the
gate only narrows, it never widens, real RBAC).

`submit_requirement_for_approval` is also proven unaffected by the gate —
it no longer carries `APPROVAL_ACTION_ROUTE_EXTRA` and needs no `allow_ai_
approvals` opt-in, since it only queues a decision rather than deciding
anything.

Also covers `complete_required_action_assessment` (2026-09-23 hardening
pass): this endpoint's own docstring names `complete_requirement` (core)
as its shape template, but it was missing that endpoint's MCP gate
entirely — found and fixed in that pass. `uncomplete_required_action_
assessment` is deliberately left ungated, mirroring core's own documented
complete/uncomplete asymmetry (`uncomplete_requirement` is also ungated) —
not tested here for the gate itself, only that it remains reachable.

And `complete_project_review`/`complete_standard_review` (same pass):
these were found declared as plain, ungated MCP write tools despite
recording a review outcome being core's one categorically MCP-excluded
action in every configuration (`mcp-server/server.py`'s own instructions).
Fixed by marking both routes `APPROVAL_ACTION_ROUTE_EXTRA` and removing
their `McpToolDefinition` declarations — proven below by asserting neither
resolves via MCP at all, gate flags on or off, rather than a 403.
"""

from __future__ import annotations

from app.modules.compliance.tests.test_compliance_approval_workflow import _pcr_path, _setup_assessed_pcr
from app.modules.compliance.tests.test_project_compliance_api import (
    _assign_project_role,
    _assign_standard_to_project,
    _project_base,
    _setup_published_standard_with_tree,
)
from tests.conftest import auth_headers, create_org_user, create_project, login
from tests.test_ai_approvals_via_mcp import _mcp_headers, _set_org_ai_approvals, _set_project_ai_approvals


def test_mcp_submit_for_approval_is_unaffected_by_the_gate(client, admin_token, org_id):
    """submit-for-approval never carried an approval-type gate before this
    reversal removed its `APPROVAL_ACTION_ROUTE_EXTRA` marker, and still
    doesn't need one — it only queues a decision."""
    project, assignment, pcr_id, _tree = _setup_assessed_pcr(client, admin_token, org_id)

    resp = client.post(
        _pcr_path(project["id"], assignment["id"], pcr_id, "/submit-for-approval"), headers=_mcp_headers(admin_token)
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["approval_state"] == "pending_approval"


def test_mcp_approve_requirement_blocked_when_both_flags_off(client, admin_token, org_id):
    project, assignment, pcr_id, _tree = _setup_assessed_pcr(client, admin_token, org_id)
    client.post(_pcr_path(project["id"], assignment["id"], pcr_id, "/submit-for-approval"), headers=auth_headers(admin_token))

    resp = client.post(
        _pcr_path(project["id"], assignment["id"], pcr_id, "/approve"),
        json={"decision_note": ""}, headers=_mcp_headers(admin_token),
    )
    assert resp.status_code == 403
    assert "AI approval is not enabled" in resp.text


def test_mcp_approve_requirement_blocked_when_only_one_flag_is_on(client, admin_token, org_id):
    project, assignment, pcr_id, _tree = _setup_assessed_pcr(client, admin_token, org_id)
    client.post(_pcr_path(project["id"], assignment["id"], pcr_id, "/submit-for-approval"), headers=auth_headers(admin_token))

    _set_org_ai_approvals(client, admin_token, org_id, True)
    resp = client.post(
        _pcr_path(project["id"], assignment["id"], pcr_id, "/approve"),
        json={"decision_note": ""}, headers=_mcp_headers(admin_token),
    )
    assert resp.status_code == 403

    _set_org_ai_approvals(client, admin_token, org_id, False)
    _set_project_ai_approvals(client, admin_token, project["id"], True)
    resp = client.post(
        _pcr_path(project["id"], assignment["id"], pcr_id, "/approve"),
        json={"decision_note": ""}, headers=_mcp_headers(admin_token),
    )
    assert resp.status_code == 403


def test_mcp_approve_requirement_allowed_when_both_flags_on_and_marks_via_mcp(client, admin_token, org_id):
    project, assignment, pcr_id, _tree = _setup_assessed_pcr(client, admin_token, org_id)
    client.post(_pcr_path(project["id"], assignment["id"], pcr_id, "/submit-for-approval"), headers=auth_headers(admin_token))
    _set_org_ai_approvals(client, admin_token, org_id, True)
    _set_project_ai_approvals(client, admin_token, project["id"], True)

    resp = client.post(
        _pcr_path(project["id"], assignment["id"], pcr_id, "/approve"),
        json={"decision_note": "Reviewed via AI assistant."}, headers=_mcp_headers(admin_token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["approval_state"] == "approved"

    history = client.get(
        _pcr_path(project["id"], assignment["id"], pcr_id, "/history"), headers=auth_headers(admin_token)
    ).json()
    latest = next(e for e in history if e["action"] == "approved")
    assert latest["detail"]["via"] == "mcp"


def test_mcp_reject_requirement_blocked_then_allowed(client, admin_token, org_id):
    project, assignment, pcr_id, _tree = _setup_assessed_pcr(client, admin_token, org_id)
    client.post(_pcr_path(project["id"], assignment["id"], pcr_id, "/submit-for-approval"), headers=auth_headers(admin_token))

    blocked = client.post(
        _pcr_path(project["id"], assignment["id"], pcr_id, "/reject"),
        json={"decision_note": "Not sufficient."}, headers=_mcp_headers(admin_token),
    )
    assert blocked.status_code == 403

    _set_org_ai_approvals(client, admin_token, org_id, True)
    _set_project_ai_approvals(client, admin_token, project["id"], True)
    allowed = client.post(
        _pcr_path(project["id"], assignment["id"], pcr_id, "/reject"),
        json={"decision_note": "Not sufficient."}, headers=_mcp_headers(admin_token),
    )
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["approval_state"] == "rejected"

    history = client.get(
        _pcr_path(project["id"], assignment["id"], pcr_id, "/history"), headers=auth_headers(admin_token)
    ).json()
    latest = next(e for e in history if e["action"] == "rejected")
    assert latest["detail"]["via"] == "mcp"


def test_ui_channel_approve_requirement_unaffected_by_flags_being_off(client, admin_token, org_id):
    """Regression guard: the gate must never affect a plain UI/API call (no
    X-Reqtrack-Client header) — a human with the right role can still
    approve directly, regardless of either flag's value."""
    project, assignment, pcr_id, _tree = _setup_assessed_pcr(client, admin_token, org_id)
    client.post(_pcr_path(project["id"], assignment["id"], pcr_id, "/submit-for-approval"), headers=auth_headers(admin_token))

    resp = client.post(
        _pcr_path(project["id"], assignment["id"], pcr_id, "/approve"),
        json={"decision_note": ""}, headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200, resp.text

    history = client.get(
        _pcr_path(project["id"], assignment["id"], pcr_id, "/history"), headers=auth_headers(admin_token)
    ).json()
    latest = next(e for e in history if e["action"] == "approved")
    assert latest["detail"] is None or "via" not in latest["detail"]


def test_mcp_approve_still_requires_real_rbac_role_even_with_both_flags_on(client, admin_token, org_id):
    """The gate only narrows access, it never widens it: a plain project
    member (no compliance_officer grant, no PROJECT_MANAGER) is still
    403'd through MCP even once both AI-approval flags are enabled."""
    project, assignment, pcr_id, _tree = _setup_assessed_pcr(client, admin_token, org_id)
    client.post(_pcr_path(project["id"], assignment["id"], pcr_id, "/submit-for-approval"), headers=auth_headers(admin_token))
    _set_org_ai_approvals(client, admin_token, org_id, True)
    _set_project_ai_approvals(client, admin_token, project["id"], True)

    plain_id = create_org_user(client, admin_token, org_id, "compliance.mcp.plain@example.com", role="member")
    _assign_project_role(client, admin_token, project["id"], plain_id, "stakeholder")
    plain_token = login(client, "compliance.mcp.plain@example.com", "Password123!")

    resp = client.post(
        _pcr_path(project["id"], assignment["id"], pcr_id, "/approve"),
        json={"decision_note": ""}, headers=_mcp_headers(plain_token),
    )
    assert resp.status_code == 403
    assert "AI approval" not in resp.text


# --- complete_required_action_assessment: MCP gate (2026-09-23 hardening pass) ----


def _setup_required_action_assessment(client, admin_token, org_id):
    """Standard -> published version -> project assignment -> the child
    requirement's one required-action assessment, mirroring
    `test_project_compliance_api.test_required_action_assessment_complete_
    and_uncomplete`'s own setup. Returns (project, base_url)."""
    standard, version, _parent, child, _pa, _child_action = _setup_published_standard_with_tree(
        client, admin_token, org_id
    )
    project = create_project(client, admin_token, org_id, name="Required Action MCP Gate Project")
    assignment = _assign_standard_to_project(client, admin_token, org_id, project["id"], standard["id"], version["id"])
    requirements = client.get(
        f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/requirements",
        headers=auth_headers(admin_token),
    ).json()
    child_pcr_id = next(r["id"] for r in requirements if r["requirement_id"] == child["id"])
    assessment_id = client.get(
        f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/requirements/{child_pcr_id}"
        "/required-action-assessments",
        headers=auth_headers(admin_token),
    ).json()[0]["id"]
    base = (
        f"{_project_base(project['id'])}/project-compliance/{assignment['id']}/requirements/{child_pcr_id}"
        f"/required-action-assessments/{assessment_id}"
    )
    return project, base


def test_mcp_complete_required_action_assessment_blocked_when_flags_off(client, admin_token, org_id):
    _project, base = _setup_required_action_assessment(client, admin_token, org_id)

    resp = client.post(f"{base}/complete", headers=_mcp_headers(admin_token))
    assert resp.status_code == 403
    assert "AI approval is not enabled" in resp.text


def test_mcp_complete_required_action_assessment_allowed_when_both_flags_on_and_marks_via_mcp(client, admin_token, org_id):
    project, base = _setup_required_action_assessment(client, admin_token, org_id)
    _set_org_ai_approvals(client, admin_token, org_id, True)
    _set_project_ai_approvals(client, admin_token, project["id"], True)

    resp = client.post(f"{base}/complete", headers=_mcp_headers(admin_token))
    assert resp.status_code == 200, resp.text
    assert resp.json()["is_completed"] is True


def test_ui_channel_complete_required_action_assessment_unaffected_by_flags_being_off(client, admin_token, org_id):
    """Regression guard: a plain UI/API call (no X-Reqtrack-Client header)
    is never affected by the gate, same as every other gated endpoint."""
    _project, base = _setup_required_action_assessment(client, admin_token, org_id)

    resp = client.post(f"{base}/complete", headers=auth_headers(admin_token))
    assert resp.status_code == 200, resp.text


def test_mcp_uncomplete_required_action_assessment_remains_ungated(client, admin_token, org_id):
    """`uncomplete` deliberately carries no gate at all (mirrors core's
    `uncomplete_requirement`) — an MCP-channel call succeeds with both
    flags off, unlike `complete` above."""
    _project, base = _setup_required_action_assessment(client, admin_token, org_id)
    client.post(f"{base}/complete", headers=auth_headers(admin_token))

    resp = client.post(f"{base}/uncomplete", headers=_mcp_headers(admin_token))
    assert resp.status_code == 200, resp.text
    assert resp.json()["is_completed"] is False


# --- complete_project_review / complete_standard_review: categorical MCP
# exclusion (2026-09-23 hardening pass) --------------------------------------------


def test_complete_project_review_and_complete_standard_review_are_not_mcp_tools(client, admin_token):
    """Recording a review outcome must never be reachable through the MCP
    server's own tool surface, in any configuration — mirroring core's
    `record_review_outcome`, which also has no MCP tool declared anywhere.
    Asserts against the real, live manifest endpoint the MCP server itself
    queries (`GET /api/v1/system/modules/mcp-tools`), not just the
    in-process registry, so this fails if either the route's
    `APPROVAL_ACTION_ROUTE_EXTRA` marker or the manifest-builder's own
    exclusion logic ever regresses."""
    tools = client.get("/api/v1/system/modules/mcp-tools", headers=auth_headers(admin_token)).json()
    names = {t["name"] for t in tools}
    assert "compliance_complete_project_review" not in names
    assert "compliance_complete_standard_review" not in names
