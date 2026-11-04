"""Tests for the request record tables: the list exports as the CSV it imports (project and organisation inbox), a row
with a code updates that request through the edit endpoint's own path (a new version, the triager gate), a blank code
creates one starting New, a file never moves a request through its lifecycle, the export follows the list's filters, and
a project that restricted submission refuses a member's import. Each test builds its own organisation."""

from __future__ import annotations

import csv
import io

from app.modules.product_feedback.tests._helpers import (
    add_member,
    create_inbox_request,
    create_request,
    grant_project_role,
    org_base,
    project_base,
    setup,
    transition,
)
from tests.conftest import auth_headers

REQUEST = "enhancement_request"


def _project_tier(project: dict) -> str:
    return f"/api/v1/projects/{project['id']}/records/{REQUEST}"


def _org_tier(org: dict) -> str:
    return f"/api/v1/orgs/{org['id']}/records/{REQUEST}"


def _rows(resp) -> list[dict]:
    assert resp.status_code == 200, resp.text
    return list(csv.DictReader(io.StringIO(resp.content.decode("utf-8-sig"))))


def _import(client, token, tier, text: str, *, apply: bool = False):
    return client.post(
        f"{tier}/import", params={"dry_run": "false" if apply else "true"},
        files={"file": ("records.csv", text.encode("utf-8"), "text/csv")}, headers=auth_headers(token),
    )


def _csv(header: list[str], *rows: list[str]) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(header)
    writer.writerows(rows)
    return out.getvalue()


def test_the_list_exports_with_codes_and_status_and_a_filtered_export_keeps_only_what_the_page_shows(client, admin_token):
    _, project, token = setup(client, admin_token, "Feedback Tables Export Co")
    first = create_request(client, token, project["id"], title="Keep me")
    second = create_request(client, token, project["id"], title="Declined one")
    transition(client, token, project_base(project["id"]), second["id"], "declined", "Not now.")
    resp = client.get(f"{_project_tier(project)}/export", headers=auth_headers(token))
    rows = _rows(resp)
    assert {r["code"]: r["status"] for r in rows} == {first["unique_code"]: "New", second["unique_code"]: "Declined"}
    assert next(r for r in rows if r["code"] == second["unique_code"])["decline_reason"] == "Not now."
    open_rows = _rows(client.get(f"{_project_tier(project)}/export", params={"open_only": "true"}, headers=auth_headers(token)))
    assert [r["code"] for r in open_rows] == [first["unique_code"]]


def test_a_row_with_a_code_updates_the_request_as_a_new_version(client, admin_token):
    _, project, token = setup(client, admin_token, "Feedback Tables Update Co")
    request = create_request(client, token, project["id"])
    text = _csv(["code", "description"], [request["unique_code"], "Reworded through a file."])
    preview = _import(client, token, _project_tier(project), text)
    assert preview.status_code == 200, preview.text
    applied = _import(client, token, _project_tier(project), text, apply=True)
    assert applied.status_code == 200, applied.text
    current = client.get(f"{project_base(project['id'])}/requests/{request['id']}", headers=auth_headers(token)).json()
    assert current["description"] == "Reworded through a file." and current["version_number"] == 2
    assert current["title"] == request["title"]


def test_a_blank_code_creates_a_new_request_and_a_file_cannot_set_the_status(client, admin_token):
    _, project, token = setup(client, admin_token, "Feedback Tables Create Co")
    text = _csv(["code", "title", "description", "status"], ["", "From a file", "Created by import.", "Delivered"])
    applied = _import(client, token, _project_tier(project), text, apply=True)
    assert applied.status_code == 200, applied.text
    listed = client.get(project_base(project["id"]) + "/requests", headers=auth_headers(token)).json()
    assert len(listed) == 1
    assert listed[0]["title"] == "From a file" and listed[0]["status"] == "new" and listed[0]["unique_code"] == "ENH-001"


def test_an_unknown_code_is_a_row_error_not_a_new_request(client, admin_token):
    _, project, token = setup(client, admin_token, "Feedback Tables Unknown Co")
    text = _csv(["code", "title"], ["ENH-099", "Ghost"])
    resp = _import(client, token, _project_tier(project), text, apply=True)
    assert resp.status_code == 200, resp.text
    assert client.get(project_base(project["id"]) + "/requests", headers=auth_headers(token)).json() == []


def test_a_plain_member_cannot_update_through_a_file(client, admin_token):
    org, project, admin = setup(client, admin_token, "Feedback Tables Gate Co")
    _, member = add_member(client, admin, org["id"], project["id"], "member.tables@example.com")
    request = create_request(client, admin, project["id"])
    text = _csv(["code", "description"], [request["unique_code"], "Sneaky."])
    resp = _import(client, member, _project_tier(project), text, apply=True)
    assert resp.status_code in (403, 200)
    current = client.get(f"{project_base(project['id'])}/requests/{request['id']}", headers=auth_headers(admin)).json()
    assert current["description"] == request["description"]


