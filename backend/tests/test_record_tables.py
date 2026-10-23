"""Tests for the record table engine (`services.record_tables`, `routers.record_tables`): the CSV every record list
exports is the CSV it imports, a row with a code updates that record, a blank code creates one, and the type's own
create/update path (version lock, validation, audit) is what writes.

Each test builds its own organisation (`tests.link_world.World`), so none depends on state left by another test.
"""

from __future__ import annotations

import csv
import dataclasses
import io
import uuid
from pathlib import Path

import pytest

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.models.enums import RequirementStatus
from app.models.requirement import Requirement, RequirementVersion
from app.models.requirement_action import RequirementAction
from app.modules.registry import (
    RECORD_SENSITIVITY_TAGS,
    get_all_registered_artefact_types,
    get_module_registry,
    get_not_importable_types,
    get_record_table_providers,
)
from tests.conftest import auth_headers, create_org_user, create_project_group, login
from tests.link_world import ACTION, REQ, World

#: Types whose table has not been written yet. Shrinks as the roll-out lands; a type with a provider must not be
#: listed, and a type not listed must have one.
PENDING_RECORD_TABLES = {
    "change_request", "compliance_evidence", "compliance_required_action_assessment", "compliance_requirement", "decision",
    "engagement", "future_state", "guiding_principle", "open_question", "pain_point", "persona",
    "project_compliance_requirement", "research_finding", "risk", "stakeholder", "stakeholder_group", "stakeholder_need",
    "strategy",
}


@pytest.fixture
def world(client, admin_token) -> World:
    return World(client, admin_token, "Tables Org", context_strategy=True)


def _base(project: dict, record_type: str) -> str:
    return f"/api/v1/projects/{project['id']}/records/{record_type}"


def _export(world: World, project: dict, record_type: str = REQ, token: str | None = None, **params):
    return world.client.get(f"{_base(project, record_type)}/export", params=params, headers=auth_headers(token or world.token))


def _rows(resp) -> list[dict]:
    assert resp.status_code == 200, resp.text
    return list(csv.DictReader(io.StringIO(resp.content.decode("utf-8-sig"))))


def _import(world: World, project: dict, text: str, record_type: str = REQ, *, apply: bool = False, token: str | None = None):
    return world.client.post(
        f"{_base(project, record_type)}/import", params={"dry_run": "false" if apply else "true"},
        files={"file": ("records.csv", text.encode("utf-8"), "text/csv")}, headers=auth_headers(token or world.token),
    )


def _csv(header: list[str], *rows: list[str]) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(header)
    writer.writerows(rows)
    return out.getvalue()


def _member(world: World, project: dict, role: str = "member") -> str:
    """A user holding only `role` on `project`; returns their token."""
    email = f"{role}-{uuid.uuid4().hex[:6]}@example.com"
    user_id = create_org_user(world.client, world.token, world.org["id"], email)
    resp = world.client.post(
        f"/api/v1/projects/{project['id']}/roles", json={"user_id": user_id, "role": role}, headers=auth_headers(world.token),
    )
    assert resp.status_code in (200, 201, 204), resp.text
    return login(world.client, email, "Password123!")


def _versions(requirement_id: uuid.UUID) -> int:
    db = SessionLocal()
    try:
        return db.query(RequirementVersion).filter(RequirementVersion.requirement_id == requirement_id).count()
    finally:
        db.close()


def _requirement_count(project: dict) -> int:
    db = SessionLocal()
    try:
        return db.query(Requirement).filter(Requirement.project_id == project["id"]).count()
    finally:
        db.close()


def _audit(project: dict, action: str) -> list[AuditEvent]:
    db = SessionLocal()
    try:
        return list(db.query(AuditEvent).filter(AuditEvent.project_id == project["id"], AuditEvent.action == action).all())
    finally:
        db.close()


# --- the shape of the file ----------------------------------------------------------------------------------------


def test_export_starts_with_the_code_and_lists_the_records(world):
    project = world.project()
    world.requirement(project, "First")
    resp = _export(world, project)
    rows = _rows(resp)
    assert resp.headers["content-type"].startswith("text/csv")
    assert resp.headers["x-record-count"] == "1"
    assert list(rows[0])[0] == "code"
    assert rows[0]["name"] == "First"
    assert rows[0]["code"].startswith("SW-")


