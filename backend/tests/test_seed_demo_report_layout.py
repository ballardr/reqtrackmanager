"""Tests that the demo seed's logo report is a valid layout and its bundled logo is a picture the library accepts."""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

from app.services.report_layout_tree import assert_valid
from app.services.report_svg import sanitize_svg

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import seed_demo_data  # noqa: E402


def test_the_demo_logo_report_layout_is_valid_and_layers_the_logo_over_a_shape():
    tree = seed_demo_data.project_overview_with_logo_layout(str(uuid.uuid4()))
    assert_valid(tree)
    shape, image = tree["nodes"][:2]
    assert (shape["type"], shape["placement"], shape["fill"]) == ("shape", "behind", "accent")
    assert (image["type"], image["placement"]) == ("image", "front")


def test_the_bundled_demo_logo_is_white_on_transparent_and_accepted_as_a_report_picture():
    path = seed_demo_data.LOGO_PATH
    assert path.is_file()
    svg = path.read_text(encoding="utf-8")
    assert "fill:white" in svg
    assert "<svg" in sanitize_svg(svg)
