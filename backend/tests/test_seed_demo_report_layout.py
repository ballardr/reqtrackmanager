"""Tests that the demo seed's logo report is a valid layout and its bundled logo is a picture the library accepts."""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest

from app.models.organization import Organization
from app.services.report_layout_tree import assert_valid
from app.services.report_svg import sanitize_svg
from tests.conftest import auth_headers
from tests.test_report_images import db, world  # noqa: F401 - the world and db fixtures
from tests.test_report_styles import create, pdf_fonts

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import seed_demo_data  # noqa: E402


def test_the_demo_logo_report_layout_is_valid_and_layers_the_logo_over_a_shape():
    tree = seed_demo_data.project_overview_with_logo_layout(str(uuid.uuid4()))
    assert_valid(tree, organization_colours=["alert", "success"])
    shape, image = tree["nodes"][:2]
    assert (shape["type"], shape["placement"], shape["fill"]) == ("shape", "behind", "plate")
    assert (image["type"], image["placement"]) == ("image", "front")


def test_the_bundled_demo_logo_is_white_on_transparent_and_accepted_as_a_report_picture():
    path = seed_demo_data.LOGO_PATH
    assert path.is_file()
    svg = path.read_text(encoding="utf-8")
    assert "fill:white" in svg
    assert "<svg" in sanitize_svg(svg)


def test_the_demo_logo_report_shows_its_own_colour_scheme_a_serif_body_sans_headings_and_an_italic_footer():
    tree = seed_demo_data.project_overview_with_logo_layout(str(uuid.uuid4()))
    assert {entry["name"] for entry in tree["palette"]} == {"plate", "highlight"}
    assert tree["styles"]["body"]["font"] == "serif" and tree["styles"]["headings"]["font"] == "sans"
    assert tree["styles"]["headings"]["colour"] == "plate"
    assert all(tree["footer"][cell].startswith("*") and tree["footer"][cell].endswith("*") for cell in ("left", "right"))


@pytest.mark.parametrize("fmt", ["html", "pdf", "docx", "odt"])
def test_the_demo_logo_report_runs_in_every_format_with_its_own_scheme_over_the_organisations(world, db, fmt):  # noqa: F811
    organization = db.get(Organization, uuid.UUID(world.org["id"]))
    organization.report_colour_scheme = [{"name": "alert", "colour": "#B42318"}, {"name": "success", "colour": "#067647"}]
    organization.report_accent_color_hex = "#336699"
    db.commit()
    tree = seed_demo_data.project_overview_with_logo_layout(str(uuid.uuid4()))
    tree["nodes"] = [node for node in tree["nodes"] if node["type"] != "image"]  # the picture needs a library file
    project = world.project("Demo")
    world.requirement(project, "The system shall log in users")
    layout = create(world, project, tree, "Demo overview")

    resp = world.client.get(
        f"/api/v1/projects/{project['id']}/custom-reports/{layout['id']}/run", params={"format": fmt}, headers=auth_headers(world.token),
    )

    assert resp.status_code == 200, resp.text
    if fmt == "html":
        assert 'font-family: "Times New Roman", serif' in resp.text  # the serif body
        assert "color: #264c73" in resp.text  # plate = accent_dark: 25% of the way from #336699 to black
    elif fmt == "pdf":
        assert {"LiberationSerif", "LiberationSans-Bold"} <= pdf_fonts(resp.content)
