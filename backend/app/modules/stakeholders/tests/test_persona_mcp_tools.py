"""Tests for the Stakeholders & Personas module's MCP tools: against the
real registry, so a wrong path template or method (which
`build_mcp_tool_manifest` silently excludes) fails here rather than going
unnoticed. No approval-gated tool exists, so none is marked as one."""

from __future__ import annotations

from app.modules.registry import build_mcp_tool_manifest


def _tools() -> dict[str, object]:
    return {t.name.removeprefix("stakeholders_"): t for t in build_mcp_tool_manifest() if t.name.startswith("stakeholders_")}


def test_all_declared_tools_resolve():
    assert set(_tools()) == {
        "list_personas", "get_persona", "create_persona", "update_persona", "activate_persona", "retire_persona",
    }


def test_read_tools_are_non_mutating_and_write_tools_mutate():
    tools = _tools()
    for name in ("list_personas", "get_persona"):
        assert tools[name].method == "GET" and tools[name].mutates is False
    for name in ("create_persona", "update_persona", "activate_persona", "retire_persona"):
        assert tools[name].mutates is True


def test_create_requires_name():
    params = {p["name"]: p for p in _tools()["create_persona"].params}
    assert params["name"]["required"] is True and params["project_id"]["required"] is True
