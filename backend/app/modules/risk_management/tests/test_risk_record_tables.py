"""Tests for the Risk record table: the register exports as the CSV it imports, a row with a code updates that
risk through the edit endpoint's own path (scoring-level validation, the accepted-risk content lock, a new version,
the Risk Manager gate), a blank code creates one starting `Identified`, and a file never moves a risk through its
lifecycle. Each test builds its own organisation, so none depends on state left by another test.
"""

from __future__ import annotations

import csv
import io

from app.modules.risk_management.tests._helpers import add_member, create_risk, levels, project_base, setup
from app.modules.risk_management.tests.test_risk_lifecycle import _move, _score, _score_and_create, _walk
from tests.conftest import auth_headers

RISK = "risk"


def _base(project: dict) -> str:
    return f"/api/v1/projects/{project['id']}/records/{RISK}"


def _export(client, token, project, **params):
    return client.get(f"{_base(project)}/export", params=params, headers=auth_headers(token))


def _rows(resp) -> list[dict]:
    assert resp.status_code == 200, resp.text
    return list(csv.DictReader(io.StringIO(resp.content.decode("utf-8-sig"))))


def _import(client, token, project, text: str, *, apply: bool = False):
    return client.post(
        f"{_base(project)}/import", params={"dry_run": "false" if apply else "true"},
        files={"file": ("records.csv", text.encode("utf-8"), "text/csv")}, headers=auth_headers(token),
    )


def _csv(header: list[str], *rows: list[str]) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(header)
    writer.writerows(rows)
    return out.getvalue()


