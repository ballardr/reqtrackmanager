"""
Tests for the agent skill (`skill/reqtrack-mcp/`) and its build/drift tooling.

These guard that the skill cannot silently rot: every core tool the server
registers must be named in the hand-written SKILL.md, and the generated
`references/core-tools.md` must match the live tool list. Module tools are
checked on the backend side (`backend/tests/test_mcp_skill_reference.py`),
because only the backend can build the module manifest. If a test here
fails, regenerate with `python scripts/generate_skill_reference.py` and update
SKILL.md's workflow guidance for the new/changed tool (root CLAUDE.md:
a new or changed MCP tool updates `mcp-server/skill/` in the same change).

No running backend is needed.
"""

from __future__ import annotations

import importlib.util
import re
import zipfile
from pathlib import Path

import pytest

SERVER_DIR = Path(__file__).resolve().parent.parent
SKILL_MD = SERVER_DIR / "skill" / "reqtrack-mcp" / "SKILL.md"


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, SERVER_DIR / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def reference_script():
    return _load_script("generate_skill_reference")


@pytest.fixture(scope="module")
def core_tools(reference_script):
    return reference_script.collect()


def test_core_tools_reference_is_up_to_date(reference_script, core_tools):
    assert reference_script.REFERENCE_PATH.read_text() == reference_script.render(core_tools), (
        "skill/reqtrack-mcp/references/core-tools.md is stale: run python scripts/generate_skill_reference.py"
    )


def test_every_core_tool_is_named_in_skill_md(core_tools):
    text = SKILL_MD.read_text()
    missing = [t["name"] for t in core_tools if f"`{t['name']}`" not in text]
    assert not missing, f"core tools not mentioned in SKILL.md (add workflow guidance): {missing}"


def test_skill_md_names_no_removed_core_tool(core_tools):
    """A tool removed or renamed must not linger in SKILL.md."""
    known = {t["name"] for t in core_tools}
    text = SKILL_MD.read_text()
    # Backticked names starting with a core verb; module tools (`<module_key>_...`) and `get_artefact_link_graph` are exempt.
    candidates = set(re.findall(r"`((?:list|get|create|update|approve|decide|complete)_[a-z_]+)`", text))
    unknown = {c for c in candidates if c not in known and c != "get_artefact_link_graph"}
    assert not unknown, f"SKILL.md names tools that no longer exist: {sorted(unknown)}"


def test_core_tool_kinds(core_tools):
    kinds = {t["name"]: t["kind"] for t in core_tools}
    assert kinds["list_requirements"] == "read"
    assert kinds["create_requirement"] == "write"
    assert kinds["approve_requirement"] == "approval"
    assert sum(k == "approval" for k in kinds.values()) == 3


def test_skill_frontmatter_is_valid():
    match = re.match(r"---\n(.*?)\n---\n", SKILL_MD.read_text(), re.DOTALL)
    assert match, "SKILL.md must start with YAML frontmatter"
    fields = dict(line.split(": ", 1) for line in match.group(1).splitlines())
    assert fields["name"] == SKILL_MD.parent.name
    assert fields["description"].strip()
    assert len(fields["description"]) <= 1024


def test_build_skill_zip_contains_skill_and_both_references(tmp_path):
    builder = _load_script("build_skill_zip")
    module_reference = tmp_path / "module-tools.md"
    module_reference.write_text("# Module tools\n\n## Example (`example`)\n")
    zip_path, instructions_path = builder.build(tmp_path / "out", module_reference)

    with zipfile.ZipFile(zip_path) as archive:
        assert set(archive.namelist()) == {
            "reqtrack-mcp/SKILL.md",
            "reqtrack-mcp/references/core-tools.md",
            "reqtrack-mcp/references/module-tools.md",
        }
        assert archive.read("reqtrack-mcp/SKILL.md").startswith(b"---\nname: reqtrack-mcp\n")

    plain = instructions_path.read_text()
    assert not plain.startswith("---"), "plain variant must not carry skill frontmatter"
    assert "references/" not in plain.split("## Core tools")[0], "plain variant must not point at files it does not ship"
    assert "## Core tools" in plain and "## Module tools" in plain


def test_build_skill_zip_is_deterministic(tmp_path):
    builder = _load_script("build_skill_zip")
    module_reference = tmp_path / "module-tools.md"
    module_reference.write_text("# Module tools\n")
    first, _ = builder.build(tmp_path / "a", module_reference)
    second, _ = builder.build(tmp_path / "b", module_reference)
    assert first.read_bytes() == second.read_bytes()