def test_columns_list_the_accepted_values_of_a_closed_column_and_none_for_free_text(world):
    project = world.project()
    resp = world.client.get(f"{_base(project, REQ)}/columns", headers=auth_headers(world.token))
    assert resp.status_code == 200, resp.text
    columns = {c["key"]: c for c in resp.json()["columns"]}
    assert columns["level"]["choices"] == ["Requirement", "Recommended", "Optional"]
    assert "SW" in columns["component"]["choices"]
    assert columns["category"]["choices"] and columns["target_version"]["choices"]
    assert columns["name"]["choices"] is None and columns["owner"]["choices"] is None


def test_columns_say_whether_the_caller_may_import(world):
    project = world.project()
    mine = world.client.get(f"{_base(project, REQ)}/columns", headers=auth_headers(world.token)).json()
    assert mine["importable"] is True and mine["can_import"] is True
    reader = world.client.get(f"{_base(project, REQ)}/columns", headers=auth_headers(_member(world, project, "member"))).json()
    assert reader["importable"] is True and reader["can_import"] is False


def test_a_cell_that_would_run_as_a_formula_is_prefixed_and_the_prefix_is_removed_on_import(world):
    project = world.project()
    rid = world.requirement(project, "=HYPERLINK(\"http://x\")")
    exported = _export(world, project)
    assert _rows(exported)[0]["name"] == "'=HYPERLINK(\"http://x\")"
    # Re-importing the same file changes nothing: the guard is stripped again, losslessly.
    result = _import(world, project, exported.content.decode("utf-8-sig"), apply=True).json()
    assert (result["updated"], result["unchanged"], result["failed"]) == (0, 1, 0)
    assert _versions(rid) == 1


def test_an_apostrophe_the_person_typed_is_not_mistaken_for_the_guard(world):
    project = world.project()
    rid = world.requirement(project, "'quoted title")
    exported = _export(world, project)
    assert _rows(exported)[0]["name"] == "'quoted title"
    result = _import(world, project, exported.content.decode("utf-8-sig"), apply=True).json()
    assert result["unchanged"] == 1 and _versions(rid) == 1


# --- round trip ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("record_type", [REQ, ACTION])
def test_reimporting_an_unchanged_export_changes_nothing(world, record_type):
    project = world.project()
    ids = [world.requirement(project, "A"), world.requirement(project, "B")] if record_type == REQ else [
        world.action(project, "A"), world.action(project, "B")
    ]
    text = _export(world, project, record_type).content.decode("utf-8-sig")
    preview = _import(world, project, text, record_type).json()
    assert (preview["created"], preview["updated"], preview["unchanged"], preview["failed"]) == (0, 0, 2, 0)
    applied = _import(world, project, text, record_type, apply=True).json()
    assert applied["applied"] is True and applied["updated"] == 0
    if record_type == REQ:
        assert [_versions(i) for i in ids] == [1, 1]


def test_editing_one_cell_updates_that_record_through_its_edit_path(world):
    project = world.project()
    rid = world.requirement(project, "Old name")
    other = world.requirement(project, "Untouched")
    rows = _rows(_export(world, project))
    text = _csv(["code", "name"], [rows[0]["code"], "New name"], [rows[1]["code"], rows[1]["name"]])
    preview = _import(world, project, text).json()
    assert preview["updated"] == 1 and preview["unchanged"] == 1
    change = preview["rows"][0]["changes"][0]
    assert (change["column"], change["before"], change["after"]) == ("name", "Old name", "New name")
    assert _versions(rid) == 1, "a preview must not write"

    assert _import(world, project, text, apply=True).json()["updated"] == 1
    assert _versions(rid) == 2
    assert _versions(other) == 1
    names = {r["name"] for r in _rows(_export(world, project))}
    assert names == {"New name", "Untouched"}


