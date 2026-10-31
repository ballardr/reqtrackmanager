"""Tests for the starter report layouts (`services.report_starters`): every starter is a valid document layout, a new
organisation gets them, they can be added again without overwriting an edit, they need the manage permission, and
each one runs in a project, with its module sections noted (not failing) where a module is off. Each test builds its
own organisation.
"""

from __future__ import annotations

import pytest

from app.models.report_layout import FAMILY_DOCUMENT
from app.modules.registry import get_module_registry, get_report_starter_sections
from app.services.report_layout_tree import validate_tree
from app.services.report_starters import STARTER_NOTE, STARTERS
from tests.conftest import auth_headers, create_org_user, login
from tests.link_world import World

STARTER_NAMES = ["Business Requirements Document", "Engineering Specification", "Review Package", "Requirements by Component"]


@pytest.fixture
def world(client, admin_token) -> World:
    return World(client, admin_token, "Starters Org", keep_starter_layouts=True)


def org_layouts(world: World, token: str | None = None) -> list[dict]:
    resp = world.client.get(f"/api/v1/orgs/{world.org['id']}/report-layouts", headers=auth_headers(token or world.token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def by_name(layouts: list[dict], name: str) -> dict:
    return next(layout for layout in layouts if layout["name"] == name)


def add_starters(world: World, token: str | None = None):
    return world.client.post(f"/api/v1/orgs/{world.org['id']}/report-layouts/starters", headers=auth_headers(token or world.token))


def test_every_starter_is_a_valid_document_layout_with_a_unique_name():
    assert [s.name for s in STARTERS] == STARTER_NAMES
    for starter in STARTERS:
        result = validate_tree(starter.tree, family=FAMILY_DOCUMENT)
        assert [(e.path, e.message) for e in result.errors] == [], starter.name
        assert starter.description


def test_every_module_section_names_a_real_starter_and_a_module_that_owns_it():
    keys = {starter.key for starter in STARTERS}
    contributed = [(module, section) for module, definition in get_module_registry().items() for section in definition.report_starter_sections]

    assert contributed, "modules contribute starter sections"
    assert {section.starter for _module, section in contributed} <= keys
    assert sum(len(get_report_starter_sections(key)) for key in keys) == len(contributed)
    for starter in STARTERS:
        wrapped = {block["when"]["module"] for block in starter.tree["nodes"] if block["type"] == "if"}
        assert wrapped == {module for module, section in contributed if section.starter == starter.key}


def test_a_new_organisation_starts_with_the_starter_layouts(world):
    layouts = org_layouts(world)

    assert sorted(layout["name"] for layout in layouts) == sorted(STARTER_NAMES)
    assert all(layout["family"] == FAMILY_DOCUMENT and layout["project_id"] is None for layout in layouts)


def test_a_starter_is_an_ordinary_editable_layout(world):
    layout = by_name(org_layouts(world), "Review Package")
    url = f"/api/v1/orgs/{world.org['id']}/report-layouts/{layout['id']}"

    detail = world.client.get(url, headers=auth_headers(world.token)).json()
    assert detail["current"]["comment"] == STARTER_NOTE
    assert detail["editable"] is True

    renamed = world.client.patch(url, json={"name": "Our review pack"}, headers=auth_headers(world.token))
    assert renamed.status_code == 200, renamed.text
    assert world.client.delete(url, headers=auth_headers(world.token)).status_code == 204


def test_adding_the_starters_again_adds_nothing_when_all_are_there(world):
    resp = add_starters(world)

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"added": []}
    assert len(org_layouts(world)) == len(STARTER_NAMES)


def test_adding_the_starters_restores_a_deleted_one_and_leaves_an_edited_one_alone(world):
    base = f"/api/v1/orgs/{world.org['id']}/report-layouts"
    layouts = org_layouts(world)
    gone, kept = by_name(layouts, "Review Package"), by_name(layouts, "Engineering Specification")
    assert world.client.delete(f"{base}/{gone['id']}", headers=auth_headers(world.token)).status_code == 204
    detail = world.client.get(f"{base}/{kept['id']}", headers=auth_headers(world.token)).json()
    edited_tree = {**detail["current"]["tree"], "orientation": "portrait"}
    saved = world.client.put(
        f"{base}/{kept['id']}/tree", json={"tree": edited_tree, "base_version": detail["current_version"], "comment": "ours"},
        headers=auth_headers(world.token),
    )
    assert saved.status_code == 200, saved.text

    resp = add_starters(world)

    assert resp.json() == {"added": ["Review Package"]}
    again = world.client.get(f"{base}/{kept['id']}", headers=auth_headers(world.token)).json()
    assert again["current_version"] == detail["current_version"] + 1
    assert again["current"]["tree"]["orientation"] == "portrait"


def test_a_starter_name_an_organisation_already_uses_is_skipped(world):
    base = f"/api/v1/orgs/{world.org['id']}/report-layouts"
    layout = by_name(org_layouts(world), "Business Requirements Document")
    world.client.patch(f"{base}/{layout['id']}", json={"name": "BRD (ours)"}, headers=auth_headers(world.token))
    own = world.client.post(
        base, json={"name": "Review Package", "description": "", "family": "document", "tree": STARTERS[2].tree},
        headers=auth_headers(world.token),
    )
    assert own.status_code == 409, own.text  # the starter holds the name already

    assert add_starters(world).json() == {"added": ["Business Requirements Document"]}


def missing_starters(world: World, token: str | None = None):
    return world.client.get(f"/api/v1/orgs/{world.org['id']}/report-layouts/starters", headers=auth_headers(token or world.token))


def test_the_missing_starters_are_listed_so_the_ui_offers_adding_only_when_one_is_missing(world):
    base = f"/api/v1/orgs/{world.org['id']}/report-layouts"
    assert missing_starters(world).json() == {"missing": []}

    gone = by_name(org_layouts(world), "Review Package")
    assert world.client.delete(f"{base}/{gone['id']}", headers=auth_headers(world.token)).status_code == 204
    assert missing_starters(world).json() == {"missing": ["Review Package"]}

    assert add_starters(world).json() == {"added": ["Review Package"]}
    assert missing_starters(world).json() == {"missing": []}


def test_listing_the_missing_starters_needs_the_manage_permission(world):
    email = "plain-member-missing@example.com"
    create_org_user(world.client, world.token, world.org["id"], email)
    member = login(world.client, email, "Password123!")

    assert missing_starters(world, member).status_code == 403


def test_adding_the_starters_needs_the_manage_permission(world):
    email = "plain-member@example.com"
    create_org_user(world.client, world.token, world.org["id"], email)
    member = login(world.client, email, "Password123!")

    assert add_starters(world, member).status_code == 403


def run_starter(world: World, project: dict, name: str, fmt: str | None = None):
    layout = by_name(org_layouts(world), name)
    url = f"/api/v1/projects/{project['id']}/custom-reports/{layout['id']}/run"
    return world.client.get(url, params={"format": fmt} if fmt else {}, headers=auth_headers(world.token))


@pytest.mark.parametrize("name", STARTER_NAMES)
def test_each_starter_runs_in_a_project_with_every_module_on(client, admin_token, name):
    world = World(client, admin_token, "Starter Run", decisions=True, context_strategy=True, keep_starter_layouts=True)
    world.enable("risk_management")
    world.enable("stakeholders")
    project = world.project("Full")
    world.requirement(project, "The system shall log in users")
    world.pain_point(project, "Slow sign in")
    world.decision(project)

    resp = run_starter(world, project, name)

    assert resp.status_code == 200, resp.text
    report = resp.json()
    assert report["title"] == name
    assert report["sections"]


def test_the_business_requirements_document_lists_what_the_project_holds(client, admin_token):
    world = World(client, admin_token, "Starter Content", decisions=True, context_strategy=True, keep_starter_layouts=True)
    project = world.project("Content")
    world.requirement(project, "The system shall log in users")
    world.pain_point(project, "Slow sign in")

    html = run_starter(world, project, "Business Requirements Document", "html")

    assert html.status_code == 200, html.text
    assert "Slow sign in" in html.text
    assert "The system shall log in users" in html.text
    assert "Business Requirements Document" in html.text


def test_requirements_by_component_prints_each_requirement_under_its_component_and_category(world):
    project = world.project("By component")
    world.requirement(project, "The system shall log in users")

    html = run_starter(world, project, "Requirements by Component", "html").text

    assert "The system shall log in users" in html
    assert "<h2" in html and "<h3" in html  # a component heading with a category heading under it
    assert "Introduction" in html and "Appendices" in html
    for column in ("ID", "Name", "Reasoning", "Status", "Tags"):
        assert f">{column}<" in html, column


def test_a_part_whose_module_is_off_is_left_out_rather_than_printed_empty(world):
    project = world.project("Bare")
    world.requirement(project, "The system shall log in users")

    html = run_starter(world, project, "Business Requirements Document", "html").text

    assert "The system shall log in users" in html
    for left_out in ("Pain Point", "Stakeholder", "Risks and business impacts", "Key decisions", "Open Questions", "not available"):
        assert left_out not in html, left_out


def test_a_part_comes_back_in_a_project_where_its_module_is_on(client, admin_token):
    world = World(client, admin_token, "Starter Modules", decisions=True, keep_starter_layouts=True)
    project = world.project("With decisions")

    html = run_starter(world, project, "Business Requirements Document", "html").text

    assert "Key decisions" in html and "No decisions recorded." in html
    assert "Risks and business impacts" not in html


@pytest.mark.parametrize("name", STARTER_NAMES)
def test_a_starter_runs_as_pdf_and_word(world, name):
    project = world.project("Files")
    world.requirement(project)

    assert run_starter(world, project, name, "pdf").status_code == 200
    assert run_starter(world, project, name, "docx").status_code == 200


@pytest.mark.parametrize("name", STARTER_NAMES)
def test_a_starter_still_runs_where_a_module_is_off(world, name):
    project = world.project("Bare")
    world.requirement(project)

    resp = run_starter(world, project, name)

    assert resp.status_code == 200, resp.text

