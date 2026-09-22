"""Tests for Decision Management's MCP tools (docs/plans/module-04-decision-
management-plan.md, "Phase 4 addendum (2026-09-21) — MCP tools added").

Mirrors `backend/tests/test_module_mcp_tools.py`'s own "against the REAL
registry" integration section (written against Compliance, the only prior
precedent) — Decision Management is already a real, permanent
`INSTALLED_MODULES` entry with real routers, so this proves the seven
declared `McpToolDefinition`s in `module.py` actually resolve against real
routes (not just that the declared strings look right), and — the load-
bearing assertion this addendum exists for — that `approve`/`reject` are
mechanically excluded from the built manifest now that `project_router.py`
marks both routes with `APPROVAL_ACTION_ROUTE_EXTRA`. No `fake_module`
fixture / `INSTALLED_MODULES` mutation is needed, same reasoning as the
Compliance integration test this mirrors.
"""

from __future__ import annotations

import dataclasses

from app.modules import registry as module_registry
from app.modules.decisions.module import DECISIONS_MODULE_KEY
from app.modules.registry import McpToolDefinition, build_mcp_tool_manifest, build_registry


def test_decisions_mcp_tools_resolve_against_the_real_registry():
    """All seven of Decision Management's declared tools resolve, are
    read-only (`mutates=False`, all GET), and carry exactly the path
    parameters their router endpoints require."""
    tools = build_mcp_tool_manifest()
    by_name = {t.name: t for t in tools}

    assert "decisions_list_decision_types" in by_name
    assert "decisions_list_decisions" in by_name
    assert "decisions_get_decision" in by_name
    assert "decisions_list_decision_relationships" in by_name
    assert "decisions_list_decision_comments" in by_name
    assert "decisions_list_decision_files" in by_name
    assert "decisions_list_decision_templates" in by_name

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


def test_decisions_mcp_manifest_excludes_approval_actions():
    """The actual load-bearing assertion this addendum exists for: `approve`
    and `reject` never appear in the built manifest, even though this
    module now declares real MCP tools (unlike before, when their absence
    was only because nothing was declared at all). This is true for two
    independent reasons — no `McpToolDefinition` for either action exists
    in `module.py`'s `mcp_tools` tuple, AND `project_router.py` marks both
    routes with `APPROVAL_ACTION_ROUTE_EXTRA` as defense-in-depth — but the
    assertion below only proves the observable outcome (nothing resolves),
    not which of the two reasons is doing the work in isolation."""
    tools = build_mcp_tool_manifest()
    names = {t.name for t in tools}

    assert not any("approve" in name for name in names if name.startswith("decisions_"))
    assert not any("reject" in name for name in names if name.startswith("decisions_"))
    assert "decisions_approve_decision" not in names
    assert "decisions_reject_decision" not in names

    # No mutating tool at all is declared for this module — create/update/
    # archive/unarchive/propose/submit-for-review/approve/reject/supersede/
    # link/comment/file-attach all stay off the MCP tool surface.
    assert not any(name.startswith("decisions_") and t.mutates for name, t in {t.name: t for t in tools}.items())


def test_decisions_manifest_would_exclude_approve_even_if_declared():
    """The real defense-in-depth proof, not just "no tool was declared for
    it": temporarily add an `McpToolDefinition` pointing straight at the
    real, live `POST .../{decision_id}/approve` route (which
    `project_router.py` marks `APPROVAL_ACTION_ROUTE_EXTRA`) to the real
    `decisions` module's own `mcp_tools`, rebuild the registry, and confirm
    the manifest builder still excludes it — proving the mechanical
    exclusion actually fires for this module's real route metadata, the
    same way `test_manifest_excludes_approval_marked_route_regardless_of_
    declaration` proves it against a synthetic fixture route in
    `backend/tests/test_module_mcp_tools.py`. Always restores the real,
    unmodified module definition afterwards, whether the assertion passes
    or fails."""
    installed = module_registry.INSTALLED_MODULES
    index = next(i for i, m in enumerate(installed) if m.key == DECISIONS_MODULE_KEY)
    original = installed[index]

    sneaky_tool = McpToolDefinition(
        name="sneaky_approve_decision",
        description="Tries to expose the approval-marked approve route as an MCP tool.",
        method="POST",
        path_template="/api/v1/projects/{project_id}/modules/decisions/{decision_id}/approve",
        params=[
            {"name": "project_id", "type": "uuid", "required": True, "in": "path", "description": ""},
            {"name": "decision_id", "type": "uuid", "required": True, "in": "path", "description": ""},
        ],
    )
    modified = dataclasses.replace(original, mcp_tools=(*original.mcp_tools, sneaky_tool))

    try:
        installed[index] = modified
        build_registry(force=True)
        tools = build_mcp_tool_manifest()
        assert "decisions_sneaky_approve_decision" not in {t.name for t in tools}
    finally:
        installed[index] = original
        build_registry(force=True)
