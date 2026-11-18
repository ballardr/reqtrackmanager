"""
Pins scripts/check_menu_rows.py: a menu row, a listbox option and a list of choices in a popover are text rows
(`menu-item`), never standard `btn` buttons (docs/ux-style-guide.md, "Pattern: action menu").

Skipped when the repository root is not visible (the backend container mounts only backend/); the script can be run directly
from the repository root.
"""

import importlib.util
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_menu_rows.py"


def _load_checker():
    """Imports the checker script as a module; returns None if unavailable."""
    if not SCRIPT.is_file():
        return None
    try:
        subprocess.run(["git", "rev-parse"], cwd=SCRIPT.parent, check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    spec = importlib.util.spec_from_file_location("check_menu_rows", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


checker = _load_checker()
pytestmark = pytest.mark.skipif(checker is None or not checker.SRC.is_dir(), reason="frontend sources not available")


def _scan(tmp_path, source: str) -> list[str]:
    """Runs the checker over one temporary `.tsx` file and returns its findings."""
    (tmp_path / "Sample.tsx").write_text(source, encoding="utf-8")
    original = checker.SRC
    checker.SRC = tmp_path
    try:
        return checker.violations()
    finally:
        checker.SRC = original


def test_no_menu_row_is_a_standard_button():
    """The product has no menu row drawn as a `btn` (the baseline is empty)."""
    assert checker.violations() == []


def test_a_menuitem_or_option_with_a_btn_class_fails(tmp_path):
    """A `role="menuitem"` or `role="option"` element that carries `btn` is reported."""
    source = (
        "export const A = () => (\n"
        "  <div>\n"
        "    <button\n"
        '      role="option"\n'
        '      className="btn"\n'
        "      onClick={pick}\n"
        "    >\n"
        "      Pick\n"
        "    </button>\n"
        "  </div>\n"
        ");\n"
    )
    assert len(_scan(tmp_path, source)) == 1


def test_menu_item_combined_with_btn_fails(tmp_path):
    """A row that mixes `menu-item` and `btn` is still a bordered button."""
    source = 'export const A = () => <button className="btn menu-item">Go</button>;\n'
    assert len(_scan(tmp_path, source)) == 1


def test_a_stack_of_btn_rows_in_a_popover_fails(tmp_path):
    """A `btn` repeated by `.map(` inside a `Popover` is a list of choices drawn as buttons."""
    source = (
        "export const A = () => (\n"
        "  <>\n"
        "    <Popover anchorRef={ref} title=\"Pick\" onClose={close}>\n"
        "      <div className=\"stack\">\n"
        "        {choices.map((c) => (\n"
        "          <button key={c} type=\"button\" className=\"btn\" onClick={() => pick(c)}>\n"
        "            {c}\n"
        "          </button>\n"
        "        ))}\n"
        "      </div>\n"
        "    </Popover>\n"
        "  </>\n"
        ");\n"
    )
    assert len(_scan(tmp_path, source)) == 1


def test_single_buttons_and_text_rows_pass(tmp_path):
    """A Save button in a popover, a `menu-item` row and a `btn` outside any popover are not reported."""
    source = (
        "export const A = () => (\n"
        "  <>\n"
        '    <button className="btn">Outside</button>\n'
        "    <Popover anchorRef={ref} title=\"Pick\" onClose={close}>\n"
        "      <div className=\"menu-list\">\n"
        "        {choices.map((c) => (\n"
        "          <button key={c} type=\"button\" className=\"menu-item\" onClick={() => pick(c)}>{c}</button>\n"
        "        ))}\n"
        "      </div>\n"
        "      <button type=\"button\" className=\"btn btn-primary\" onClick={save}>Save</button>\n"
        "    </Popover>\n"
        "  </>\n"
        ");\n"
    )
    assert _scan(tmp_path, source) == []


def test_exempt_row_with_a_reason_passes(tmp_path):
    """A row that carries `data-menu-row-ok` is skipped."""
    source = (
        "export const A = () => (\n"
        '  <button role="option" className="btn" data-menu-row-ok="its own control">Go</button>\n'
        ");\n"
    )
    assert _scan(tmp_path, source) == []