def test_a_column_missing_from_the_file_is_left_alone_and_a_blank_cell_clears(world):
    project = world.project()
    world.requirement(project, "Has description")
    code = _rows(_export(world, project))[0]["code"]
    world.client.put(
        f"/api/v1/projects/{project['id']}/requirements/{world.requirement(project, 'Other')}",
        json={"name": "Other", "description": "kept", "component_id": project["component_id"],
              "category_id": project["category_id"], "owner": {"type": "user", "id": str(world.user_id)}},
        headers=auth_headers(world.token),
    )
    rows = {r["name"]: r for r in _rows(_export(world, project))}
    assert rows["Other"]["description"] == "kept"
    # Only `name` in the file: description untouched.
    _import(world, project, _csv(["code", "name"], [rows["Other"]["code"], "Other 2"]), apply=True)
    # A present, blank `description` clears it.
    code2 = {r["name"]: r for r in _rows(_export(world, project))}["Other 2"]["code"]
    result = _import(world, project, _csv(["code", "description"], [code2, ""]), apply=True).json()
    assert result["updated"] == 1
    assert {r["name"]: r for r in _rows(_export(world, project))}["Other 2"]["description"] == ""
    assert code  # the first project record stayed in the list


def test_a_blank_code_creates_a_record_and_a_preview_creates_nothing(world):
    project = world.project()
    text = _csv(["code", "name", "component", "category"], ["", "Brand new", "SW", "PERF"])
    preview = _import(world, project, text).json()
    assert preview["created"] == 1 and preview["rows"][0]["action"] == "create"
    assert _requirement_count(project) == 0
    assert _import(world, project, text, apply=True).json()["created"] == 1
    assert _requirement_count(project) == 1
    rows = _rows(_export(world, project))
    assert rows[0]["name"] == "Brand new" and rows[0]["code"]


def test_a_create_needs_its_required_columns(world):
    project = world.project()
    no_name = _import(world, project, _csv(["code", "component", "category"], ["", "SW", "PERF"])).json()
    assert no_name["failed"] == 1 and "no Name column" in no_name["rows"][0]["message"]
    blank = _import(world, project, _csv(["name", "component", "category"], ["", "SW", "PERF"])).json()
    assert blank["rows"][0]["message"] == "Name is required."
    unknown = _import(world, project, _csv(["name", "component", "category"], ["X", "NOPE", "PERF"])).json()
    assert "Unknown component" in unknown["rows"][0]["message"]


def test_valid_rows_apply_and_failed_rows_come_back_as_a_csv_to_fix(world):
    project = world.project()
    text = _csv(
        ["code", "name", "component", "category"],
        ["", "Good", "SW", "PERF"], ["", "Bad", "ZZ", "PERF"], ["", "Also good", "SW", "PERF"],
    )
    result = _import(world, project, text, apply=True).json()
    assert (result["created"], result["failed"]) == (2, 1)
    assert _requirement_count(project) == 2
    errors = list(csv.DictReader(io.StringIO(result["error_csv"])))
    assert len(errors) == 1 and errors[0]["name"] == "Bad" and "Unknown component" in errors[0]["error"]


# --- the code decides what a row means ----------------------------------------------------------------------------


def test_an_unknown_other_project_or_other_organisation_code_is_one_and_the_same_row_error(client, admin_token):
    mine = World(client, admin_token, "Mine")
    theirs = World(client, admin_token, "Theirs")
    project, sibling, foreign = mine.project("P"), mine.project("Q"), theirs.project("R")
    sibling_req = mine.requirement(sibling, "Sibling record")
    theirs.requirement(foreign, "Foreign record")
    sibling_code = _rows(_export(mine, sibling))[0]["code"]
    foreign_code = _rows(_export(theirs, foreign))[0]["code"]
    messages = set()
    for code in (sibling_code, foreign_code, "SW-PERF-999", f"{sibling['code']}-{sibling_code}"):
        result = _import(mine, project, _csv(["code", "name"], [code, "Hijack"]), apply=True).json()
        assert (result["updated"], result["failed"]) == (0, 1), code
        messages.add(result["rows"][0]["message"].replace(code, "<code>"))
    assert len(messages) == 1, messages
    assert _versions(sibling_req) == 1, "another project's record must never be written"


def test_a_code_may_be_written_with_this_projects_own_code_in_front(world):
    project = world.project()
    rid = world.requirement(project, "Qualified")
    code = _rows(_export(world, project))[0]["code"]
    result = _import(world, project, _csv(["code", "name"], [f"{project['code']}-{code}", "Renamed"]), apply=True).json()
    assert result["updated"] == 1 and _versions(rid) == 2


def test_the_same_code_twice_in_a_file_is_refused_the_second_time(world):
    project = world.project()
    world.requirement(project, "Once")
    code = _rows(_export(world, project))[0]["code"]
    result = _import(world, project, _csv(["code", "name"], [code, "First edit"], [code, "Second edit"]), apply=True).json()
    assert (result["updated"], result["failed"]) == (1, 1)
    assert "more than once" in result["rows"][1]["message"]


