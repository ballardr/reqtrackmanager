"""Tests for the Decision record table: the Decisions list exports as the CSV it imports, a row with a code updates
that Decision through the edit path (type and person validation, the content lock once approved), a blank code
creates a draft owned by the importer, and a file never moves a Decision through its approval workflow. Each test
builds its own organisation, so none depends on state left by another test.
"""

from __future__ import annotations

import csv
import io

from app.modules.decisions.tests.test_decisions_api import (
    _add_plain_member,
    _advance_to_under_review,
    _approve,
    _base,
    _create_decision,
    _first_decision_type_id,
    _setup,
)
from tests.conftest import auth_headers

DECISION = "decision"


def _records(project: dict) -> str:
    return f"/api/v1/projects/{project['id']}/records/{DECISION}"


def _export(client, token, project, **params):
    return client.get(f"{_records(project)}/export", params=params, headers=auth_headers(token))


def _rows(resp) -> list[dict]:
    assert resp.status_code == 200, resp.text
    return list(csv.DictReader(io.StringIO(resp.content.decode("utf-8-sig"))))


def _import(client, token, project, text: str, *, apply: bool = False):
    return client.post(
        f"{_records(project)}/import", params={"dry_run": "false" if apply else "true"},
        files={"file": ("records.csv", text.encode("utf-8"), "text/csv")}, headers=auth_headers(token),
    )


def _csv(header: list[str], *rows: list[str]) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(header)
    writer.writerows(rows)
    return out.getvalue()


