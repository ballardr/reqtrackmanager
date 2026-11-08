"""Tests that the demo seed gives the Business Requirements Document its substance: the requirement statements, the bundled
pictures and the evidence section print a link, a picture and an equation, and the seed's own data stays consistent.
"""

from __future__ import annotations

import io
import sys
import uuid
from pathlib import Path

import pytest
from PIL import Image as PilImage

from app.services.report_layout_tree import assert_valid
from app.services.report_starters import BUSINESS_REQUIREMENTS
from app.services.report_svg import sanitize_svg
from tests.conftest import auth_headers
from tests.link_world import World

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import seed_demo_data  # noqa: E402


@pytest.fixture
def world(client, admin_token) -> World:
    return World(client, admin_token, "Demo BRD Org", context_strategy=True)


def test_every_demo_requirement_has_a_statement_and_no_statement_is_orphaned():
    names = {
        spec[0]
        for specs in (seed_demo_data.DRONE_REQUIREMENTS, seed_demo_data.CLOUD_REQUIREMENTS, seed_demo_data.AVIONICS_REQUIREMENTS)
        for spec in specs
    }
    assert names == set(seed_demo_data.REQUIREMENT_DESCRIPTIONS)


def test_the_demo_statements_carry_equations_that_close_their_delimiters():
    equations = [text for text in seed_demo_data.REQUIREMENT_DESCRIPTIONS.values() if "\\(" in text]
    assert len(equations) >= 4
    assert all(text.count("\\(") == text.count("\\)") for text in equations)


def test_the_bundled_pictures_are_real_pictures_a_report_can_print():
    for picture, expected in ((seed_demo_data.TRIAL_SITE_PICTURE, "PNG"), (seed_demo_data.BENCH_RIG_PICTURE, "JPEG")):
        source, _name, _content_type = picture
        assert PilImage.open(io.BytesIO(source.read_bytes())).format == expected
    source, _name, _content_type = seed_demo_data.ARCHITECTURE_DIAGRAM
    assert "<svg" in sanitize_svg(source.read_text(encoding="utf-8"))


def test_the_illustrated_document_keeps_the_starter_and_is_a_valid_layout():
    starter = BUSINESS_REQUIREMENTS.tree
    tree = seed_demo_data.illustrated_brd_tree(starter)
    assert tree["nodes"][: len(starter["nodes"])] == starter["nodes"]
    assert len(tree["nodes"]) > len(starter["nodes"])
    assert_valid(tree)


def test_the_demo_document_prints_a_link_a_picture_a_diagram_and_an_equation(world):
    project = world.project("Demo")
    h = auth_headers(world.token)
    statement = seed_demo_data.REQUIREMENT_DESCRIPTIONS["Provide a minimum flight time of 42 minutes at an 800g payload"]
    created = world.client.post(
        f"/api/v1/projects/{project['id']}/requirements",
        json={
            "name": "Hover for the stated time", "description": statement,
            "component_id": project["component_id"], "category_id": project["category_id"],
        },
        headers=h,
    )
    assert created.status_code == 201, created.text
    requirement = created.json()
    pain_point = world.pain_point(project, "Pilots cannot tell which controller is in command")
    for source, filename, content_type in (seed_demo_data.TRIAL_SITE_PICTURE, seed_demo_data.ARCHITECTURE_DIAGRAM):
        resp = world.client.post(
            f"/api/v1/projects/{project['id']}/modules/context_strategy/pain-points/{pain_point}/files",
            files={"file": (filename, source.read_bytes(), content_type)}, headers=h,
        )
        assert resp.status_code == 201, resp.text
    motivates = world.link_types_by_name()["Motivates"]["id"]
    world.generic_link(project, ("pain_point", pain_point), motivates, ("requirement", uuid.UUID(requirement["id"])))

    tree = seed_demo_data.illustrated_brd_tree(BUSINESS_REQUIREMENTS.tree)
    resp = world.client.post(f"/api/v1/projects/{project['id']}/report-layouts/preview", json={"tree": tree}, headers=h)
    assert resp.status_code == 200, resp.text
    html = resp.json()["html"]

    assert 'class="math"' in html, "the requirement statement's equation is typeset"
    assert "<figcaption>Figure 1: bvlos-trial-site.png</figcaption>" in html, "the picture is printed with a numbered caption"
    assert "<figcaption>Figure 2: flight-controller-architecture.svg</figcaption>" in html, "the diagram is printed too"
    evidence = html[html.index("Evidence and traceability"):]
    assert requirement["unique_code"] in evidence[evidence.index("Pilots cannot tell"):], "the linked requirement is listed under the Pain Point"