def test_an_approved_requirement_refuses_a_file_edit_and_status_is_never_written(world):
    project = world.project()
    rid = world.requirement(project, "Locked one")
    db = SessionLocal()
    try:
        version = db.query(RequirementVersion).filter(RequirementVersion.requirement_id == rid, RequirementVersion.valid_to.is_(None)).one()
        version.status = RequirementStatus.APPROVED
        db.commit()
    finally:
        db.close()
    code = _rows(_export(world, project))[0]["code"]
    result = _import(world, project, _csv(["code", "name", "status"], [code, "Changed", "Draft"]), apply=True).json()
    assert result["failed"] == 1 and "change request" in result["rows"][0]["message"]
    assert "status" in result["ignored_columns"]
    assert _versions(rid) == 1


def test_a_draft_requirement_keeps_its_status_when_the_file_names_another(world):
    project = world.project()
    world.requirement(project, "Draft one")
    code = _rows(_export(world, project))[0]["code"]
    result = _import(world, project, _csv(["code", "name", "status"], [code, "Draft one!", "Approved"]), apply=True).json()
    assert result["updated"] == 1 and "status" in result["ignored_columns"]
    row = _rows(_export(world, project))[0]
    assert row["name"] == "Draft one!" and row["status"] == "Draft"


# --- people -------------------------------------------------------------------------------------------------------


def test_an_owner_is_an_email_or_a_group_and_both_round_trip(world, client):
    project = world.project()
    group_id = create_project_group(client, world.token, project["id"], "Platform Team", users=[str(world.user_id)])
    assert group_id
    world.requirement(project, "Owned")
    rows = _rows(_export(world, project))
    assert "@" in rows[0]["owner"]
    code = rows[0]["code"]
    by_group = _import(world, project, _csv(["code", "owner"], [code, "Platform Team (Project group)"]), apply=True).json()
    assert by_group["updated"] == 1
    exported = _rows(_export(world, project))[0]
    assert exported["owner"] == "Platform Team (Project group)"
    # The exported group cell re-imports unchanged, and a user email takes it back.
    again = _import(world, project, _export(world, project).content.decode("utf-8-sig"), apply=True).json()
    assert again["unchanged"] == 1
    email = client.get("/api/v1/auth/me", headers=auth_headers(world.token)).json()["email"]
    assert _import(world, project, _csv(["code", "owner"], [code, email]), apply=True).json()["updated"] == 1
    unknown = _import(world, project, _csv(["code", "owner"], [code, "nobody@example.com"])).json()
    assert "Unknown owner" in unknown["rows"][0]["message"]
    other_group = _import(world, project, _csv(["code", "owner"], [code, "No Such Group"])).json()
    assert other_group["failed"] == 1


def test_a_user_of_another_organisation_reads_like_an_unknown_email(client, admin_token):
    mine, theirs = World(client, admin_token, "Mine"), World(client, admin_token, "Theirs")
    project = mine.project()
    mine.requirement(project, "Owned")
    code = _rows(_export(mine, project))[0]["code"]
    foreign_email = client.get("/api/v1/auth/me", headers=auth_headers(theirs.token)).json()["email"]
    result = _import(mine, project, _csv(["code", "owner"], [code, foreign_email]), apply=True).json()
    unknown = _import(mine, project, _csv(["code", "owner"], [code, "nobody-here@example.com"])).json()
    assert result["failed"] == 1
    assert result["rows"][0]["message"].replace(foreign_email, "<e>") == unknown["rows"][0]["message"].replace("nobody-here@example.com", "<e>")


