"""Tests for the Project report name: the setting (set, clear, trim, limits, audit), the `{{project_report_name}}`
placeholder in a layout's text and in a file name (with its fallback to the project name, and `{{project_name}}`
unchanged), a run over a parent and its child, a clone and a bundle round trip. Each test builds its own organisation.
"""

from __future__ import annotations

import io
import re
from typing import Any

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.models.project import MAX_REPORT_NAME_LENGTH
from app.services.report_file_names import FILE_NAME_PLACEHOLDERS, ORG_FILE_NAME_PLACEHOLDERS, render_stem
from app.services.report_layout_tree import empty_tree, validate_tree
from tests.conftest import auth_headers
from tests.link_world import World

LONG_NAME = "The Very Long Programme Name Delivery Office Phase Two"


@pytest.fixture
def world(client, admin_token) -> World:
    return World(client, admin_token, "Report Name Org")


def patch(world: World, project: dict, body: dict[str, Any]):
    return world.client.patch(f"/api/v1/projects/{project['id']}", json=body, headers=auth_headers(world.token))


def get(world: World, project: dict) -> dict:
    resp = world.client.get(f"/api/v1/projects/{project['id']}", headers=auth_headers(world.token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def make_layout(world: World, project: dict, text: str, *, file_name: str | None = None) -> dict:
    tree: dict[str, Any] = {**empty_tree("document"), "nodes": [{"type": "heading", "text": text}]}
    if file_name is not None:
        tree["file_name"] = file_name
    resp = world.client.post(
        f"/api/v1/projects/{project['id']}/report-layouts",
        json={"name": "Layout", "description": "d", "family": "document", "tree": tree}, headers=auth_headers(world.token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def run(world: World, project: dict, layout: dict, fmt: str = "html"):
    resp = world.client.get(
        f"/api/v1/projects/{project['id']}/custom-reports/{layout['id']}/run", params={"format": fmt},
        headers=auth_headers(world.token),
    )
    assert resp.status_code == 200, resp.text
    return resp


# ---- the setting ---------------------------------------------------------------------------------------------------


def test_a_new_project_has_no_report_name(world):
    assert world.project("Plain")["report_name"] is None


def test_a_report_name_can_be_set_trimmed_and_cleared(world):
    project = world.project(LONG_NAME)
    assert patch(world, project, {"report_name": "  Delivery Two  "}).json()["report_name"] == "Delivery Two"
    assert get(world, project)["report_name"] == "Delivery Two"
    assert patch(world, project, {"name": "Renamed"}).json()["report_name"] == "Delivery Two"  # absent: unchanged
    assert patch(world, project, {"report_name": "   "}).json()["report_name"] is None  # blank is stored as null
    patch(world, project, {"report_name": "Again"})
    assert patch(world, project, {"report_name": None}).json()["report_name"] is None


def test_a_report_name_can_be_given_at_creation(world):
    resp = world.client.post(
        "/api/v1/projects", json={"organization_id": world.org["id"], "name": "Created", "report_name": "Short"},
        headers=auth_headers(world.token),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["report_name"] == "Short"


@pytest.mark.parametrize("value", ["x" * (MAX_REPORT_NAME_LENGTH + 1), "two\nlines", "tab\there", "nul\x00"])
def test_an_over_long_or_control_character_report_name_is_refused(world, value):
    project = world.project("P")
    assert patch(world, project, {"report_name": value}).status_code == 422
    assert get(world, project)["report_name"] is None


def test_a_report_name_at_the_limit_is_accepted(world):
    project = world.project("P")
    assert patch(world, project, {"report_name": "x" * MAX_REPORT_NAME_LENGTH}).status_code == 200


def test_changing_the_report_name_is_audited_alone(world):
    project = world.project("Audited")
    patch(world, project, {"report_name": "Short"})
    patch(world, project, {"report_name": "Short"})  # unchanged: no second event
    patch(world, project, {"report_name": None})
    with SessionLocal() as db:
        events = db.scalars(
            select(AuditEvent).where(AuditEvent.action == "report_name_changed", AuditEvent.project_id == project["id"])
            .order_by(AuditEvent.created_at)
        ).all()
    assert [e.detail for e in events] == [{"from": None, "to": "Short"}, {"from": "Short", "to": None}]


def test_a_child_project_does_not_inherit_the_report_name(world):
    parent = world.project("Parent")
    patch(world, parent, {"report_name": "Par"})
    child = world.project("Child", parent=parent)
    assert get(world, child)["report_name"] is None


def test_a_project_requires_manage_rights_to_set_it(world, client):
    project = world.project("P")
    assert client.patch(f"/api/v1/projects/{project['id']}", json={"report_name": "X"}).status_code in (401, 403)


# ---- the placeholder -------------------------------------------------------------------------------------------------


def test_the_layout_check_accepts_the_new_placeholder_and_still_rejects_unknown_ones():
    ok = {**empty_tree("document"), "nodes": [{"type": "heading", "text": "{{project_report_name}}"}]}
    assert validate_tree(ok).ok
    bad = {**empty_tree("document"), "nodes": [{"type": "heading", "text": "{{project_short_name}}"}]}
    assert any("Unknown placeholder" in e.message for e in validate_tree(bad).errors)


def test_the_placeholder_prints_the_report_name_and_project_name_is_unchanged(world):
    project = world.project(LONG_NAME)
    patch(world, project, {"report_name": "Delivery Two"})
    layout = make_layout(world, project, "Short {{project_report_name}} long {{project_name}}")
    assert f"Short Delivery Two long {LONG_NAME}" in run(world, project, layout).text


def test_the_placeholder_falls_back_to_the_project_name(world):
    project = world.project("Plain Project")
    layout = make_layout(world, project, "[{{project_report_name}}] [{{project_name}}]")
    assert "[Plain Project] [Plain Project]" in run(world, project, layout).text


def test_a_run_over_a_parent_and_its_child_uses_the_runs_own_project(world):
    parent = world.project("Parent Programme")
    patch(world, parent, {"report_name": "Par"})
    child = world.project("Child Work", parent=parent)
    layout = make_layout(world, parent, "{{project_report_name}} / {{project_name}}")
    assert "Par / Parent Programme" in run(world, parent, layout).text
    child_layout = make_layout(world, child, "{{project_report_name}} / {{project_name}}")
    assert "Child Work / Child Work" in run(world, child, child_layout).text


def test_a_report_name_is_escaped_like_the_project_name(world):
    project = world.project("P")
    patch(world, project, {"report_name": "<b>&Co</b>"})
    layout = make_layout(world, project, "{{project_report_name}}")
    body = run(world, project, layout).text
    assert "<b>&Co</b>" not in body and "&lt;b&gt;&amp;Co&lt;/b&gt;" in body


# ---- file names ---------------------------------------------------------------------------------------------------


def test_file_name_templates_may_use_the_placeholder():
    assert "project_report_name" in FILE_NAME_PLACEHOLDERS and "project_report_name" in ORG_FILE_NAME_PLACEHOLDERS
    assert render_stem("{{project_report_name}}-{{report_title}}", {"project_report_name": "Par", "report_title": "R"}) == "Par-R"


def test_a_download_is_named_by_the_report_name_when_the_template_writes_it(world):
    project = world.project(LONG_NAME)
    layout = make_layout(world, project, "x", file_name="{{project_report_name}}-{{report_title}}")
    name = re.search(r'filename="([^"]*)"', run(world, project, layout, "pdf").headers["content-disposition"])
    assert name is not None and name.group(1).startswith("The Very Long") and "Delivery Two" not in name.group(1)
    patch(world, project, {"report_name": "Delivery Two"})
    name = re.search(r'filename="([^"]*)"', run(world, project, layout, "pdf").headers["content-disposition"])
    assert name is not None and name.group(1) == "Delivery Two-Layout.pdf"


def test_a_hostile_report_name_cannot_inject_a_file_name_or_header(world):
    project = world.project("P")
    patch(world, project, {"report_name": '../../etc/"x"'})
    layout = make_layout(world, project, "x", file_name="{{project_report_name}}")
    resp = run(world, project, layout, "pdf")
    disposition = resp.headers["content-disposition"]
    assert "/" not in disposition.split("filename=")[1] and "\r" not in disposition and "\n" not in disposition


# ---- a copy and a bundle ---------------------------------------------------------------------------------------------


def test_the_bundle_round_trips_the_report_name(world):
    project = world.project("Source")
    patch(world, project, {"report_name": "Src"})
    export = world.client.get(f"/api/v1/projects/{project['id']}/export", headers=auth_headers(world.token))
    assert export.status_code == 200
    imported = world.client.post(
        "/api/v1/projects/import", data={"organization_id": world.org["id"], "name": "Copy"},
        files={"file": ("bundle.zip", io.BytesIO(export.content), "application/zip")}, headers=auth_headers(world.token),
    )
    assert imported.status_code == 201, imported.text
    assert imported.json()["project"]["report_name"] == "Src"


def test_a_bundle_without_the_key_imports_with_no_report_name(world):
    project = world.project("Source")
    export = world.client.get(f"/api/v1/projects/{project['id']}/export", headers=auth_headers(world.token))
    imported = world.client.post(
        "/api/v1/projects/import", data={"organization_id": world.org["id"], "name": "Copy"},
        files={"file": ("bundle.zip", io.BytesIO(export.content), "application/zip")}, headers=auth_headers(world.token),
    )
    assert imported.json()["project"]["report_name"] is None


def test_a_template_clone_does_not_copy_the_template_report_name(world):
    template = world.project("Template")
    patch(world, template, {"is_template": True, "report_name": "Tpl"})
    resp = world.client.post(
        "/api/v1/projects",
        json={"organization_id": world.org["id"], "name": "From template", "template_project_id": template["id"]},
        headers=auth_headers(world.token),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["report_name"] is None