def _get(client, token, project, risk_id) -> dict:
    resp = client.get(f"{project_base(project['id'])}/risks/{risk_id}", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_the_register_exports_with_codes_and_reimporting_it_unchanged_changes_nothing(client, admin_token):
    _, project, token = setup(client, admin_token, "Risk Tables Roundtrip Co")
    first, second = create_risk(client, token, project["id"]), create_risk(client, token, project["id"], title="Second")
    resp = _export(client, token, project)
    rows = _rows(resp)
    assert resp.headers["x-record-count"] == "2"
    assert {r["code"] for r in rows} == {first["unique_code"], second["unique_code"]}
    assert {r["status"] for r in rows} == {"Identified"}
    text = resp.content.decode("utf-8-sig")
    preview = _import(client, token, project, text).json()
    assert (preview["created"], preview["updated"], preview["unchanged"], preview["failed"]) == (0, 0, 2, 0), preview


def test_editing_one_cell_updates_that_risk_as_a_new_version_and_a_preview_writes_nothing(client, admin_token):
    _, project, token = setup(client, admin_token, "Risk Tables Edit Co")
    risk = create_risk(client, token, project["id"])
    text = _csv(["code", "cause"], [risk["unique_code"], "Sole supplier went bankrupt"])
    preview = _import(client, token, project, text).json()
    assert preview["updated"] == 1 and preview["rows"][0]["changes"][0]["column"] == "cause"
    assert _get(client, token, project, risk["id"])["cause"] != "Sole supplier went bankrupt"
    assert _import(client, token, project, text, apply=True).json()["updated"] == 1
    after = _get(client, token, project, risk["id"])
    assert after["cause"] == "Sole supplier went bankrupt" and after["version_number"] == risk["version_number"] + 1


def test_a_blank_code_creates_an_identified_risk_with_its_own_code(client, admin_token):
    _, project, token = setup(client, admin_token, "Risk Tables Create Co")
    text = _csv(["code", "title", "statement"], ["", "From a file", "If X then Y"])
    assert _import(client, token, project, text).json()["created"] == 1
    assert _rows(_export(client, token, project)) == [], "a preview must not create"
    assert _import(client, token, project, text, apply=True).json()["created"] == 1
    row = _rows(_export(client, token, project))[0]
    assert (row["title"], row["status"]) == ("From a file", "Identified") and row["code"].startswith("RSK-")


def test_a_create_without_a_title_is_that_rows_error(client, admin_token):
    _, project, token = setup(client, admin_token, "Risk Tables Required Co")
    result = _import(client, token, project, _csv(["code", "statement"], ["", "no title"])).json()
    assert result["created"] == 0 and result["failed"] == 1


def test_levels_are_written_by_name_rate_the_risk_and_an_unknown_level_is_that_rows_error(client, admin_token):
    _, project, token = setup(client, admin_token, "Risk Tables Levels Co")
    risk = create_risk(client, token, project["id"])
    code = risk["unique_code"]
    columns = client.get(f"{_base(project)}/columns", headers=auth_headers(token)).json()["columns"]
    assert "Likely" in next(c for c in columns if c["key"] == "inherent_likelihood")["choices"]
    text = _csv(["code", "inherent_likelihood", "inherent_consequence"], [code, "Likely", "Major"])
    assert _import(client, token, project, text, apply=True).json()["updated"] == 1
    row = _rows(_export(client, token, project))[0]
    assert (row["inherent_likelihood"], row["inherent_consequence"]) == ("Likely", "Major")
    assert row["inherent_rating"] != "" and row["residual_rating"] == ""
    assert _import(client, token, project, text).json()["unchanged"] == 1
    bad = _import(client, token, project, _csv(["code", "inherent_likelihood"], [code, "Nonsense"])).json()
    assert bad["failed"] == 1 and "likelihood level" in bad["rows"][0]["message"]
    cleared = _import(client, token, project, _csv(["code", "inherent_likelihood"], [code, ""]), apply=True).json()
    assert cleared["updated"] == 1
    assert _get(client, token, project, risk["id"])["inherent_likelihood_level_id"] is None
    assert levels(client, token, project["id"])["likelihood"]["Likely"]


def test_type_strategy_review_date_and_owner_round_trip_and_clear(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Tables Fields Co")
    risk = create_risk(client, token, project["id"])
    code = risk["unique_code"]
    email = client.get("/api/v1/auth/me", headers=auth_headers(token)).json()["email"]
    header = ["code", "type", "treatment_strategy", "review_date", "owner"]
    result = _import(client, token, project, _csv(header, [code, "Safety", "Mitigate", "2027-02-01", email]), apply=True).json()
    assert result["updated"] == 1, result
    row = _rows(_export(client, token, project))[0]
    assert (row["type"], row["treatment_strategy"], row["review_date"], row["owner"]) == ("Safety", "Mitigate", "2027-02-01", email)
    assert _import(client, token, project, _csv(header, [code, "Safety", "Mitigate", "2027-02-01", email])).json()["unchanged"] == 1
    bad = _import(client, token, project, _csv(["code", "type"], [code, "Nonsense"])).json()
    assert bad["failed"] == 1 and "Unknown Risk type" in bad["rows"][0]["message"]
    cleared = _import(client, token, project, _csv(["code", "owner", "review_date"], [code, "", ""]), apply=True).json()
    assert cleared["updated"] == 1
    after = _get(client, token, project, risk["id"])
    assert after["owner"] is None and after["review_date"] is None


def test_status_is_exported_by_label_and_never_written_by_a_file(client, admin_token):
    _, project, token = setup(client, admin_token, "Risk Tables Status Co")
    risk = create_risk(client, token, project["id"])
    result = _import(client, token, project, _csv(["code", "status"], [risk["unique_code"], "Closed"]), apply=True).json()
    assert result["updated"] == 0 and "status" in result["ignored_columns"]
    assert _get(client, token, project, risk["id"])["status"] == "identified"


def test_an_accepted_risks_assessment_cannot_be_edited_by_a_file(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Tables Accepted Co")
    risk = _score_and_create(client, token, project)
    _walk(client, token, project["id"], risk["id"], "assessed")
    _score(client, token, project, risk, residual=True)
    from app.modules.risk_management.tests.test_risk_lifecycle import _url

    client.put(_url(project["id"], risk["id"]), json={"acceptance_criteria": "Within appetite."}, headers=auth_headers(token))
    assert _move(client, token, project["id"], risk["id"], "accepted", comment="Signed off").status_code == 200
    result = _import(client, token, project, _csv(["code", "acceptance_criteria"], [risk["unique_code"], "Changed"]), apply=True).json()
    assert result["failed"] == 1 and "cannot be edited in place" in result["rows"][0]["message"]
    assert _get(client, token, project, risk["id"])["acceptance_criteria"] == "Within appetite."
    unlocked = _import(client, token, project, _csv(["code", "cause"], [risk["unique_code"], "New cause"]), apply=True).json()
    assert unlocked["updated"] == 1


def test_a_plain_member_may_create_from_a_file_but_not_update(client, admin_token):
    org, project, token = setup(client, admin_token, "Risk Tables Member Co")
    risk = create_risk(client, token, project["id"])
    _, member = add_member(client, token, org["id"], project["id"], "risk-tables-member@example.com")
    columns = client.get(f"{_base(project)}/columns", headers=auth_headers(member)).json()
    assert columns["can_import"] is True
    created = _import(client, member, project, _csv(["code", "title"], ["", "Member's risk"]), apply=True).json()
    assert created["created"] == 1
    refused = _import(client, member, project, _csv(["code", "cause"], [risk["unique_code"], "x"]), apply=True).json()
    assert refused["failed"] == 1 and refused["updated"] == 0


def test_the_registers_filters_reach_the_export(client, admin_token):
    _, project, token = setup(client, admin_token, "Risk Tables Filters Co")
    kept = create_risk(client, token, project["id"], title="Kept risk", review_date="2020-01-01")
    create_risk(client, token, project["id"], title="Other risk")
    assert [r["code"] for r in _rows(_export(client, token, project, review_overdue="true"))] == [kept["unique_code"]]
    assert [r["code"] for r in _rows(_export(client, token, project, search="kept"))] == [kept["unique_code"]]
    assert len(_rows(_export(client, token, project, untreated="true"))) == 2
    assert _rows(_export(client, token, project, status="closed")) == []
    assert _export(client, token, project, nonsense="1").status_code == 422
    client.post(f"{project_base(project['id'])}/risks/{kept['id']}/archive", headers=auth_headers(token))
    assert len(_rows(_export(client, token, project))) == 1
    assert len(_rows(_export(client, token, project, include_archived="true"))) == 2