def test_an_action_round_trips_with_a_group_assignee_an_outcome_and_a_due_date(world, client):
    project = world.project()
    create_project_group(client, world.token, project["id"], "Reviewers", users=[str(world.user_id)])
    types = client.get(f"/api/v1/projects/{project['id']}/action-types", headers=auth_headers(world.token)).json()
    text = _csv(
        ["code", "title", "action_type", "assignee", "outcome", "due_date"],
        ["", "Review spec", types[0]["name"], "Reviewers (Project group)", "Completed", "2027-03-05"],
    )
    assert _import(world, project, text, ACTION, apply=True).json()["created"] == 1
    row = _rows(_export(world, project, ACTION))[0]
    assert (row["title"], row["assignee"], row["outcome"], row["due_date"]) == ("Review spec", "Reviewers (Project group)", "Completed", "2027-03-05")
    assert row["completed_at"]
    again = _import(world, project, _export(world, project, ACTION).content.decode("utf-8-sig"), ACTION, apply=True).json()
    assert again["unchanged"] == 1
    bad = _import(world, project, _csv(["code", "action_type"], [row["code"], "Not a type"]), ACTION).json()
    assert "Unknown action type" in bad["rows"][0]["message"]
    bad_date = _import(world, project, _csv(["code", "due_date"], [row["code"], "05/03/2027"]), ACTION).json()
    assert "YYYY-MM-DD" in bad_date["rows"][0]["message"]


# --- filters, tags and nested projects ----------------------------------------------------------------------------


def test_the_export_respects_the_lists_filters_and_refuses_one_it_cannot_honour(world):
    project = world.project()
    world.requirement(project, "Alpha one")
    world.requirement(project, "Beta two")
    assert [r["name"] for r in _rows(_export(world, project, search="alpha"))] == ["Alpha one"]
    assert _export(world, project, status="draft").headers["x-record-count"] == "2"
    assert _export(world, project, status="approved").headers["x-record-count"] == "0"
    refused = _export(world, project, sort="name")
    assert refused.status_code == 422 and "sort" in refused.json()["detail"]
    assert _export(world, project, status="bogus").status_code == 422


def test_the_export_respects_the_tag_filter_and_archived_visibility(world):
    project = world.project()
    tagged = world.requirement(project, "Tagged")
    world.requirement(project, "Plain")
    resp = world.client.post(
        f"/api/v1/projects/{project['id']}/artefacts/requirement/{tagged}/tags", json={"name": "safety"}, headers=auth_headers(world.token),
    )
    assert resp.status_code == 201, resp.text
    assert [r["name"] for r in _rows(_export(world, project, tag="safety"))] == ["Tagged"]
    gone = world.requirement(project, "Archived one")
    assert world.client.delete(f"/api/v1/projects/{project['id']}/requirements/{gone}", headers=auth_headers(world.token)).status_code == 204
    assert "Archived one" not in {r["name"] for r in _rows(_export(world, project))}
    assert "Archived one" in {r["name"] for r in _rows(_export(world, project, include_archived="true"))}


def test_a_widened_scope_exports_related_projects_with_qualified_codes_that_cannot_be_imported_here(world):
    parent = world.project("Parent")
    child = world.project("Child", parent=parent)
    world.requirement(parent, "Parent record")
    world.requirement(child, "Child record")
    rows = {r["name"]: r for r in _rows(_export(world, parent, project_scope="children"))}
    assert set(rows) == {"Parent record", "Child record"}
    assert rows["Child record"]["project"] == child["code"] and rows["Parent record"]["project"] == parent["code"]
    assert rows["Child record"]["code"].startswith(f"{child['code']}-")
    assert [r["name"] for r in _rows(_export(world, parent))] == ["Parent record"]
    # Read-only here: the child's qualified code is not this project's record.
    text = _csv(["code", "name"], [rows["Child record"]["code"], "Edited from the parent"])
    assert _import(world, parent, text, apply=True).json()["failed"] == 1


# --- access -------------------------------------------------------------------------------------------------------


def test_an_unknown_type_and_a_type_without_a_table_yet_are_not_found(world):
    project = world.project()
    assert _export(world, project, "no_such_type").status_code == 404
    assert world.client.get(f"{_base(project, 'no_such_type')}/columns", headers=auth_headers(world.token)).status_code == 404
    assert _import(world, project, "code\n", "no_such_type").status_code == 404


def test_a_person_with_no_role_in_the_project_cannot_export_or_import(world):
    project = world.project()
    world.requirement(project, "Private")
    email = f"outsider-{uuid.uuid4().hex[:6]}@example.com"
    create_org_user(world.client, world.token, world.org["id"], email)
    outsider = login(world.client, email, "Password123!")
    assert _export(world, project, token=outsider).status_code == 403
    assert _import(world, project, _csv(["name"], ["x"]), token=outsider, apply=True).status_code == 403


