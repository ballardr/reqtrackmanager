"""Tests for Decision Management's MCP tools (docs/plans/module-04-decision-
management-plan.md, "Phase 4 addendum (2026-09-21) — MCP tools added"; the
2026-09-22 "Decision Management MCP approval gate" follow-up adds two more).

Mirrors `backend/tests/test_module_mcp_tools.py`'s own "against the REAL
registry" integration section (written against Compliance, the only prior
precedent) — Decision Management is already a real, permanent
`INSTALLED_MODULES` entry with real routers, so this proves the nine
declared `McpToolDefinition`s in `module.py` actually resolve against real
routes (not just that the declared strings look right). No `fake_module`
fixture / `INSTALLED_MODULES` mutation is needed, same reasoning as the
Compliance integration test this mirrors.

`approve_decision`/`reject_decision` no longer carry `APPROVAL_ACTION_
ROUTE_EXTRA` (removed from `project_router.py` as part of the 2026-09-22
gate) — they resolve as real, mutating tools here; the actual "is an
MCP-originated call to either one still blocked without the org+project
`allow_ai_approvals` opt-in" behaviour is covered by `test_decisions_ai_
approvals_via_mcp.py`, not this file (this file only proves the manifest
shape, the same division of labour `test_compliance_ai_approvals_via_mcp.py`
uses for Compliance)."""

from __future__ import annotations

from app.modules.registry import build_mcp_tool_manifest


def test_decisions_mcp_tools_resolve_against_the_real_registry():
    """All nine of Decision Management's declared tools resolve and carry
    exactly the path/body parameters their router endpoints require. Seven
    are read-only (`mutates=False`, all GET); `approve_decision`/
    `reject_decision` are mutating `POST` tools, gated by `require_ai_
    approvals_enabled` when reached through MCP (not by manifest exclusion
    — see this module's own docstring)."""
    tools = build_mcp_tool_manifest()
    by_name = {t.name: t for t in tools}

    assert "decisions_list_decision_types" in by_name
    assert "decisions_list_decisions" in by_name
    assert "decisions_get_decision" in by_name
    assert "decisions_list_decision_relationships" in by_name
    assert "decisions_list_decision_comments" in by_name
    assert "decisions_list_decision_files" in by_name
    assert "decisions_list_decision_templates" in by_name
    assert "decisions_approve_decision" in by_name
    assert "decisions_reject_decision" in by_name

    list_types = by_name["decisions_list_decision_types"]
    assert list_types.mutates is False
    assert list_types.method == "GET"
    assert list_types.path_template == "/api/v1/projects/{project_id}/modules/decisions/decision-types"
    assert {p["name"] for p in list_types.params} == {"project_id"}

    list_decisions = by_name["decisions_list_decisions"]
    assert list_decisions.mutates is False
    assert list_decisions.path_template == "/api/v1/projects/{project_id}/modules/decisions"
    assert {p["name"] for p in list_decisions.params} == {"project_id"}

    get_decision = by_name["decisions_get_decision"]
    assert get_decision.mutates is False
    assert get_decision.path_template == "/api/v1/projects/{project_id}/modules/decisions/{decision_id}"
    assert {p["name"] for p in get_decision.params} == {"project_id", "decision_id"}
    assert all(p["in"] == "path" and p["required"] for p in get_decision.params)

    list_relationships = by_name["decisions_list_decision_relationships"]
    assert list_relationships.mutates is False
    assert list_relationships.path_template == (
        "/api/v1/projects/{project_id}/modules/decisions/{decision_id}/relationships"
    )
    assert {p["name"] for p in list_relationships.params} == {"project_id", "decision_id"}

    list_comments = by_name["decisions_list_decision_comments"]
    assert list_comments.mutates is False
    assert list_comments.path_template == "/api/v1/projects/{project_id}/modules/decisions/{decision_id}/comments"
    assert {p["name"] for p in list_comments.params} == {"project_id", "decision_id"}

    list_files = by_name["decisions_list_decision_files"]
    assert list_files.mutates is False
    assert list_files.path_template == "/api/v1/projects/{project_id}/modules/decisions/{decision_id}/files"
    assert {p["name"] for p in list_files.params} == {"project_id", "decision_id"}

    # Org-scoped, via `router.py` rather than `project_router.py`.
    list_templates = by_name["decisions_list_decision_templates"]
    assert list_templates.mutates is False
    assert list_templates.path_template == "/api/v1/orgs/{organization_id}/modules/decisions/templates"
    assert {p["name"] for p in list_templates.params} == {"organization_id"}

    approve = by_name["decisions_approve_decision"]
    assert approve.mutates is True
    assert approve.method == "POST"
    assert approve.path_template == "/api/v1/projects/{project_id}/modules/decisions/{decision_id}/approve"
    assert {p["name"] for p in approve.params} == {"project_id", "decision_id", "comment"}

    reject = by_name["decisions_reject_decision"]
    assert reject.mutates is True
    assert reject.method == "POST"
    assert reject.path_template == "/api/v1/projects/{project_id}/modules/decisions/{decision_id}/reject"
    assert {p["name"] for p in reject.params} == {"project_id", "decision_id", "comment"}


def test_decisions_mcp_manifest_declares_no_other_mutating_tool():
    """Beyond the two approval-gated tools above, no other mutating tool is
    declared for this module — create/update/archive/unarchive/propose/
    submit-for-review/supersede/link/comment/file-attach all stay off the
    MCP tool surface (2026-09-22 addendum's own scope: only approve/reject
    were asked for)."""
    tools = build_mcp_tool_manifest()
    by_name = {t.name: t for t in tools}
    mutating_decisions_tools = {name for name, tool in by_name.items() if name.startswith("decisions_") and tool.mutates}
    assert mutating_decisions_tools == {"decisions_approve_decision", "decisions_reject_decision"}