def _get(client, token, project, decision_id) -> dict:
    resp = client.get(f"{_base(project['id'])}/{decision_id}", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _world(client, admin_token, name):
    org, project, token = _setup(client, admin_token, name)
    return org, project, token, _first_decision_type_id(client, token, project["id"])


def test_the_list_exports_with_codes_and_reimporting_it_unchanged_changes_nothing(client, admin_token):
    _, project, token, type_id = _world(client, admin_token, "Dec Tables Roundtrip Co")
    first = _create_decision(client, token, project["id"], type_id, rationale="Because")
    second = _create_decision(client, token, project["id"], type_id, title="Second")
    resp = _export(client, token, project)
    rows = _rows(resp)
    assert resp.headers["x-record-count"] == "2"
    assert {r["code"] for r in rows} == {first["unique_code"], second["unique_code"]}
    assert {r["status"] for r in rows} == {"Draft"}
    preview = _import(client, token, project, resp.content.decode("utf-8-sig")).json()
    assert (preview["created"], preview["updated"], preview["unchanged"], preview["failed"]) == (0, 0, 2, 0), preview


def test_editing_one_cell_updates_that_decision_and_a_preview_writes_nothing(client, admin_token):
    _, project, token, type_id = _world(client, admin_token, "Dec Tables Edit Co")
    decision = _create_decision(client, token, project["id"], type_id, rationale="Original")
    text = _csv(["code", "rationale"], [decision["unique_code"], "Cheaper to run"])
    preview = _import(client, token, project, text).json()
    assert preview["updated"] == 1 and preview["rows"][0]["changes"][0]["after"] == "Cheaper to run"
    assert _get(client, token, project, decision["id"])["rationale"] == "Original"
    assert _import(client, token, project, text, apply=True).json()["updated"] == 1
    after = _get(client, token, project, decision["id"])
    assert after["rationale"] == "Cheaper to run" and after["title"] == decision["title"]


def test_a_blank_code_creates_a_draft_owned_by_the_importer(client, admin_token):
    _, project, token, type_id = _world(client, admin_token, "Dec Tables Create Co")
    me = client.get("/api/v1/auth/me", headers=auth_headers(token)).json()["email"]
    types = client.get(f"{_base(project['id'])}/decision-types", headers=auth_headers(token)).json()
    name = next(t["name"] for t in types if t["id"] == type_id)
    text = _csv(["code", "title", "decision_statement", "type"], ["", "From a file", "We will do X", name])
    assert _import(client, token, project, text).json()["created"] == 1
    assert _rows(_export(client, token, project)) == [], "a preview must not create"
    assert _import(client, token, project, text, apply=True).json()["created"] == 1
    row = _rows(_export(client, token, project))[0]
    assert (row["title"], row["status"], row["owner"], row["type"]) == ("From a file", "Draft", me, name)
    assert row["code"].startswith("DEC-")


def test_a_create_without_its_required_columns_is_that_rows_error(client, admin_token):
    _, project, token, _ = _world(client, admin_token, "Dec Tables Required Co")
    result = _import(client, token, project, _csv(["code", "rationale"], ["", "just this"])).json()
    assert result["created"] == 0 and result["failed"] == 1


def test_the_type_is_a_name_and_an_unknown_one_is_that_rows_error(client, admin_token):
    _, project, token, type_id = _world(client, admin_token, "Dec Tables Type Co")
    decision = _create_decision(client, token, project["id"], type_id)
    types = client.get(f"{_base(project['id'])}/decision-types", headers=auth_headers(token)).json()
    current, other = (next(t["name"] for t in types if t["id"] == type_id), next(t["name"] for t in types if t["id"] != type_id))
    columns = client.get(f"{_records(project)}/columns", headers=auth_headers(token)).json()["columns"]
    assert current in next(c for c in columns if c["key"] == "type")["choices"]
    code = decision["unique_code"]
    assert _import(client, token, project, _csv(["code", "type"], [code, other]), apply=True).json()["updated"] == 1
    assert _rows(_export(client, token, project))[0]["type"] == other
    bad = _import(client, token, project, _csv(["code", "type"], [code, "Nonsense"])).json()
    assert bad["failed"] == 1 and "Unknown Decision type" in bad["rows"][0]["message"]


def test_dates_and_people_round_trip_and_the_owner_cannot_be_cleared(client, admin_token):
    _, project, token, type_id = _world(client, admin_token, "Dec Tables People Co")
    decision = _create_decision(client, token, project["id"], type_id)
    code = decision["unique_code"]
    me = client.get("/api/v1/auth/me", headers=auth_headers(token)).json()["email"]
    header = ["code", "decision_date", "decision_maker"]
    assert _import(client, token, project, _csv(header, [code, "2027-03-01", me]), apply=True).json()["updated"] == 1
    row = _rows(_export(client, token, project))[0]
    assert (row["decision_date"], row["decision_maker"]) == ("2027-03-01", me)
    assert _import(client, token, project, _csv(header, [code, "2027-03-01", me])).json()["unchanged"] == 1
    assert _import(client, token, project, _csv(header, [code, "", ""]), apply=True).json()["updated"] == 1
    after = _get(client, token, project, decision["id"])
    assert after["decision_date"] is None and after["decision_maker"] is None
    bad = _import(client, token, project, _csv(["code", "decision_date"], [code, "01/03/2027"])).json()
    assert bad["failed"] == 1 and "YYYY-MM-DD" in bad["rows"][0]["message"]
    blank_owner = _import(client, token, project, _csv(["code", "owner"], [code, ""])).json()
    assert blank_owner["failed"] == 1 and "needs an owner" in blank_owner["rows"][0]["message"]


def test_status_is_never_written_by_a_file_and_an_approved_decision_refuses_an_edit(client, admin_token):
    _, project, token, type_id = _world(client, admin_token, "Dec Tables Lock Co")
    decision = _create_decision(client, token, project["id"], type_id)
    ignored = _import(client, token, project, _csv(["code", "status"], [decision["unique_code"], "Approved"]), apply=True).json()
    assert ignored["updated"] == 0 and "status" in ignored["ignored_columns"]
    assert _get(client, token, project, decision["id"])["status"] == "draft"

    _advance_to_under_review(client, token, project["id"], decision["id"])
    _approve(client, token, project["id"], decision["id"])
    refused = _import(client, token, project, _csv(["code", "rationale"], [decision["unique_code"], "Changed"]), apply=True).json()
    assert refused["failed"] == 1 and "approved or superseded" in refused["rows"][0]["message"]
    assert _rows(_export(client, token, project))[0]["status"] == "Approved"


def test_a_plain_member_may_create_but_not_update(client, admin_token):
    org, project, token, type_id = _world(client, admin_token, "Dec Tables Member Co")
    decision = _create_decision(client, token, project["id"], type_id)
    _, member = _add_plain_member(client, token, org["id"], project["id"], "dec-tables-member@example.com")
    assert client.get(f"{_records(project)}/columns", headers=auth_headers(member)).json()["can_import"] is True
    types = client.get(f"{_base(project['id'])}/decision-types", headers=auth_headers(member)).json()
    name = next(t["name"] for t in types if t["id"] == type_id)
    created = _import(client, member, project, _csv(["code", "title", "decision_statement", "type"], ["", "Mine", "Do it", name]), apply=True).json()
    assert created["created"] == 1
    refused = _import(client, member, project, _csv(["code", "rationale"], [decision["unique_code"], "x"]), apply=True).json()
    assert refused["failed"] == 1 and refused["updated"] == 0


def test_the_lists_filters_reach_the_export(client, admin_token):
    _, project, token, type_id = _world(client, admin_token, "Dec Tables Filters Co")
    kept = _create_decision(client, token, project["id"], type_id, title="Kept decision")
    other = _create_decision(client, token, project["id"], type_id, title="Other decision")
    _advance_to_under_review(client, token, project["id"], other["id"])
    _approve(client, token, project["id"], other["id"])
    assert [r["code"] for r in _rows(_export(client, token, project, search="kept"))] == [kept["unique_code"]]
    assert [r["code"] for r in _rows(_export(client, token, project, status="approved"))] == [other["unique_code"]]
    assert [r["code"] for r in _rows(_export(client, token, project, open_only="true"))] == [kept["unique_code"]]
    assert len(_rows(_export(client, token, project, mine="true"))) == 2
    assert _export(client, token, project, nonsense="1").status_code == 422
