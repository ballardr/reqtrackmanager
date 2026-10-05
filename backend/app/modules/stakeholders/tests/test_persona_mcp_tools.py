"""Tests for the Stakeholders & Personas module's MCP tools (Personas,
Stakeholders and Stakeholder Needs): against the
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
        "list_stakeholders", "get_stakeholder", "create_stakeholder", "update_stakeholder", "activate_stakeholder",
        "retire_stakeholder", "list_stakeholder_needs", "get_stakeholder_need", "create_stakeholder_need",
        "update_stakeholder_need", "activate_stakeholder_need", "retire_stakeholder_need",
    }


def test_read_tools_are_non_mutating_and_write_tools_mutate():
    tools = _tools()
    for name in ("list_personas", "get_persona", "list_stakeholders", "get_stakeholder", "list_stakeholder_needs",
                 "get_stakeholder_need"):
        assert tools[name].method == "GET" and tools[name].mutates is False
    for name in (
        "create_persona", "update_persona", "activate_persona", "retire_persona", "create_stakeholder",
        "update_stakeholder", "activate_stakeholder", "retire_stakeholder", "create_stakeholder_need",
        "update_stakeholder_need", "activate_stakeholder_need", "retire_stakeholder_need",
    ):
        assert tools[name].mutates is True


def test_create_requires_name():
    for tool in ("create_persona", "create_stakeholder", "create_stakeholder_need"):
        params = {p["name"]: p for p in _tools()[tool].params}
        assert params["name"]["required"] is True and params["project_id"]["required"] is True


def test_no_tool_can_erase_a_stakeholder():
    """Irreversible deletion of personal data stays a human action in the UI."""
    assert not any("delete" in name or "erase" in name for name in _tools())
