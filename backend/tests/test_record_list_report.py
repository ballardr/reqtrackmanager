"""Tests for the Record list report (`routers.record_list_report`, `services.record_list_report`): any record type
with a table is a report, with the list's own filters, the export's columns and access rule, tones in the Word and
PDF output, an audit event per file and a catalogue entry that offers only what the caller may run.

Each test builds its own organisation (`tests.link_world.World`), so none depends on state left by another test.
"""

from __future__ import annotations

import csv
import dataclasses
import io
import uuid
import zipfile

import openpyxl
import pytest

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.modules.registry import get_record_table_providers
from app.services import record_list_report, record_tables
from app.services.report_model import TONE_FILL
from tests.conftest import auth_headers, create_org_user, login
from tests.link_world import ACTION, REQ, World


@pytest.fixture
def world(client, admin_token) -> World:
    return World(client, admin_token, "Record List Org")


def _report(world: World, project: dict, record_type: str = REQ, token: str | None = None, **params):
    return world.client.get(
        f"/api/v1/projects/{project['id']}/reports/record-list", params={"record_type": record_type, **params},
        headers=auth_headers(token or world.token),
    )


def _catalogue(world: World, project: dict, token: str | None = None) -> list[dict]:
    resp = world.client.get(f"/api/v1/projects/{project['id']}/report-catalogue", headers=auth_headers(token or world.token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _audit(project: dict, action: str = "records_exported") -> list[AuditEvent]:
    db = SessionLocal()
    try:
        return list(db.query(AuditEvent).filter(AuditEvent.project_id == project["id"], AuditEvent.action == action).all())
    finally:
        db.close()


def _outsider(world: World) -> str:
    email = f"outsider-{uuid.uuid4().hex[:6]}@example.com"
    create_org_user(world.client, world.token, world.org["id"], email)
    return login(world.client, email, "Password123!")


# --- the report ---------------------------------------------------------------------------------------------------


def test_the_json_report_is_the_list_as_one_table_with_the_codes_first(world):
    project = world.project()
    world.requirement(project, "First")
    resp = _report(world, project)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["title"] == "Requirements" and body["scope_label"] == project["name"]
    (section,) = body["sections"]
    assert section["columns"][0] == "Code" and "Name" in section["columns"]
    name = section["columns"].index("Name")
    assert [row[name] for row in section["rows"]] == ["First"]
    assert section["rows"][0][0].startswith("SW-")
    assert body["metrics"] == [{"label": "Records", "value": 1, "gap": False, "group": None, "link": None}]
    assert _audit(project) == [], "an on-screen run is a view, not an export"


def test_without_a_record_type_requirements_is_used_as_the_catalogue_offers_it(world):
    project = world.project()
    entry = next(e for e in _catalogue(world, project) if e["slug"] == "record-list")
    default = next(p for p in entry["params"] if p["name"] == "record_type")["default"]
    resp = world.client.get(f"/api/v1/projects/{project['id']}/reports/record-list", headers=auth_headers(world.token))
    assert resp.status_code == 200, resp.text
    assert default == REQ and resp.json()["title"] == get_record_table_providers()[default].label


def test_any_type_with_a_table_is_a_report(world):
    project = world.project()
    world.action(project, "Chase the vendor")
    section = _report(world, project, ACTION).json()["sections"][0]
    assert section["title"] == "Actions"
    assert "Chase the vendor" in {cell for row in section["rows"] for cell in row}


def test_the_csv_is_the_exports_import_file_byte_for_byte(world):
    project = world.project()
    world.requirement(project, "=cmd|' /C calc'!A0")
    exported = world.client.get(f"/api/v1/projects/{project['id']}/records/{REQ}/export", headers=auth_headers(world.token))
    report = _report(world, project, format="csv")
    assert report.status_code == 200 and report.headers["content-type"].startswith("text/csv")
    assert report.content == exported.content
    rows = list(csv.DictReader(io.StringIO(report.content.decode("utf-8-sig"))))
    assert rows[0]["name"].startswith("'="), "the formula guard applies"


def test_the_pdf_is_a_document_and_the_word_file_fills_the_status_cells_as_the_screen_does(world):
    project = world.project()
    world.requirement(project, "Coloured")
    pdf = _report(world, project, format="pdf")
    assert pdf.status_code == 200 and pdf.content[:5] == b"%PDF-"
    assert pdf.headers["content-disposition"].endswith('-requirements-record-list.pdf"')
    docx = _report(world, project, format="docx")
    assert docx.status_code == 200
    xml = zipfile.ZipFile(io.BytesIO(docx.content)).read("word/document.xml").decode("utf-8")
    assert "Coloured" in xml and "Draft" in xml
    assert f'w:fill="{TONE_FILL["muted"]}"' in xml, "a Draft cell is filled with the muted tone"


def test_the_other_formats_are_real_files_and_are_audited_and_capped_like_the_documents(world):
    project = world.project()
    world.requirement(project, "=cmd|' /C calc'!A0")
    html = _report(world, project, format="html")
    assert html.status_code == 200 and html.headers["content-type"].startswith("text/html")
    assert html.headers["content-disposition"].endswith('-requirements-record-list.html"')
    odt = _report(world, project, format="odt")
    assert odt.status_code == 200 and odt.content[:2] == b"PK" and odt.headers["content-type"] == "application/vnd.oasis.opendocument.text"
    xlsx = _report(world, project, format="xlsx")
    assert xlsx.status_code == 200 and xlsx.headers["content-disposition"].endswith('-requirements-record-list.xlsx"')
    cells = [c.value for row in openpyxl.load_workbook(io.BytesIO(xlsx.content)).worksheets[0].iter_rows() for c in row]
    assert any(isinstance(v, str) and v.startswith("'=cmd") for v in cells), "the formula guard applies"
    ods = _report(world, project, format="ods")
    assert ods.status_code == 200 and ods.headers["content-type"] == "application/vnd.oasis.opendocument.spreadsheet"
    assert {e.detail["format"] for e in _audit(project)} >= {"html", "odt", "xlsx", "ods"}


def test_only_the_filters_of_the_list_apply(world):
    project = world.project()
    world.requirement(project, "Live")
    gone = world.requirement(project, "Archived one")
    assert world.client.delete(f"/api/v1/projects/{project['id']}/requirements/{gone}", headers=auth_headers(world.token)).status_code == 204

    def names(**params) -> set[str]:
        section = _report(world, project, **params).json()["sections"][0]
        index = section["columns"].index("Name")
        return {row[index] for row in section["rows"]}

    assert names() == {"Live"}
    assert names(include_archived="true") == {"Live", "Archived one"}
    body = _report(world, project, include_archived="true").json()
    assert "Filtered by: include_archived." in body["notes"]


def test_a_filter_the_type_cannot_honour_is_refused_not_ignored(world):
    project = world.project()
    resp = _report(world, project, outcome_status="done")
    assert resp.status_code == 422 and "outcome_status" in resp.json()["detail"]


def test_a_widened_scope_lists_related_projects_and_says_so(world):
    parent = world.project("Parent")
    child = world.project("Child", parent=parent)
    world.requirement(parent, "Parent record")
    world.requirement(child, "Child record")
    body = _report(world, parent, project_scope="children").json()
    section = body["sections"][0]
    assert section["columns"][-1] == "Project"
    assert {row[-1] for row in section["rows"]} == {parent["code"], child["code"]}
    assert any("related projects" in note for note in body["notes"])
    assert len(_report(world, parent).json()["sections"][0]["rows"]) == 1


def test_a_document_over_the_row_limit_is_refused_and_the_csv_is_not(world, monkeypatch):
    project = world.project()
    world.requirement(project, "One")
    world.requirement(project, "Two")
    from app.routers import record_list_report as router

    monkeypatch.setattr(router, "MAX_DOCUMENT_ROWS", 1)
    assert _report(world, project, format="pdf").status_code == 413
    assert _report(world, project, format="docx").status_code == 413
    assert _report(world, project, format="html").status_code == 413
    assert _report(world, project, format="odt").status_code == 413
    assert _report(world, project, format="csv").status_code == 200
    assert _report(world, project, format="xlsx").status_code == 200
    assert _report(world, project).status_code == 200


def test_a_report_template_must_be_the_organisations_own(world):
    project = world.project()
    assert _report(world, project, format="pdf", report_template_id=str(uuid.uuid4())).status_code == 400


# --- access and audit ---------------------------------------------------------------------------------------------


def test_a_file_is_audited_as_an_export_with_counts_only(world):
    project = world.project()
    world.requirement(project, "Secret-sounding name")
    _report(world, project, format="docx")
    _report(world, project, format="pdf", include_archived="true")
    events = {e.detail["format"]: e for e in _audit(project)}
    assert set(events) == {"docx", "pdf"}
    assert events["docx"].detail["rows"] == 1 and events["pdf"].detail["filters"] == ["include_archived"]
    assert "Secret-sounding" not in str([e.detail for e in events.values()])


def test_unknown_type_no_role_and_another_organisation_are_refused(client, admin_token):
    mine, theirs = World(client, admin_token, "Mine"), World(client, admin_token, "Theirs")
    project = mine.project()
    mine.requirement(project, "Mine only")
    assert _report(mine, project, "no_such_type").status_code == 404
    assert _report(mine, project, token=_outsider(mine)).status_code == 403
    assert _report(mine, project, token=theirs.token).status_code == 403


def test_a_type_whose_module_is_off_is_not_found(world, monkeypatch):
    project = world.project()
    monkeypatch.setattr(record_tables, "artefact_type_enabled_for_project", lambda db, artefact_type, project_id: False)
    assert _report(world, project).status_code == 404


def test_a_column_the_personal_data_policy_excludes_is_left_out_of_every_format_and_the_report_says_so(world, monkeypatch):
    project = world.project()
    world.requirement(project, "Has an owner")
    real = get_record_table_providers()[REQ]

    def tagged(db, project_row):
        return [dataclasses.replace(c, sensitivity="contact") if c.key == "owner" else c for c in real.columns(db, project_row)]

    patched = dataclasses.replace(real, columns=tagged)
    monkeypatch.setattr(record_tables, "get_record_table_providers", lambda: {**get_record_table_providers(), REQ: patched})
    body = _report(world, project).json()
    assert "Owner" not in body["sections"][0]["columns"]
    assert record_list_report.PERSONAL_DATA_NOTE in body["notes"]
    xml = zipfile.ZipFile(io.BytesIO(_report(world, project, format="docx").content)).read("word/document.xml").decode("utf-8")
    assert ">Owner<" not in xml
    assert _audit(project)[0].detail["omitted_sensitivity"] == ["contact"]


# --- the catalogue ------------------------------------------------------------------------------------------------


def test_the_catalogue_offers_the_record_list_with_exactly_the_types_the_caller_may_run(world):
    project = world.project()
    entry = next(e for e in _catalogue(world, project) if e["slug"] == "record-list")
    assert entry["module_key"] == "platform" and entry["scope"] == "project" and entry["supports_include_children"] is False
    assert entry["path"] == f"/api/v1/projects/{project['id']}/reports/record-list"
    assert set(entry["formats"]) == {"json", "pdf", "docx", "html", "odt", "csv", "xlsx", "ods"}
    record_type = next(p for p in entry["params"] if p["name"] == "record_type")
    assert {REQ, ACTION} <= set(record_type["choices"]) and record_type["default"] in record_type["choices"]
    assert record_type["choice_labels"][REQ] == "Requirements"
    assert [p["name"] for p in entry["params"]] == ["record_type", "tag"], "no project scope on a project with no relatives"


def test_the_project_scope_is_offered_only_where_the_project_has_relatives(world):
    parent = world.project("Parent")
    world.project("Child", parent=parent)
    entry = next(e for e in _catalogue(world, parent) if e["slug"] == "record-list")
    scope = next(p for p in entry["params"] if p["name"] == "project_scope")
    assert scope["choices"] == ["this", "parents", "children", "both"] and scope["default"] == "this"


def test_every_type_the_catalogue_offers_runs(world):
    """The picker must never offer a type the route refuses: run the report for each choice."""
    project = world.project()
    entry = next(e for e in _catalogue(world, project) if e["slug"] == "record-list")
    for record_type in next(p for p in entry["params"] if p["name"] == "record_type")["choices"]:
        assert _report(world, project, record_type).status_code == 200, record_type


def test_the_catalogue_is_closed_to_a_person_with_no_role_in_the_project(world):
    project = world.project()
    resp = world.client.get(f"/api/v1/projects/{project['id']}/report-catalogue", headers=auth_headers(_outsider(world)))
    assert resp.status_code == 403


def test_the_report_names_no_module():
    from pathlib import Path

    from app.modules.registry import get_module_registry

    root = Path(record_list_report.__file__).parent.parent
    for path in (root / "services" / "record_list_report.py", root / "routers" / "record_list_report.py"):
        for module_key in get_module_registry():
            assert f"modules.{module_key}" not in path.read_text(), f"{path.name} imports module {module_key}"
