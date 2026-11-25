"""
Pins scripts/check_grid_long_text.py: grid and table code never lets long user text decide the layout (docs/ux-style-guide.md,
"Pattern: long text in a grid or table"). The script sees only the shapes a script can see; the Storybook `LongText` stories
and `frontend/src/testing/gridStability.ts` measure the real layout.

Skipped when the repository root is not visible (the backend container mounts only backend/); the script can be run directly
from the repository root.
"""

import importlib.util
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_grid_long_text.py"


def _load_checker():
    """Imports the checker script as a module; returns None if unavailable."""
    if not SCRIPT.is_file():
        return None
    try:
        subprocess.run(["git", "rev-parse"], cwd=SCRIPT.parent, check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    spec = importlib.util.spec_from_file_location("check_grid_long_text", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


checker = _load_checker()
pytestmark = pytest.mark.skipif(checker is None or not checker.SRC.is_dir(), reason="frontend sources not available")


def _scan(tmp_path, name: str, source: str) -> list[str]:
    """Runs the checker over one temporary source file (in a directory of its own) and returns its findings."""
    root = tmp_path / f"scan{len(list(tmp_path.iterdir()))}"
    target = root / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source, encoding="utf-8")
    original = checker.SRC
    checker.SRC = root
    try:
        return checker.violations()
    finally:
        checker.SRC = original


def test_the_product_has_no_unexplained_content_sized_track_or_hand_built_ellipsis():
    """The product's own styles and components pass (the baseline is empty)."""
    assert checker.violations() == []


def test_a_track_sized_by_its_content_is_reported(tmp_path):
    """`max-content`, `min-content` and a bare `auto` in a grid column template are reported, in CSS and in a style prop."""
    css = _scan(tmp_path, "a.css", ".x {\n  display: grid;\n  grid-template-columns: max-content 1fr;\n}\n")
    assert len(css) == 1 and css[0].startswith("a.css:3")
    tsx = _scan(tmp_path, "B.tsx", 'export const B = () => <div style={{ gridTemplateColumns: "1fr auto" }} />;\n')
    assert len(tsx) == 1 and "sized by its content" in tsx[0]


def test_bounded_and_repeating_tracks_pass(tmp_path):
    """Fixed widths, `fr` shares, clamped `minmax` and `auto-fit`/`auto-fill` repeats are not content tracks; `overflow: auto`
    on the same line is not a track."""
    css = (
        ".x { grid-template-columns: repeat(auto-fill, minmax(10rem, 1fr)); overflow-y: auto; }\n"
        ".y { grid-template-columns: minmax(0, 2fr) 6rem; }\n"
    )
    assert _scan(tmp_path, "a.css", css) == []


def test_a_reasoned_marker_exempts_a_track(tmp_path):
    """A `grid-text-ok: <reason>` comment on the line or the line before exempts it; a marker with no reason does not."""
    exempt = "/* grid-text-ok: the last column holds only buttons */\n.x { grid-template-columns: 1fr max-content; }\n"
    assert _scan(tmp_path, "a.css", exempt) == []
    bare = "/* grid-text-ok: */\n.x { grid-template-columns: 1fr max-content; }\n"
    assert len(_scan(tmp_path, "a.css", bare)) == 1


def test_a_hand_built_ellipsis_is_reported_outside_cell_text(tmp_path):
    """`text-overflow: ellipsis` is reported anywhere but CellText, in CSS and in a style prop; a marker exempts it."""
    assert len(_scan(tmp_path, "a.css", ".x {\n  text-overflow: ellipsis;\n}\n")) == 1
    tsx = 'export const A = () => <span style={{ textOverflow: "ellipsis" }}>x</span>;\n'
    assert len(_scan(tmp_path, "A.tsx", tsx)) == 1
    marked = '// grid-text-ok: a select control label\nexport const A = () => <span style={{ textOverflow: "ellipsis" }}>x</span>;\n'
    assert _scan(tmp_path, "A.tsx", marked) == []


def test_render_extra_needs_a_declared_kind_or_cell_text(tmp_path):
    """A file that passes `renderExtra` without `extraContent="controls"` or `CellText` is reported; either one passes."""
    bare = "export const P = () => <DefinitionList renderExtra={(i) => <span>{i.summary}</span>} />;\n"
    assert len(_scan(tmp_path, "P.tsx", bare)) == 1
    controls = 'export const P = () => <DefinitionList extraContent="controls" renderExtra={(i) => <Toggle />} />;\n'
    assert _scan(tmp_path, "P.tsx", controls) == []
    text = "export const P = () => <DefinitionList renderExtra={(i) => <CellText>{i.summary}</CellText>} />;\n"
    assert _scan(tmp_path, "P.tsx", text) == []


def test_stories_and_testing_helpers_are_not_checked(tmp_path):
    """Stories and `testing/` build deliberately broken grids to prove the guard, so they are skipped."""
    assert _scan(tmp_path, "testing/x.ts", 'const g = { gridTemplateColumns: "max-content 1fr" };\n') == []
    assert _scan(tmp_path, "A.stories.tsx", 'const g = { gridTemplateColumns: "max-content 1fr" };\n') == []
