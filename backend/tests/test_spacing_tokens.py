"""
Pins scripts/check_spacing_tokens.py: spacing and radius values that sit on the named scale in
`frontend/src/styles/theme.css` are written as the token, in the stylesheet and in inline React styles, so
the scale can change in one place (docs/ux-style-guide.md, "Tokens").

Skipped when the repository root is not visible (the backend container mounts only backend/); the script can
be run directly from the repository root.
"""

import importlib.util
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_spacing_tokens.py"


def _load_checker():
    """Imports the checker script as a module; returns None if unavailable."""
    if not SCRIPT.is_file():
        return None
    try:
        subprocess.run(["git", "rev-parse"], cwd=SCRIPT.parent, check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    spec = importlib.util.spec_from_file_location("check_spacing_tokens", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


checker = _load_checker()
pytestmark = pytest.mark.skipif(checker is None or not checker.SRC.is_dir(), reason="frontend sources not available")


def test_no_spacing_or_radius_literal_has_a_token_left_unused():
    """The baseline is empty: every value on the scale is written as its token."""
    assert checker.violations() == []


def test_theme_declares_every_token_the_checker_maps_to():
    """A literal is only ever redirected to a token that exists in theme.css."""
    theme = (checker.SRC / "styles" / "theme.css").read_text(encoding="utf-8")
    for token in set(checker.SPACE.values()) | set(checker.RADIUS.values()):
        assert f"{token}:" in theme, token


def test_a_literal_on_the_scale_is_flagged_and_a_between_step_value_is_not(tmp_path, monkeypatch):
    """Flags `0.5rem` and `6px` in css and tsx; leaves `0.6rem`, `calc()`, tokens and custom properties alone."""
    (tmp_path / "a.css").write_text(
        ".a {\n  padding: 0.5rem 0.6rem;\n  border-radius: 6px;\n}\n"
        ".b {\n  gap: var(--space-3);\n  margin: calc(1rem + 2px);\n}\n"
        ":root {\n  --space-3: 0.5rem;\n}\n",
        encoding="utf-8",
    )
    (tmp_path / "b.tsx").write_text(
        'const s = { gap: "0.25rem", padding: "0.3rem 0", borderRadius: 4, marginTop: "var(--space-1)" };\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(checker, "SRC", tmp_path)
    assert checker.violations() == [
        "a.css:2: 0.5rem -> var(--space-3)",
        "a.css:3: 6px -> var(--radius-md)",
        "b.tsx:1: 0.25rem -> var(--space-1)",
        "b.tsx:1: 4px -> var(--radius-sm)",
    ]