def test_a_member_cannot_import_new_requests_when_submission_is_restricted(client, admin_token):
    org, project, admin = setup(client, admin_token, "Feedback Tables Policy Co")
    triager_id, triager = add_member(client, admin, org["id"], project["id"], "triager.tables@example.com")
    grant_project_role(client, admin, project["id"], triager_id, "feedback_triager")
    _, member = add_member(client, admin, org["id"], project["id"], "member.policy.tables@example.com")
    client.put(project_base(project["id"]) + "/settings", json={"submission_policy": "triagers"}, headers=auth_headers(admin))
    text = _csv(["code", "title"], ["", "Imported by a member"])
    _import(client, member, _project_tier(project), text, apply=True)
    assert client.get(project_base(project["id"]) + "/requests", headers=auth_headers(admin)).json() == []
    _import(client, triager, _project_tier(project), text, apply=True)
    assert len(client.get(project_base(project["id"]) + "/requests", headers=auth_headers(admin)).json()) == 1


def test_the_inbox_exports_and_imports_at_organisation_level(client, admin_token):
    org, project, token = setup(client, admin_token, "Feedback Tables Inbox Co")
    inbox = create_inbox_request(client, token, org["id"], title="Inbox idea")
    create_request(client, token, project["id"], title="A project request")
    rows = _rows(client.get(f"{_org_tier(org)}/export", headers=auth_headers(token)))
    assert [r["title"] for r in rows] == ["Inbox idea"]
    code = rows[0]["code"]  # an organisation's record is always named with the organisation's code
    assert code.endswith(f"-{inbox['unique_code']}") and code != inbox["unique_code"]

    text = _csv(["code", "title", "description"], [code, "Inbox idea", "Edited"], ["", "Second idea", "New"])
    applied = _import(client, token, _org_tier(org), text, apply=True)
    assert applied.status_code == 200, applied.text
    titles = {r["title"]: r for r in client.get(org_base(org["id"]) + "/requests", headers=auth_headers(token)).json()}
    assert set(titles) == {"Inbox idea", "Second idea"}
    assert titles["Inbox idea"]["description"] == "Edited" and titles["Second idea"]["status"] == "new"
    assert len(client.get(project_base(project["id"]) + "/requests", headers=auth_headers(token)).json()) == 1


def test_scoring_levels_export_by_name_with_the_derived_score_and_import_by_name(client, admin_token):
    _, project, token = setup(client, admin_token, "Feedback Tables Score Co")
    pid = project["id"]
    request = create_request(client, token, pid)
    rows = _rows(client.get(f"{_project_tier(project)}/export", headers=auth_headers(token)))
    assert rows[0]["score"] == "" and rows[0]["reach"] == ""  # unscored

    text = _csv(
        ["code", "reach", "impact", "confidence", "effort"], [request["unique_code"], "Many", "High", "High", "Medium"],
    )
    applied = _import(client, token, _project_tier(project), text, apply=True)
    assert applied.status_code == 200, applied.text
    shown = client.get(f"{project_base(pid)}/requests/{request['id']}", headers=auth_headers(token)).json()
    assert shown["score"]["raw"] == 3 and shown["version_number"] == 2
    row = _rows(client.get(f"{_project_tier(project)}/export", headers=auth_headers(token)))[0]
    assert (row["reach"], row["effort"], row["score"], row["score_band"]) == ("Many", "Medium", "3", "High")

    cleared = _import(client, token, _project_tier(project), _csv(["code", "effort"], [request["unique_code"], ""]), apply=True)
    assert cleared.status_code == 200, cleared.text
    assert client.get(f"{project_base(pid)}/requests/{request['id']}", headers=auth_headers(token)).json()["score"] is None


def test_an_unknown_level_name_is_a_row_error_and_changes_nothing(client, admin_token):
    _, project, token = setup(client, admin_token, "Feedback Tables Bad Level Co")
    request = create_request(client, token, project["id"])
    preview = _import(client, token, _project_tier(project), _csv(["code", "effort"], [request["unique_code"], "Gigantic"]))
    assert preview.status_code == 200, preview.text
    assert "Gigantic" in preview.text
    _import(client, token, _project_tier(project), _csv(["code", "effort"], [request["unique_code"], "Gigantic"]), apply=True)
    current = client.get(f"{project_base(project['id'])}/requests/{request['id']}", headers=auth_headers(token)).json()
    assert current["version_number"] == 1 and "effort" not in current["levels"]


def test_ease_is_an_editable_level_column_and_demand_a_read_only_derived_one(client, admin_token):
    _, project, token = setup(client, admin_token, "Feedback Tables Ease Demand Co")
    pid = project["id"]
    request = create_request(client, token, pid)
    row = _rows(client.get(f"{_project_tier(project)}/export", headers=auth_headers(token)))[0]
    assert row["ease"] == "" and row["demand"] == "Single voice"  # derived: the lowest level with no requesters

    text = _csv(["code", "ease", "demand"], [request["unique_code"], "Easy", "Widespread"])
    applied = _import(client, token, _project_tier(project), text, apply=True)
    assert applied.status_code == 200, applied.text
    shown = client.get(f"{project_base(pid)}/requests/{request['id']}", headers=auth_headers(token)).json()
    assert set(shown["levels"]) == {"ease"}  # the demand cell is not an editable column: it set nothing
    row = _rows(client.get(f"{_project_tier(project)}/export", headers=auth_headers(token)))[0]
    assert row["ease"] == "Easy" and row["demand"] == "Single voice"
