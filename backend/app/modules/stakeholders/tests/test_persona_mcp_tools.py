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
        # Phase 3 link tools.
        "list_relationship_kinds", "list_relationship_targets", "list_incoming_relationships",
        "list_stakeholder_relationships", "add_stakeholder_relationship", "remove_stakeholder_relationship",
        "list_persona_relationships", "add_persona_relationship", "remove_persona_relationship",
        "list_stakeholder_personas", "add_stakeholder_persona", "remove_stakeholder_persona",
        "list_need_holders", "add_need_holder", "remove_need_holder",
        "list_need_requirements", "add_need_requirement", "remove_need_requirement",
        # Phase 3b visibility tools.
        "set_stakeholder_visibility", "reset_stakeholder_visibility",
    }


def test_read_tools_are_non_mutating_and_write_tools_mutate():
    tools = _tools()
    for name in ("list_personas", "get_persona", "list_stakeholders", "get_stakeholder", "list_stakeholder_needs",
                 "get_stakeholder_need", "list_relationship_kinds", "list_relationship_targets",
                 "list_incoming_relationships", "list_stakeholder_relationships", "list_persona_relationships",
                 "list_stakeholder_personas", "list_need_holders", "list_need_requirements"):
        assert tools[name].method == "GET" and tools[name].mutates is False
    for name in (
        "create_persona", "update_persona", "activate_persona", "retire_persona", "create_stakeholder",
        "update_stakeholder", "activate_stakeholder", "retire_stakeholder", "create_stakeholder_need",
        "update_stakeholder_need", "activate_stakeholder_need", "retire_stakeholder_need",
        "add_stakeholder_relationship", "remove_stakeholder_relationship", "add_persona_relationship",
        "remove_persona_relationship", "add_stakeholder_persona", "remove_stakeholder_persona", "add_need_holder",
        "remove_need_holder", "add_need_requirement", "remove_need_requirement", "set_stakeholder_visibility",
        "reset_stakeholder_visibility",
    ):
        assert tools[name].mutates is True


def test_create_requires_name():
    for tool in ("create_persona", "create_stakeholder", "create_stakeholder_need"):
        params = {p["name"]: p for p in _tools()[tool].params}
        assert params["name"]["required"] is True and params["project_id"]["required"] is True


def test_remove_tools_delete_only_a_link():
    """Every `remove_*` tool is a DELETE of a link path, never of a record."""
    tools = _tools()
    for name in [n for n in tools if n.startswith("remove_")]:
        assert tools[name].method == "DELETE"
        assert any(part in tools[name].path_template for part in ("/relationships/", "/personas/", "/holders/", "/requirements/"))


def test_no_tool_can_erase_a_stakeholder():
    """Irreversible deletion of personal data stays a human action in the UI."""
    assert not any("delete" in name or "erase" in name for name in _tools())
