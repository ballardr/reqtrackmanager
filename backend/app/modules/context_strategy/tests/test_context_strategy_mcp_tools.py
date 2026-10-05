"""Tests for Context & Strategy's MCP tools (docs/plans/module-01-context-
and-strategy-plan.md Phase 6 — Cross-artefact relationships, "MCP tools"
section) — mirrors `backend/app/modules/decisions/tests/test_decisions_
mcp_tools.py`'s own "against the REAL registry" integration approach:
Context & Strategy is already a real, permanent `INSTALLED_MODULES` entry
with real routers, so this proves the 62 declared `McpToolDefinition`s in
`module.py` actually resolve against real routes (not just that the
declared strings look right) — no `fake_module` fixture / `INSTALLED_
MODULES` mutation needed.

The five approve/decide-tier tools (`approve_strategy`/`approve_future_
state`/`activate_guiding_principle`/`retire_guiding_principle`/`resolve_
open_question`) resolve here as ordinary mutating tools — the actual "is
an MCP-originated call to any of them still blocked without the org+
project `allow_ai_approvals` opt-in" behaviour is covered by
`test_context_strategy_relationships_api.py`'s own MCP-gate tests (one
representative case, `approve_strategy`), not this file (this file only
proves the manifest shape, the same division of labour `test_decisions_
mcp_tools.py`/`test_decisions_ai_approvals_via_mcp.py` use for Decision
Management).
"""

from __future__ import annotations

from app.modules.registry import build_mcp_tool_manifest


def _by_local_name() -> dict[str, object]:
    tools = build_mcp_tool_manifest()
    return {t.name.removeprefix("context_strategy_"): t for t in tools if t.name.startswith("context_strategy_")}


def test_context_strategy_mcp_tools_resolve_against_the_real_registry():
    """All 62 declared tools resolve — no tool is silently excluded by
    `build_mcp_tool_manifest`'s mechanical verification (a wrong path
    template, an unmatched route, or a mismatched method would exclude a
    tool rather than error, so this count is the actual regression guard —
    see that function's own docstring)."""
    by_name = _by_local_name()
    assert len(by_name) == 62


def test_context_strategy_read_only_tools_are_get_and_non_mutating():
    by_name = _by_local_name()
    for name in (
        "list_strategies", "get_strategy", "list_future_states", "get_future_state",
        "list_pain_points", "get_pain_point", "list_guiding_principles", "get_guiding_principle",
        "list_open_questions", "get_open_question",
        "list_strategy_relationships", "list_future_state_relationships", "list_pain_point_relationships",
        "list_guiding_principle_relationships", "list_open_question_relationships",
    ):
        tool = by_name[name]
        assert tool.method == "GET", name
        assert tool.mutates is False, name


def test_context_strategy_create_tools_have_the_expected_shape():
    by_name = _by_local_name()

    create_strategy = by_name["create_strategy"]
    assert create_strategy.method == "POST"
    assert create_strategy.mutates is True
    assert create_strategy.path_template == "/api/v1/projects/{project_id}/modules/context_strategy/strategies"
    param_names = {p["name"] for p in create_strategy.params}
    assert {"project_id", "title", "objective"} <= param_names

    create_pain_point = by_name["create_pain_point"]
    assert create_pain_point.path_template == "/api/v1/projects/{project_id}/modules/context_strategy/pain-points"
    assert {"pain_point_type_id", "title"} <= {p["name"] for p in create_pain_point.params}


def test_context_strategy_relationship_tools_resolve_to_the_right_paths():
    by_name = _by_local_name()

    create_pp_link = by_name["create_pain_point_relationship"]
    assert create_pp_link.method == "POST"
    assert create_pp_link.path_template == (
        "/api/v1/projects/{project_id}/modules/context_strategy/pain-points/{pain_point_id}/relationships"
    )
    assert {p["name"] for p in create_pp_link.params} == {"project_id", "pain_point_id", "kind", "target_id"}

    supersession = by_name["create_strategy_supersession"]
    assert supersession.path_template == (
        "/api/v1/projects/{project_id}/modules/context_strategy/strategies/{strategy_id}/supersessions"
    )
    assert {p["name"] for p in supersession.params} == {"project_id", "strategy_id", "old_strategy_id", "comment"}


def test_context_strategy_gated_tools_are_present_and_mutating():
    """The five approve/decide-tier tools this phase's `require_ai_
    approvals_enabled` gate applies to (per `service.py`'s own "MCP tools
    and the `require_ai_approvals_enabled` gate" docstring section) —
    Guiding Principle's own gated pair is `activate`/`retire`, not
    `approve`, deliberately asymmetric with Strategy/Future State."""
    by_name = _by_local_name()
    gated_names = {
        "approve_strategy", "approve_future_state", "activate_guiding_principle",
        "retire_guiding_principle", "resolve_open_question",
    }
    for name in gated_names:
        tool = by_name[name]
        assert tool.method == "POST", name
        assert tool.mutates is True, name
    # Guiding Principle's own `approve` is declared too, but deliberately
    # NOT one of the five gated tools above (activate/retire are; approve
    # isn't) — see `service.py`'s own docstring for the asymmetry with
    # Strategy/Future State's gated `approve`.
    assert "approve_guiding_principle" in by_name
    assert "approve_guiding_principle" not in gated_names


def test_context_strategy_org_scoped_endpoints_have_no_mcp_tools():
    """Org-scoped Strategy/Future State/Guiding Principle approve/activate/
    retire endpoints (`router.py`) are deliberately not declared as MCP
    tools at all — `require_ai_approvals_enabled` needs a `Project` to
    check, which an org-scoped artefact has none of (see `module.py`'s own
    docstring). Every declared tool's `path_template` uses the
    `{project_id}`-based project router prefix, never the org one."""
    by_name = _by_local_name()
    assert all(t.path_template.startswith("/api/v1/projects/{project_id}/") for t in by_name.values())
