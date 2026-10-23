"""Tests for Context & Strategy's record tables: Strategies, Future States, Guiding Principles, Pain Points and
Open Questions export their list as the CSV they import, a row with a code updates that record through the
type's own edit path (the content lock past review, the terminal outcome of a Pain Point or Open Question), a blank
code creates one, and a file never moves a record through its lifecycle.

Each test builds its own organisation, so none depends on state left by another test.
"""

from __future__ import annotations

import csv
import functools
import io
import uuid

import pytest

from app.modules.context_strategy.tests.test_context_strategy_relationships_api import (
    _add_plain_member,
    _advance_strategy_to_active,
    _create_future_state,
    _create_guiding_principle,
    _create_open_question,
    _create_org_strategy,
    _create_pain_point,
    _create_strategy,
    _market_pain_point_type_id,
    _setup,
)
from tests.conftest import auth_headers

STRATEGY, FUTURE_STATE, GUIDING_PRINCIPLE, PAIN_POINT, OPEN_QUESTION = (
    "strategy", "future_state", "guiding_principle", "pain_point", "open_question",
)
PATHS = {
    STRATEGY: "strategies", FUTURE_STATE: "future-states", GUIDING_PRINCIPLE: "guiding-principles",
    PAIN_POINT: "pain-points", OPEN_QUESTION: "open-questions",
}
#: type -> (creator, the column a test edits, its new value, how the API names it)
CASES = {
    STRATEGY: (_create_strategy, "objective", "Win the whole market", "objective"),
    FUTURE_STATE: (_create_future_state, "desired_state", "Every inspection is automatic", "desired_state"),
    GUIDING_PRINCIPLE: (_create_guiding_principle, "rationale", "People get hurt otherwise", "rationale"),
    PAIN_POINT: (_create_pain_point, "impact", "Customers churn", "impact"),
    OPEN_QUESTION: (_create_open_question, "context", "Procurement closes in March", "context"),
}
TITLE_COLUMN = {STRATEGY: "title", FUTURE_STATE: "title", GUIDING_PRINCIPLE: "name", PAIN_POINT: "title", OPEN_QUESTION: "question"}


def _base(project: dict, record_type: str) -> str:
    return f"/api/v1/projects/{project['id']}/records/{record_type}"


def _module(project: dict, record_type: str) -> str:
    return f"/api/v1/projects/{project['id']}/modules/context_strategy/{PATHS[record_type]}"


def _export(client, token, project, record_type, **params):
    return client.get(f"{_base(project, record_type)}/export", params=params, headers=auth_headers(token))


def _rows(resp) -> list[dict]:
    assert resp.status_code == 200, resp.text
    return list(csv.DictReader(io.StringIO(resp.content.decode("utf-8-sig"))))


def _import(client, token, project, record_type, text: str, *, apply: bool = False):
    return client.post(
        f"{_base(project, record_type)}/import", params={"dry_run": "false" if apply else "true"},
        files={"file": ("records.csv", text.encode("utf-8"), "text/csv")}, headers=auth_headers(token),
    )


def _csv(header: list[str], *rows: list[str]) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(header)
    writer.writerows(rows)
    return out.getvalue()


def _codes(client, token, project, record_type, **params) -> set[str]:
    """The codes an export with `params` lists."""
    return {r["code"] for r in _rows(_export(client, token, project, record_type, **params))}