def test_a_read_only_member_may_export_but_not_import(world):
    project = world.project()
    rid = world.requirement(project, "Readable")
    member = _member(world, project, "member")
    assert _rows(_export(world, project, token=member))[0]["name"] == "Readable"
    code = _rows(_export(world, project, token=member))[0]["code"]
    denied = _import(world, project, _csv(["code", "name"], [code, "Vandalised"]), token=member, apply=True)
    assert denied.status_code == 403
    assert _versions(rid) == 1


def test_another_organisations_user_cannot_use_the_tables_of_this_project(client, admin_token):
    mine, theirs = World(client, admin_token, "Mine"), World(client, admin_token, "Theirs")
    project = mine.project()
    mine.requirement(project, "Mine only")
    assert _export(mine, project, token=theirs.token).status_code == 403


def test_a_module_that_is_off_for_the_organisation_hides_its_types(world, monkeypatch):
    """A provider whose module is off answers 404 like a type that does not exist."""
    project = world.project()
    from app.services import record_tables

    monkeypatch.setattr(record_tables, "artefact_type_enabled_for_project", lambda db, artefact_type, project_id: False)
    assert _export(world, project).status_code == 404


# --- caps and malformed files -------------------------------------------------------------------------------------


def test_a_file_over_the_byte_or_row_cap_is_refused(world, monkeypatch):
    from app.services import record_tables

    project = world.project()
    text = _csv(["name", "component", "category"], *[[f"R{i}", "SW", "PERF"] for i in range(3)])
    monkeypatch.setattr(record_tables, "MAX_IMPORT_ROWS", 2)
    assert _import(world, project, text).status_code == 413
    monkeypatch.setattr(record_tables, "MAX_IMPORT_ROWS", 5000)
    monkeypatch.setattr("app.routers.record_tables.MAX_IMPORT_BYTES", 10)
    monkeypatch.setattr(record_tables, "MAX_IMPORT_BYTES", 10)
    assert _import(world, project, text).status_code == 413
    assert _requirement_count(project) == 0


@pytest.mark.parametrize(
    "body", [b"", b"\xff\xfe\x00\x01 not utf8 \xc3\x28", b",,\n1,2\n", b"name,name\nA,B\n"],
    ids=["empty", "not-utf8", "blank-header", "repeated-header"],
)
def test_a_malformed_file_is_a_422_with_a_message(world, body):
    project = world.project()
    resp = world.client.post(
        f"{_base(project, REQ)}/import", files={"file": ("x.csv", body, "text/csv")}, headers=auth_headers(world.token),
    )
    assert resp.status_code == 422 and resp.json()["detail"]


def test_a_file_with_only_ignored_columns_changes_nothing_and_says_why(world):
    project = world.project()
    world.requirement(project, "Same")
    code = _rows(_export(world, project))[0]["code"]
    result = _import(world, project, _csv(["code", "mystery", "status"], [code, "x", "Approved"]), apply=True).json()
    assert result["unchanged"] == 1
    assert result["ignored_columns"]["mystery"] == "Not a column of this record type."


# --- audit --------------------------------------------------------------------------------------------------------


def test_an_export_and_an_apply_are_each_one_audit_event_with_counts_and_never_cell_values(world):
    project = world.project()
    world.requirement(project, "Confidential wording zq9")
    _export(world, project, search="confidential")
    exported = _audit(project, "records_exported")
    assert len(exported) == 1
    detail = exported[0].detail
    assert detail["record_type"] == REQ and detail["rows"] == 1 and detail["filters"] == ["search"]
    assert "zq9" not in str(detail) and "confidential" not in str(detail).lower().replace("confidential_", "")

    text = _csv(["name", "component", "category"], ["Imported thing", "SW", "PERF"])
    _import(world, project, text)  # a preview writes no event
    assert _audit(project, "records_imported") == []
    _import(world, project, text, apply=True)
    imported = _audit(project, "records_imported")
    assert len(imported) == 1 and imported[0].detail["created"] == 1
    assert "Imported thing" not in str(imported[0].detail)
    created = _audit(project, "created")
    assert any(e.entity_type == "requirement" for e in created), "the type's own create event is written too"


# --- personal data ------------------------------------------------------------------------------------------------


