"""
Module: build_skill_zip

Builds the downloadable agent-skill artefacts for the documentation site from
`mcp-server/skill/reqtrack-mcp/` plus the backend's generated module-tool
reference:

- `reqtrack-mcp-skill.zip`: a Claude Code skill folder (`reqtrack-mcp/SKILL.md`
  and `references/{core,module}-tools.md`).
- `reqtrack-mcp-instructions.md`: the same guidance as one plain Markdown file
  for clients that do not load skills (Copilot instructions, generic clients).

Responsibilities:
- Stdlib only, so CI and developers can run it without the MCP server's
  dependencies (`python mcp-server/scripts/build_skill_zip.py [OUT_DIR]`).
- Deterministic output (fixed zip timestamps, sorted entries).

Design decisions:
- The outputs are built, never committed (`docs/website/static/downloads/` is
  gitignored), so a download cannot drift from the sources the drift tests
  guard. The docs CI job runs this before `npm run build`.
"""

from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_DIR = Path(__file__).resolve().parent.parent / "skill" / "reqtrack-mcp"  # also valid inside the mcp-server image, where REPO_ROOT is not
MODULE_REFERENCE = REPO_ROOT / "backend" / "mcp_skill_reference" / "module-tools.md"
DEFAULT_OUT_DIR = REPO_ROOT / "docs" / "website" / "static" / "downloads"
ZIP_NAME = "reqtrack-mcp-skill.zip"
INSTRUCTIONS_NAME = "reqtrack-mcp-instructions.md"
_FIXED_TIMESTAMP = (2026, 1, 1, 0, 0, 0)


def _skill_files(module_reference: Path) -> dict[str, bytes]:
    """Collects the skill's files keyed by their path inside the zip.

    Args:
        module_reference: The generated module-tools reference to bundle.

    Returns:
        Archive path to bytes, sorted by path.

    Raises:
        FileNotFoundError: If SKILL.md, core-tools.md or the module reference is missing.
    """
    sources = {
        "reqtrack-mcp/SKILL.md": SKILL_DIR / "SKILL.md",
        "reqtrack-mcp/references/core-tools.md": SKILL_DIR / "references" / "core-tools.md",
        "reqtrack-mcp/references/module-tools.md": module_reference,
    }
    return {name: path.read_bytes() for name, path in sorted(sources.items())}


def _plain_instructions(files: dict[str, bytes]) -> str:
    """Flattens the skill into a single Markdown document without frontmatter.

    Args:
        files: Output of `_skill_files`.

    Returns:
        SKILL.md's body followed by both references (demoted one heading level),
        with the `references/...` file mentions pointing at the sections instead.
    """
    body = re.sub(r"\A---\n.*?\n---\n", "", files["reqtrack-mcp/SKILL.md"].decode(), count=1, flags=re.DOTALL)
    body = body.replace("`references/core-tools.md`", "the Core tools section below")
    body = body.replace("`references/module-tools.md`", "the Module tools section below")

    def demote(markdown: str) -> str:
        return re.sub(r"^(#+) ", r"#\1 ", markdown, flags=re.MULTILINE).strip()

    core = demote(files["reqtrack-mcp/references/core-tools.md"].decode())
    module = demote(files["reqtrack-mcp/references/module-tools.md"].decode())
    return f"{body.strip()}\n\n{core}\n\n{module}\n"


def build(out_dir: Path = DEFAULT_OUT_DIR, module_reference: Path = MODULE_REFERENCE) -> list[Path]:
    """Writes the zip and the plain-Markdown variant.

    Args:
        out_dir: Destination directory (created if absent).
        module_reference: The generated module-tools reference to bundle.

    Returns:
        The paths written.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    files = _skill_files(module_reference)
    zip_path = out_dir / ZIP_NAME
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            info = zipfile.ZipInfo(name, date_time=_FIXED_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, data)
    instructions_path = out_dir / INSTRUCTIONS_NAME
    instructions_path.write_text(_plain_instructions(files))
    return [zip_path, instructions_path]


if __name__ == "__main__":
    for written in build(Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT_DIR):
        print(f"wrote {written}")
