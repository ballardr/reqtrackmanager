"""Tests for the Project Workbook starter (`services.report_starters.workbook_tree`): every reportable record type has a
core-detail sheet generated from the report field registry, a module's sheets appear only where the module is on, a type a
new module registers gets a sheet with no edit to the starter, and the workbook downloads as XLSX and ODS. Each test builds
its own organisation.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import replace

import openpyxl
import pytest

from app.models.report_layout import FAMILY_TABLE
from app.modules.registry import artefact_type_module, get_report_field_providers
from app.services import report_starters
from app.services.report_fields import RESERVED_FIELD_KEYS, core_field_keys, validate_provider
from app.services.report_layout_tree import validate_tree
from app.services.report_starters import workbook_tree
from tests.conftest import auth_headers
from tests.link_world import World

NAME = "Project Workbook"


@pytest.fixture
def world(client, admin_token) -> World:
    return World(client, admin_token, "Workbook Org", keep_starter_layouts=True)


def sheets_of(tree: dict) -> list[dict]:
    """Every sheet block of a workbook tree, wrapped in a module test or not."""
    return [s for node in tree["nodes"] for s in (node["children"] if node["type"] == "if" else [node])]


def run_workbook(world: World, project: dict, fmt: str):
    layouts = world.client.get(f"/api/v1/orgs/{world.org['id']}/report-layouts", headers=auth_headers(world.token)).json()
    layout = next(layout for layout in layouts if layout["name"] == NAME)
    return world.client.get(
        f"/api/v1/projects/{project['id']}/custom-reports/{layout['id']}/run", params={"format": fmt}, headers=auth_headers(world.token),
    )


def test_every_reportable_type_marks_a_core_field_beyond_the_reserved_ones():
    for artefact_type, provider in get_report_field_providers().items():
        keys = core_field_keys(artefact_type)
        assert keys[: len(RESERVED_FIELD_KEYS)] == list(RESERVED_FIELD_KEYS), artefact_type
        assert [f.key for f in provider.fields if f.core], f"{artefact_type} marks no core field"
        assert validate_provider(artefact_type, provider) == []


def test_the_workbook_is_a_valid_table_layout_with_a_contents_sheet():
    tree = workbook_tree()

    assert tree["family"] == FAMILY_TABLE and tree["contents_sheet"] is True
    assert [(e.path, e.message) for e in validate_tree(tree, family=FAMILY_TABLE).errors] == []


def test_each_reportable_type_has_one_sheet_of_its_core_fields_with_a_unique_short_name():
    sheets = sheets_of(workbook_tree())

    assert [s["source"]["record_type"] for s in sheets] == list(get_report_field_providers())
    assert len({s["name"].casefold() for s in sheets}) == len(sheets) and all(len(s["name"]) <= 31 for s in sheets)
    for sheet in sheets:
        assert [c["field"] for c in sheet["columns"]] == core_field_keys(sheet["source"]["record_type"])


def test_a_modules_sheets_are_wrapped_in_a_test_on_that_module_and_core_ones_are_not():
    for node in workbook_tree()["nodes"]:
        record_type = (node["children"][0] if node["type"] == "if" else node)["source"]["record_type"]
        owner = artefact_type_module(record_type)
        if owner is None:
            assert node["type"] == "sheet", record_type
        else:
            assert node["type"] == "if" and node["when"] == {"module": owner.key}, record_type


def test_a_type_a_new_module_registers_gets_a_sheet_without_editing_the_starter(monkeypatch):
    providers = dict(get_report_field_providers())
    providers["widget_thing"] = replace(
        providers["requirement"], fields=tuple(replace(f, core=f.key == "description") for f in providers["requirement"].fields),
    )
    monkeypatch.setattr(report_starters, "get_report_field_providers", lambda: providers)
    monkeypatch.setattr("app.services.report_fields.get_report_field_providers", lambda: providers)

    sheet = next(s for s in sheets_of(workbook_tree()) if s["source"]["record_type"] == "widget_thing")

    assert sheet["name"] == "Widget thing"
    assert [c["field"] for c in sheet["columns"]] == ["code", "title", "status", "tags", "description"]


def test_a_new_organisation_gets_the_workbook_as_an_ordinary_table_layout(world):
    layouts = world.client.get(f"/api/v1/orgs/{world.org['id']}/report-layouts", headers=auth_headers(world.token)).json()
    layout = next(layout for layout in layouts if layout["name"] == NAME)

    assert layout["family"] == FAMILY_TABLE and layout["project_id"] is None


def test_the_workbook_downloads_as_xlsx_with_a_sheet_for_each_type_whose_module_is_on(client, admin_token):
    world = World(client, admin_token, "Workbook Modules", decisions=True, keep_starter_layouts=True)
    project = world.project("Workbook")
    world.requirement(project, "The system shall log in users")
    world.decision(project)

    resp = run_workbook(world, project, "xlsx")

    assert resp.status_code == 200, resp.text
    workbook = openpyxl.load_workbook(io.BytesIO(resp.content))
    assert workbook.sheetnames[0] == "Contents"
    assert {"Requirement", "Decision"} <= set(workbook.sheetnames)
    assert "Risk" not in workbook.sheetnames and "Pain point" not in workbook.sheetnames  # modules that are off
    requirements = list(workbook["Requirement"].iter_rows(values_only=True))
    assert requirements[0][:4] == ("Code", "Title", "Status", "Tags") and requirements[0][-2:] == ("Description", "Owner")
    assert requirements[1][1] == "The system shall log in users" and requirements[1][0]
    decisions = list(workbook["Decision"].iter_rows(values_only=True))
    assert len(decisions) == 2 and decisions[0][4:] == ("Decision statement", "Owner")


def test_the_workbook_downloads_as_ods(world):
    project = world.project("Workbook ODS")
    world.requirement(project, "The system shall log in users")

    resp = run_workbook(world, project, "ods")

    assert resp.status_code == 200, resp.text
    content = zipfile.ZipFile(io.BytesIO(resp.content)).read("content.xml").decode()
    assert "The system shall log in users" in content and 'table:name="Requirement"' in content