def test_a_column_tagged_as_personal_data_is_left_out_of_export_and_import_by_default(world, monkeypatch):
    project = world.project()
    world.requirement(project, "Has an owner")
    real = get_record_table_providers()[REQ]

    def tagged(db, project_row):
        return [dataclasses.replace(c, sensitivity="contact") if c.key == "owner" else c for c in real.columns(db, project_row)]

    patched = dataclasses.replace(real, columns=tagged)
    from app.services import record_tables

    monkeypatch.setattr(record_tables, "get_record_table_providers", lambda: {**get_record_table_providers(), REQ: patched})
    resp = _export(world, project)
    assert "owner" not in _rows(resp)[0]
    assert resp.headers["x-omitted-sensitivity"] == "contact"
    columns = world.client.get(f"{_base(project, REQ)}/columns", headers=auth_headers(world.token)).json()
    owner = next(c for c in columns["columns"] if c["key"] == "owner")
    assert owner["included"] is False and columns["omitted_sensitivity"] == ["contact"]
    code = _rows(resp)[0]["code"]
    result = _import(world, project, _csv(["code", "owner"], [code, "someone@example.com"]), apply=True).json()
    assert result["ignored_columns"]["owner"] == "Excluded by your organisation's policy."
    assert result["omitted_sensitivity"] == ["contact"] and result["unchanged"] == 1
    assert _audit(project, "records_exported")[0].detail["omitted_sensitivity"] == ["contact"]


# --- the registry -------------------------------------------------------------------------------------------------


def test_every_registered_artefact_type_has_a_record_table_or_is_pending():
    providers = get_record_table_providers()
    registered = get_all_registered_artefact_types()
    missing = {t for t in registered if t not in providers}
    assert missing == PENDING_RECORD_TABLES, "update PENDING_RECORD_TABLES: it lists exactly the types without a table"
    assert not set(providers) - registered, "a provider names a type that is not registered"


def test_not_importable_reasons_name_registered_types_with_a_reason():
    registered = get_all_registered_artefact_types()
    for artefact_type, reason in get_not_importable_types().items():
        assert artefact_type in registered and reason.strip(), artefact_type


def test_provider_columns_are_unique_valid_and_never_bypass_an_approval_gate(world):
    project = world.project()
    from app.models.project import Project

    db = SessionLocal()
    try:
        row = db.get(Project, uuid.UUID(project["id"]))
        for artefact_type, provider in get_record_table_providers().items():
            columns = list(provider.columns(db, row))
            keys = [c.key for c in columns]
            assert len(keys) == len(set(keys)), f"{artefact_type} repeats a column"
            assert not {"code", "project"} & set(keys), f"{artefact_type} redeclares a reserved column"
            for column in columns:
                assert column.sensitivity == "none" or column.sensitivity in RECORD_SENSITIVITY_TAGS, (artefact_type, column.key)
                assert not column.editable or column.importable, f"{artefact_type}.{column.key} is editable but not importable"
                assert not column.required or column.importable, f"{artefact_type}.{column.key} is required but not importable"
            if provider.approval_gated:
                assert "status" not in {c.key for c in columns if c.importable}, f"{artefact_type} imports its status"
            assert provider.create is not None or provider.update is not None or artefact_type in get_not_importable_types()
    finally:
        db.close()


def test_the_table_engine_names_no_module():
    backend = Path(__file__).resolve().parents[1] / "app"
    core_files = [
        backend / "services" / "record_tables.py", backend / "services" / "record_tables_core.py",
        backend / "routers" / "record_tables.py", backend / "schemas" / "record_tables.py",
    ]
    for module_key in get_module_registry():
        for path in core_files:
            assert f"modules.{module_key}" not in path.read_text(), f"{path.name} imports module {module_key}"


def test_actions_keep_working_through_their_own_endpoints_after_the_shared_edit_path(world):
    """The action endpoints and the file import share one create/edit path (`services.actions`)."""
    project = world.project()
    aid = world.action(project, "Via API")
    patched = world.client.patch(
        f"/api/v1/projects/{project['id']}/actions/{aid}",
        json={"title": "Via API 2", "action_type_id": world.client.get(
            f"/api/v1/projects/{project['id']}/action-types", headers=auth_headers(world.token)).json()[0]["id"],
            "outcome_status": "completed"},
        headers=auth_headers(world.token),
    )
    assert patched.status_code == 200 and patched.json()["outcome_status"] == "completed"
    db = SessionLocal()
    try:
        assert db.get(RequirementAction, aid).completed_at is not None
    finally:
        db.close()
