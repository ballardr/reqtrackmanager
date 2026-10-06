"""
Drift guard for the MCP agent skill's module-tool reference.

Module tools (and one tool per module `ReportDefinition`) appear in the MCP
server as a side effect of a module declaration, so nothing else would
prompt anyone to update the skill. These tests fail when the committed
`mcp_skill_reference/module-tools.md` no longer matches
`build_mcp_tool_manifest()`; fix by running
`python scripts/generate_mcp_module_tools_reference.py` (and see root
CLAUDE.md: a new or changed MCP tool updates `mcp-server/skill/` in the
same change). The core-tool counterpart lives in `mcp-server/tests/`.
"""

import sys
from pathlib import Path

from app.modules.registry import build_mcp_tool_manifest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import generate_mcp_module_tools_reference as gen  # noqa: E402


def test_module_tools_reference_is_up_to_date():
    assert gen.REFERENCE_PATH.exists(), "run python scripts/generate_mcp_module_tools_reference.py"
    assert gen.REFERENCE_PATH.read_text() == gen.render(), (
        "mcp_skill_reference/module-tools.md is stale: run python scripts/generate_mcp_module_tools_reference.py"
    )


def test_every_module_tool_is_in_the_reference():
    reference = gen.REFERENCE_PATH.read_text()
    missing = [t.name for t in build_mcp_tool_manifest() if f"`{t.name}`" not in reference]
    assert not missing, f"module tools missing from the skill reference: {missing}"


def test_every_module_with_tools_has_usage_guidance():
    """A module that contributes MCP tools must say how an agent should use them (`ModuleDefinition.mcp_guidance`)."""
    from app.modules.registry import get_module_registry

    prefixes = {t.name for t in build_mcp_tool_manifest()}
    for key, definition in get_module_registry().items():
        if any(name.startswith(f"{key}_") for name in prefixes):
            assert definition.mcp_guidance.strip(), f"module {key!r} has MCP tools but no mcp_guidance"


def test_guidance_appears_in_the_reference():
    from app.modules.registry import get_module_registry

    reference = gen.REFERENCE_PATH.read_text()
    for key, definition in get_module_registry().items():
        if definition.mcp_tools:
            assert definition.mcp_guidance.strip() in reference, f"{key!r} guidance missing from the reference"


def test_render_is_deterministic():
    assert gen.render() == gen.render()