def _get(client, token, project, record_type, record_id) -> dict:
    resp = client.get(f"{_module(project, record_type)}/{record_id}", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.fixture
def world(client, admin_token):
    org, project, token = _setup(client, admin_token, f"CS Tables {uuid.uuid4().hex[:6]}")
    return client, org, project, token


@pytest.mark.parametrize("record_type", list(CASES))
def test_a_list_exports_with_its_codes_and_reimporting_it_unchanged_changes_nothing(world, record_type):
    client, _, project, token = world
    create = CASES[record_type][0]
    first, second = create(client, token, project["id"]), create(client, token, project["id"])
    resp = _export(client, token, project, record_type)
    rows = _rows(resp)
    assert resp.headers["x-record-count"] == "2"
    assert {r["code"] for r in rows} == {first["unique_code"], second["unique_code"]}
    text = resp.content.decode("utf-8-sig")
    preview = _import(client, token, project, record_type, text).json()
    assert (preview["created"], preview["updated"], preview["unchanged"], preview["failed"]) == (0, 0, 2, 0), preview
    applied = _import(client, token, project, record_type, text, apply=True).json()
    assert applied["applied"] is True and applied["updated"] == 0


@pytest.mark.parametrize("record_type", list(CASES))
def test_editing_one_cell_updates_that_record_and_leaves_the_other_alone(world, record_type):
    client, _, project, token = world
    create, column, value, api_field = CASES[record_type]
    target, other = create(client, token, project["id"]), create(client, token, project["id"])
    untouched = {r["code"]: r[column] for r in _rows(_export(client, token, project, record_type))}[other["unique_code"]]
    text = _csv(["code", column], [target["unique_code"], value], [other["unique_code"], untouched])
    preview = _import(client, token, project, record_type, text).json()
    assert preview["updated"] == 1 and preview["unchanged"] == 1, preview
    change = preview["rows"][0]["changes"][0]
    assert (change["column"], change["after"]) == (column, value)
    assert _get(client, token, project, record_type, target["id"])[api_field] != value, "a preview must not write"

    assert _import(client, token, project, record_type, text, apply=True).json()["updated"] == 1
    assert _get(client, token, project, record_type, target["id"])[api_field] == value


@pytest.mark.parametrize("record_type", list(CASES))
def test_a_blank_code_creates_a_record_with_its_own_code(world, record_type):
    client, _, project, token = world
    header = ["code", TITLE_COLUMN[record_type]]
    row = ["", "From a file"]
    if record_type == STRATEGY:
        header.append("objective"), row.append("Be the best")
    if record_type == GUIDING_PRINCIPLE:
        header.append("principle_statement"), row.append("Be kind")
    if record_type == PAIN_POINT:
        header.append("type"), row.append("Market")
    text = _csv(header, row)
    assert _import(client, token, project, record_type, text).json()["created"] == 1
    assert _rows(_export(client, token, project, record_type)) == [], "a preview must not create"
    assert _import(client, token, project, record_type, text, apply=True).json()["created"] == 1
    created = _rows(_export(client, token, project, record_type))
    assert [r[TITLE_COLUMN[record_type]] for r in created] == ["From a file"]
    assert created[0]["code"]
    assert created[0]["status"] == {
        STRATEGY: "Draft", FUTURE_STATE: "Draft", GUIDING_PRINCIPLE: "Draft", PAIN_POINT: "Submitted", OPEN_QUESTION: "Open",
    }[record_type]


@pytest.mark.parametrize("record_type", list(CASES))
def test_a_create_without_its_required_columns_is_that_rows_error(world, record_type):
    client, _, project, token = world
    optional = {STRATEGY: "rationale", FUTURE_STATE: "outcomes", GUIDING_PRINCIPLE: "rationale", PAIN_POINT: "description", OPEN_QUESTION: "context"}
    result = _import(client, token, project, record_type, _csv(["code", optional[record_type]], ["", "just this"])).json()
    assert result["created"] == 0 and result["failed"] == 1
    assert "required" in result["rows"][0]["message"] or "no " in result["rows"][0]["message"]


def test_status_is_exported_with_its_label_and_never_written_by_a_file(world):
    client, _, project, token = world
    strategy = _create_strategy(client, token, project["id"])
    _advance_strategy_to_active(client, token, project["id"], strategy["id"])
    rows = _rows(_export(client, token, project, STRATEGY))
    assert rows[0]["status"] == "Active"
    result = _import(client, token, project, STRATEGY, _csv(["code", "status"], [strategy["unique_code"], "Retired"]), apply=True).json()
    assert result["updated"] == 0 and "status" in result["ignored_columns"]
    assert _get(client, token, project, STRATEGY, strategy["id"])["status"] == "active"


def test_a_strategy_past_review_refuses_a_file_edit_with_the_endpoints_message(world):
    client, _, project, token = world
    strategy = _create_strategy(client, token, project["id"])
    _advance_strategy_to_active(client, token, project["id"], strategy["id"])
    result = _import(client, token, project, STRATEGY, _csv(["code", "objective"], [strategy["unique_code"], "New"]), apply=True).json()
    assert result["failed"] == 1 and "past review" in result["rows"][0]["message"]
    assert _get(client, token, project, STRATEGY, strategy["id"])["objective"] != "New"


def test_a_closed_pain_point_and_a_withdrawn_open_question_refuse_a_file_edit(world):
    client, _, project, token = world
    pain_point = _create_pain_point(client, token, project["id"])
    assert client.post(f"{_module(project, PAIN_POINT)}/{pain_point['id']}/triage", json={}, headers=auth_headers(token)).status_code == 200
    resp = client.post(
        f"{_module(project, PAIN_POINT)}/{pain_point['id']}/reject", json={"comment": "Not a defect"}, headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    result = _import(client, token, project, PAIN_POINT, _csv(["code", "impact"], [pain_point["unique_code"], "x"]), apply=True).json()
    assert result["failed"] == 1 and "terminal outcome" in result["rows"][0]["message"]

    question = _create_open_question(client, token, project["id"])
    assert client.post(f"{_module(project, OPEN_QUESTION)}/{question['id']}/investigate", json={}, headers=auth_headers(token)).status_code == 200
    resp = client.post(
        f"{_module(project, OPEN_QUESTION)}/{question['id']}/withdraw", json={"comment": "No longer needed"}, headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    result = _import(client, token, project, OPEN_QUESTION, _csv(["code", "context"], [question["unique_code"], "x"]), apply=True).json()
    assert result["failed"] == 1 and "terminal outcome" in result["rows"][0]["message"]


def test_a_future_state_target_date_round_trips_and_clears(world):
    client, _, project, token = world
    future_state = _create_future_state(client, token, project["id"], target_date="2027-03-01")
    assert _rows(_export(client, token, project, FUTURE_STATE))[0]["target_date"] == "2027-03-01"
    code = future_state["unique_code"]
    assert _import(client, token, project, FUTURE_STATE, _csv(["code", "target_date"], [code, "2028-12-31"]), apply=True).json()["updated"] == 1
    assert _get(client, token, project, FUTURE_STATE, future_state["id"])["target_date"] == "2028-12-31"
    assert _import(client, token, project, FUTURE_STATE, _csv(["code", "target_date"], [code, ""]), apply=True).json()["updated"] == 1
    assert _get(client, token, project, FUTURE_STATE, future_state["id"])["target_date"] is None
    bad = _import(client, token, project, FUTURE_STATE, _csv(["code", "target_date"], [code, "31/12/2028"])).json()
    assert bad["failed"] == 1 and "YYYY-MM-DD" in bad["rows"][0]["message"]


def test_an_open_question_due_date_and_owner_round_trip(world):
    client, org, project, token = world
    question = _create_open_question(client, token, project["id"], due_date="2027-01-15")
    email = client.get("/api/v1/auth/me", headers=auth_headers(token)).json()["email"]
    code = question["unique_code"]
    result = _import(client, token, project, OPEN_QUESTION, _csv(["code", "owner", "due_date"], [code, email, "2027-02-01"]), apply=True).json()
    assert result["updated"] == 1, result
    row = _rows(_export(client, token, project, OPEN_QUESTION))[0]
    assert (row["owner"], row["due_date"]) == (email, "2027-02-01")
    again = _import(client, token, project, OPEN_QUESTION, _csv(["code", "owner", "due_date"], [code, email, "2027-02-01"])).json()
    assert again["unchanged"] == 1
    cleared = _import(client, token, project, OPEN_QUESTION, _csv(["code", "owner"], [code, ""]), apply=True).json()
    assert cleared["updated"] == 1
    assert _rows(_export(client, token, project, OPEN_QUESTION))[0]["owner"] == ""


def test_a_guiding_principle_owner_is_an_email_and_an_unknown_one_is_that_rows_error(world):
    client, _, project, token = world
    principle = _create_guiding_principle(client, token, project["id"])
    email = client.get("/api/v1/auth/me", headers=auth_headers(token)).json()["email"]
    code = principle["unique_code"]
    assert _import(client, token, project, GUIDING_PRINCIPLE, _csv(["code", "owner"], [code, email]), apply=True).json()["updated"] == 1
    assert _rows(_export(client, token, project, GUIDING_PRINCIPLE))[0]["owner"] == email
    bad = _import(client, token, project, GUIDING_PRINCIPLE, _csv(["code", "owner"], [code, "nobody@example.com"])).json()
    assert bad["failed"] == 1


def test_a_pain_point_type_is_a_name_and_an_unknown_one_is_that_rows_error(world):
    client, _, project, token = world
    pain_point = _create_pain_point(client, token, project["id"])
    rows = _rows(_export(client, token, project, PAIN_POINT))
    assert rows[0]["type"] == "Market"
    columns = client.get(f"{_base(project, PAIN_POINT)}/columns", headers=auth_headers(token)).json()
    assert "Market" in next(c for c in columns["columns"] if c["key"] == "type")["choices"]
    code = pain_point["unique_code"]
    types = client.get(f"{_module(project, PAIN_POINT).rsplit('/', 1)[0]}/pain-point-types", headers=auth_headers(token)).json()
    other = next(t["name"] for t in types if t["name"] != "Market")
    assert _import(client, token, project, PAIN_POINT, _csv(["code", "type"], [code, other]), apply=True).json()["updated"] == 1
    assert _rows(_export(client, token, project, PAIN_POINT))[0]["type"] == other
    bad = _import(client, token, project, PAIN_POINT, _csv(["code", "type"], [code, "Nonsense"])).json()
    assert bad["failed"] == 1 and "Unknown Pain Point type" in bad["rows"][0]["message"]


def test_a_pain_point_intentional_flag_and_priority_round_trip(world):
    client, _, project, token = world
    pain_point = _create_pain_point(client, token, project["id"])
    code = pain_point["unique_code"]
    assert _rows(_export(client, token, project, PAIN_POINT))[0]["is_intentional"] == "false"
    result = _import(client, token, project, PAIN_POINT, _csv(["code", "is_intentional", "priority"], [code, "yes", "High"]), apply=True).json()
    assert result["updated"] == 1
    got = _get(client, token, project, PAIN_POINT, pain_point["id"])
    assert got["is_intentional"] is True and got["priority"] == "high"
    assert _import(client, token, project, PAIN_POINT, _csv(["code", "priority"], [code, "Urgent"])).json()["failed"] == 1


def test_a_plain_member_may_create_but_not_update_and_a_manager_may_assign_an_owner(world, client):
    _, org, project, token = world
    _, member_token = _add_plain_member(client, token, org["id"], project["id"], f"cs-member-{uuid.uuid4().hex[:6]}@example.com")
    pain_point = _create_pain_point(client, token, project["id"])
    update = _import(client, member_token, project, PAIN_POINT, _csv(["code", "impact"], [pain_point["unique_code"], "x"]), apply=True)
    assert update.status_code == 200 and update.json()["failed"] == 1
    assert "permission" in update.json()["rows"][0]["message"]
    assert client.get(f"{_base(project, PAIN_POINT)}/columns", headers=auth_headers(member_token)).json()["can_import"] is True

    email = client.get("/api/v1/auth/me", headers=auth_headers(member_token)).json()["email"]
    create = _import(
        client, member_token, project, PAIN_POINT, _csv(["code", "title", "type", "owner"], ["", "Mine", "Market", email]), apply=True,
    ).json()
    assert create["created"] == 0 and "Pain Point Manager" in create["rows"][0]["message"]
    plain = _import(client, member_token, project, PAIN_POINT, _csv(["code", "title", "type"], ["", "Mine", "Market"]), apply=True).json()
    assert plain["created"] == 1


def test_an_organisation_strategy_is_not_in_the_project_table(world):
    client, org, project, token = world
    _create_org_strategy(client, token, org["id"])
    own = _create_strategy(client, token, project["id"])
    assert [r["code"] for r in _rows(_export(client, token, project, STRATEGY))] == [own["unique_code"]]


def test_the_archived_filter_widens_the_export_and_an_unknown_filter_is_refused(world):
    client, _, project, token = world
    kept, archived = _create_pain_point(client, token, project["id"]), _create_pain_point(client, token, project["id"])
    assert client.post(f"{_module(project, PAIN_POINT)}/{archived['id']}/archive", headers=auth_headers(token)).status_code == 200
    assert [r["code"] for r in _rows(_export(client, token, project, PAIN_POINT))] == [kept["unique_code"]]
    assert len(_rows(_export(client, token, project, PAIN_POINT, include_archived="true"))) == 2
    assert _export(client, token, project, PAIN_POINT, nonsense="1").status_code == 422


def test_the_export_takes_the_tag_filter(world):
    client, _, project, token = world
    tagged, _ = _create_strategy(client, token, project["id"]), _create_strategy(client, token, project["id"])
    resp = client.post(
        f"/api/v1/projects/{project['id']}/artefacts/strategy/{tagged['id']}/tags", json={"name": "ops"}, headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    rows = _rows(_export(client, token, project, STRATEGY, tag="ops"))
    assert [r["code"] for r in rows] == [tagged["unique_code"]]
    assert rows[0]["tags"] == "ops"


def test_a_value_too_long_for_its_column_is_that_rows_error_not_a_failed_import(world):
    client, _, project, token = world
    text = _csv(["code", "title", "type"], ["", "x" * 400, "Market"], ["", "Fine", "Market"])
    result = _import(client, token, project, PAIN_POINT, text, apply=True)
    assert result.status_code == 200, result.text
    body = result.json()
    assert (body["created"], body["failed"]) == (1, 1)
    assert "too long" in body["rows"][0]["message"]


def test_the_endpoints_still_enforce_the_same_rules_after_the_shared_write_path(world):
    client, _, project, token = world
    strategy = _create_strategy(client, token, project["id"])
    assert _get(client, token, project, STRATEGY, strategy["id"])["version_number"] == 1
    put = client.put(
        f"{_module(project, STRATEGY)}/{strategy['id']}",
        json={"title": "T2", "objective": "O2", "priority": "high", "time_horizon": "long_term"}, headers=auth_headers(token),
    )
    assert put.status_code == 200 and put.json()["version_number"] == 2
    _advance_strategy_to_active(client, token, project["id"], strategy["id"])
    locked = client.put(
        f"{_module(project, STRATEGY)}/{strategy['id']}",
        json={"title": "T3", "objective": "O3", "priority": "high", "time_horizon": "long_term"}, headers=auth_headers(token),
    )
    assert locked.status_code == 409 and "past review" in locked.json()["detail"]
    types = _market_pain_point_type_id(client, token, project["id"])
    bad = client.post(
        f"{_module(project, PAIN_POINT)}", json={"pain_point_type_id": str(uuid.uuid4()), "title": "x"}, headers=auth_headers(token),
    )
    assert bad.status_code == 400 and types


# --- the filters the list pages offer reach the export ---------------------------------------------------------------


def test_status_priority_and_search_narrow_the_export_as_they_narrow_the_page(world):
    client, _, project, token = world
    active = _create_strategy(client, token, project["id"], title="Alpha plan", priority="high")
    _advance_strategy_to_active(client, token, project["id"], active["id"])
    draft = _create_strategy(client, token, project["id"], title="Beta plan", priority="low")
    codes = functools.partial(_codes, client, token, project, STRATEGY)
    assert codes(status="active") == {active["unique_code"]}
    assert codes(priority="low") == {draft["unique_code"]}
    assert codes(search="beta") == {draft["unique_code"]}
    assert codes(search=active["unique_code"].lower()) == {active["unique_code"]}
    assert codes(status="active", priority="low") == set()
    assert _export(client, token, project, STRATEGY, status="nonsense").status_code == 422


def test_pain_point_open_intentional_and_scored_filters(world):
    client, _, project, token = world
    plain = _create_pain_point(client, token, project["id"], title="Plain")
    flagged = _create_pain_point(client, token, project["id"], title="By design")
    closed = _create_pain_point(client, token, project["id"], title="Rejected")
    base = _module(project, PAIN_POINT)
    assert client.post(f"{base}/{closed['id']}/triage", json={}, headers=auth_headers(token)).status_code == 200
    assert client.post(f"{base}/{closed['id']}/reject", json={"comment": "no"}, headers=auth_headers(token)).status_code == 200
    put = client.put(
        f"{base}/{flagged['id']}", json={
            "pain_point_type_id": flagged["pain_point_type_id"], "title": "By design", "priority": "medium", "is_intentional": True,
        }, headers=auth_headers(token),
    )
    assert put.status_code == 200, put.text
    codes = functools.partial(_codes, client, token, project, PAIN_POINT)
    assert codes(open_only="true") == {plain["unique_code"], flagged["unique_code"]}
    assert codes(hide_intentional="true") == {plain["unique_code"], closed["unique_code"]}
    assert codes(only_intentional="true") == {flagged["unique_code"]}
    assert codes(scored="no") == {plain["unique_code"], flagged["unique_code"], closed["unique_code"]}
    assert codes(scored="yes") == set() and codes(blockers_only="true") == set()
    assert _export(client, token, project, PAIN_POINT, scored="maybe").status_code == 422
    assert _export(client, token, project, PAIN_POINT, scored="yes", rollup="bogus").status_code == 422


def test_future_state_and_open_question_page_toggles_reach_the_export(world):
    client, _, project, token = world
    measured = _create_future_state(client, token, project["id"], title="Measured", success_measures="NPS 60", target_date="2020-01-01")
    bare = _create_future_state(client, token, project["id"], title="Bare")
    fs = functools.partial(_codes, client, token, project, FUTURE_STATE)
    assert fs(no_measures_only="true") == {bare["unique_code"]}
    assert fs(target_passed_only="true") == {measured["unique_code"]}
    assert fs(roadmap_only="true") == {measured["unique_code"], bare["unique_code"]}

    overdue = _create_open_question(client, token, project["id"], question="Late one", due_date="2020-01-01")
    fresh = _create_open_question(client, token, project["id"], question="Fresh one")
    oq = functools.partial(_codes, client, token, project, OPEN_QUESTION)
    assert oq(overdue_only="true") == {overdue["unique_code"]}
    assert oq(unowned_only="true") == {overdue["unique_code"], fresh["unique_code"]}
    assert oq(open_only="true") == {overdue["unique_code"], fresh["unique_code"]}
    assert oq(search="fresh") == {fresh["unique_code"]}
