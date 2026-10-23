"""Tests for the Stakeholders & Personas record tables: Personas, Stakeholders, Stakeholder Groups, Needs,
Engagements and Research Findings export their list as the CSV they import, a row with a code updates that record
through the type's own write path, a blank code creates one, personal data follows the organisation's policy, and the
organisation's own records are listed with the organisation-qualified code and are never changed from a project.

Each test builds its own organisation, so none depends on state left by another test.
"""

from __future__ import annotations

import csv
import functools
import io
import uuid

import pytest

from app.modules.stakeholders.tests.test_engagement_api import _create as _create_engagement
from app.modules.stakeholders.tests.test_need_api import _create_need
from app.modules.stakeholders.tests.test_persona_api import (
    _add_member,
    _create_org_persona,
    _create_project_persona,
    _setup,
)
from app.modules.stakeholders.tests.test_research_extras_api import _research_setup
from app.modules.stakeholders.tests.test_stakeholder_api import _create_org_stakeholder, _create_project_stakeholder
from app.modules.stakeholders.tests.test_stakeholder_groups import _group
from tests.conftest import auth_headers

PERSONA, STAKEHOLDER, GROUP, NEED, ENGAGEMENT, FINDING = (
    "persona", "stakeholder", "stakeholder_group", "stakeholder_need", "engagement", "research_finding",
)
BASE = "/api/v1/projects/{pid}/modules/stakeholders"
API_PATH = {
    PERSONA: "personas", STAKEHOLDER: "stakeholders", GROUP: "stakeholder-groups", NEED: "needs", ENGAGEMENT: "engagements",
    FINDING: "findings",
}


def _records(project: dict, record_type: str) -> str:
    return f"/api/v1/projects/{project['id']}/records/{record_type}"


def _export(client, token, project, record_type, **params):
    return client.get(f"{_records(project, record_type)}/export", params=params, headers=auth_headers(token))


def _rows(resp) -> list[dict]:
    assert resp.status_code == 200, resp.text
    return list(csv.DictReader(io.StringIO(resp.content.decode("utf-8-sig"))))


def _import(client, token, project, record_type, text: str, *, apply: bool = False):
    return client.post(
        f"{_records(project, record_type)}/import", params={"dry_run": "false" if apply else "true"},
        files={"file": ("records.csv", text.encode("utf-8"), "text/csv")}, headers=auth_headers(token),
    )


def _csv(header: list[str], *rows: list[str]) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(header)
    writer.writerows(rows)
    return out.getvalue()


def _codes(client, token, project, record_type, **params) -> set[str]:
    return {r["code"] for r in _rows(_export(client, token, project, record_type, **params))}


def _get(client, token, project, record_type, record_id) -> dict:
    """One record as the API shows it (a group has no read-one endpoint, so it is found in the list)."""
    url = f"{BASE.format(pid=project['id'])}/{API_PATH[record_type]}"
    if record_type == GROUP:
        resp = client.get(url, headers=auth_headers(token))
        assert resp.status_code == 200, resp.text
        return next(g for g in resp.json() if g["id"] == record_id)
    resp = client.get(f"{url}/{record_id}", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _allow_personal_data(client, org, token) -> None:
    """Lets the organisation's admins export and import every personal-data tag."""
    for tag in ("personal", "contact", "free_text_people"):
        resp = client.put(
            f"/api/v1/orgs/{org['id']}/record-sensitivity-policy/{tag}", json={"allowed": True}, headers=auth_headers(token),
        )
        assert resp.status_code in (200, 204), resp.text


@pytest.fixture
def world(client, admin_token):
    org, project, token = _setup(client, admin_token, f"SH Tables {uuid.uuid4().hex[:6]}")
    _allow_personal_data(client, org, token)
    return client, org, project, token


def _make(world, record_type: str, **extra) -> dict:
    """One record of `record_type` through the real endpoints."""
    client, _, project, token = world
    pid = project["id"]
    if record_type == PERSONA:
        return _create_project_persona(client, token, pid, **extra)
    if record_type == STAKEHOLDER:
        return _create_project_stakeholder(client, token, pid, **extra)
    if record_type == GROUP:
        return _group(client, token, BASE.format(pid=pid), extra.pop("name", f"Group {uuid.uuid4().hex[:5]}"), **extra)
    if record_type == NEED:
        return _create_need(client, token, pid, **extra)
    if record_type == ENGAGEMENT:
        return _create_engagement(client, token, pid, **extra)
    raise AssertionError(record_type)


#: type -> (the column a test edits, its new value, how the API names it)
EDITS = {
    PERSONA: ("goals", "Ship faster", "goals"),
    STAKEHOLDER: ("interests", "Fewer meetings", "interests"),
    GROUP: ("description", "Everyone on the shop floor", "description"),
    NEED: ("rationale", "Safety rules require it", "rationale"),
    ENGAGEMENT: ("purpose", "Validate the prototype", "purpose"),
}
NAME_COLUMN = {PERSONA: "name", STAKEHOLDER: "name", GROUP: "name", NEED: "name", ENGAGEMENT: "title"}


@pytest.mark.parametrize("record_type", list(EDITS))
def test_a_list_exports_with_its_codes_and_reimporting_it_unchanged_changes_nothing(world, record_type):
    client, _, project, token = world
    first, second = _make(world, record_type), _make(world, record_type)
    resp = _export(client, token, project, record_type)
    rows = _rows(resp)
    assert resp.headers["x-record-count"] == "2"
    assert {r["code"] for r in rows} == {first["unique_code"], second["unique_code"]}
    text = resp.content.decode("utf-8-sig")
    preview = _import(client, token, project, record_type, text).json()
    assert (preview["created"], preview["updated"], preview["unchanged"], preview["failed"]) == (0, 0, 2, 0), preview
    assert _import(client, token, project, record_type, text, apply=True).json()["updated"] == 0


@pytest.mark.parametrize("record_type", list(EDITS))
def test_editing_one_cell_updates_that_record_and_leaves_the_other_alone(world, record_type):
    client, _, project, token = world
    column, value, api_field = EDITS[record_type]
    target, other = _make(world, record_type), _make(world, record_type)
    untouched = {r["code"]: r[column] for r in _rows(_export(client, token, project, record_type))}[other["unique_code"]]
    text = _csv(["code", column], [target["unique_code"], value], [other["unique_code"], untouched])
    preview = _import(client, token, project, record_type, text).json()
    assert preview["updated"] == 1 and preview["unchanged"] == 1, preview
    change = preview["rows"][0]["changes"][0]
    assert (change["column"], change["after"]) == (column, value)
    assert _get(client, token, project, record_type, target["id"])[api_field] != value, "a preview must not write"

    assert _import(client, token, project, record_type, text, apply=True).json()["updated"] == 1
    assert _get(client, token, project, record_type, target["id"])[api_field] == value
    assert _get(client, token, project, record_type, other["id"])[api_field] == untouched


@pytest.mark.parametrize("record_type", list(EDITS))
def test_a_blank_code_creates_a_record_with_its_own_code(world, record_type):
    client, _, project, token = world
    header, row = ["code", NAME_COLUMN[record_type]], ["", "From a file"]
    if record_type == ENGAGEMENT:
        header += ["channel", "engagement_date"]
        row += ["Interview", "2026-03-04"]
    text = _csv(header, row)
    assert _import(client, token, project, record_type, text).json()["created"] == 1
    assert _rows(_export(client, token, project, record_type)) == [], "a preview must not create"
    assert _import(client, token, project, record_type, text, apply=True).json()["created"] == 1
    created = _rows(_export(client, token, project, record_type))
    assert [r[NAME_COLUMN[record_type]] for r in created] == ["From a file"] and created[0]["code"]
    if "status" in created[0]:
        assert created[0]["status"] == "Draft"


@pytest.mark.parametrize("record_type", list(EDITS))
def test_a_create_without_its_required_columns_is_that_rows_error(world, record_type):
    client, _, project, token = world
    column = EDITS[record_type][0]
    result = _import(client, token, project, record_type, _csv(["code", column], ["", "just this"])).json()
    assert result["created"] == 0 and result["failed"] == 1 and result["rows"][0]["message"]


def test_status_is_exported_by_label_and_a_file_never_moves_a_record_through_its_lifecycle(world):
    client, _, project, token = world
    persona = _make(world, PERSONA)
    base = BASE.format(pid=project["id"])
    assert client.post(f"{base}/personas/{persona['id']}/activate", json={}, headers=auth_headers(token)).status_code == 200
    assert _rows(_export(client, token, project, PERSONA))[0]["status"] == "Active"
    result = _import(client, token, project, PERSONA, _csv(["code", "status"], [persona["unique_code"], "Retired"]), apply=True).json()
    assert result["updated"] == 0 and "status" in result["ignored_columns"]
    assert _get(client, token, project, PERSONA, persona["id"])["status"] == "active"


def test_a_persona_type_is_a_name_a_weight_is_a_number_and_an_owner_is_an_email(world):
    client, _, project, token = world
    persona = _make(world, PERSONA)
    code = persona["unique_code"]
    email = client.get("/api/v1/auth/me", headers=auth_headers(token)).json()["email"]
    types = client.get(f"{BASE.format(pid=project['id'])}/persona-types", headers=auth_headers(token)).json()
    secondary = next(t["name"] for t in types if t["name"] == "Secondary")
    result = _import(
        client, token, project, PERSONA, _csv(["code", "type", "weight", "owner"], [code, secondary, "2.5", email]), apply=True,
    ).json()
    assert result["updated"] == 1, result
    row = _rows(_export(client, token, project, PERSONA))[0]
    assert (row["type"], row["weight"], row["owner"]) == (secondary, "2.5", email)
    assert _import(client, token, project, PERSONA, _csv(["code", "type"], [code, "Nonsense"])).json()["failed"] == 1
    assert _import(client, token, project, PERSONA, _csv(["code", "weight"], [code, "heavy"])).json()["failed"] == 1
    cleared = _import(client, token, project, PERSONA, _csv(["code", "weight", "owner"], [code, "", ""]), apply=True).json()
    assert cleared["updated"] == 1
    assert (_rows(_export(client, token, project, PERSONA))[0]["weight"], _rows(_export(client, token, project, PERSONA))[0]["owner"]) == ("", "")


def test_the_organisations_personas_are_listed_with_the_qualified_code_and_cannot_be_changed_from_the_project(world):
    client, org, project, token = world
    own = _make(world, PERSONA)
    shared = _create_org_persona(client, token, org["id"], name="Shared archetype")
    rows = {r["name"]: r for r in _rows(_export(client, token, project, PERSONA))}
    assert rows["Shared archetype"]["scope"] == "Organisation" and rows[own["name"]]["scope"] == "Project"
    org_code = client.get(f"/api/v1/orgs/{org['id']}", headers=auth_headers(token)).json()["code"]
    assert rows["Shared archetype"]["code"] == f"{org_code}-{shared['unique_code']}"
    assert rows[own["name"]]["code"] == own["unique_code"]
    result = _import(
        client, token, project, PERSONA, _csv(["code", "goals"], [rows["Shared archetype"]["code"], "Changed from a project"]), apply=True,
    ).json()
    assert result["failed"] == 1 and "No record with the code" in result["rows"][0]["message"]
    assert _codes(client, token, project, PERSONA, include_org="false") == {own["unique_code"]}
    unchanged = _import(client, token, project, PERSONA, _export(client, token, project, PERSONA).content.decode("utf-8-sig")).json()
    assert unchanged["failed"] == 1 and unchanged["unchanged"] == 1, "an organisation row is reported, never written"


def test_a_stakeholders_personal_data_follows_the_organisation_policy(client, admin_token):
    org, project, token = _setup(client, admin_token, f"SH Policy {uuid.uuid4().hex[:6]}")
    stakeholder = _create_project_stakeholder(client, token, project["id"])
    columns = {c["key"]: c for c in client.get(f"{_records(project, STAKEHOLDER)}/columns", headers=auth_headers(token)).json()["columns"]}
    assert {k for k, c in columns.items() if c["sensitivity"] == "personal"} == {"name", "role", "organisation_group"}
    assert {k for k, c in columns.items() if c["sensitivity"] == "contact"} == {"contact_info", "availability_constraints"}
    assert columns["interests"]["sensitivity"] == "free_text_people"

    resp = _export(client, token, project, STAKEHOLDER)
    header = _rows(resp)[0]
    assert resp.headers["x-omitted-sensitivity"] == "contact,free_text_people,personal"
    assert not {"name", "role", "contact_info", "interests"} & set(header), "a fresh install leaks nothing"
    assert header["code"] == stakeholder["unique_code"] and "type" in header and "status" in header
    ignored = _import(
        client, token, project, STAKEHOLDER, _csv(["code", "name"], [stakeholder["unique_code"], "Renamed"]), apply=True,
    ).json()
    assert ignored["updated"] == 0 and "name" in ignored["ignored_columns"]
    created = _import(client, token, project, STAKEHOLDER, _csv(["code", "type"], ["", "Primary"]), apply=True).json()
    assert created["created"] == 0 and created["failed"] == 1, created

    _allow_personal_data(client, org, token)
    full = _rows(_export(client, token, project, STAKEHOLDER))[0]
    assert full["name"] == stakeholder["name"] and full["contact_info"] == stakeholder["contact_info"]
    renamed = _import(client, token, project, STAKEHOLDER, _csv(["code", "name"], [stakeholder["unique_code"], "Renamed"]), apply=True)
    assert renamed.json()["updated"] == 1
    assert _get(client, token, project, STAKEHOLDER, stakeholder["id"])["name"] == "Renamed"


def test_a_stakeholder_round_trips_every_personal_field_once_the_policy_allows_it(world):
    client, _, project, token = world
    stakeholder = _make(world, STAKEHOLDER)
    code = stakeholder["unique_code"]
    text = _csv(
        ["code", "name", "role", "contact_info", "target_cadence", "interests"],
        [code, "Pat Renamed", "Chief auditor", "pat@authority.example.com", "Weekly", "Clear evidence"],
    )
    result = _import(client, token, project, STAKEHOLDER, text, apply=True).json()
    assert result["updated"] == 1, result
    got = _get(client, token, project, STAKEHOLDER, stakeholder["id"])
    assert (got["name"], got["role"], got["target_cadence"], got["interests"]) == ("Pat Renamed", "Chief auditor", "weekly", "Clear evidence")
    assert _import(client, token, project, STAKEHOLDER, text).json()["unchanged"] == 1
    too_long = _import(client, token, project, STAKEHOLDER, _csv(["code", "role"], [code, "x" * 400])).json()
    assert too_long["failed"] == 1 and "role" in too_long["rows"][0]["message"]


def test_a_member_without_the_export_permission_never_gets_personal_columns_even_when_the_policy_allows_them(world, client):
    _, org, project, token = world
    _make(world, STAKEHOLDER)
    _, member_token = _add_member(client, token, org["id"], project["id"], f"sh-member-{uuid.uuid4().hex[:6]}@example.com")
    header = _rows(_export(client, member_token, project, STAKEHOLDER))[0]
    assert "name" not in header and "contact_info" not in header
    assert "name" in _rows(_export(client, token, project, STAKEHOLDER))[0]


def test_a_plain_member_may_export_but_cannot_create_or_update(world, client):
    _, org, project, token = world
    persona = _make(world, PERSONA)
    _, member_token = _add_member(client, token, org["id"], project["id"], f"sh-plain-{uuid.uuid4().hex[:6]}@example.com")
    assert _rows(_export(client, member_token, project, PERSONA))
    columns = client.get(f"{_records(project, PERSONA)}/columns", headers=auth_headers(member_token)).json()
    assert columns["can_import"] is False
    denied = _import(client, member_token, project, PERSONA, _csv(["code", "goals"], [persona["unique_code"], "x"]), apply=True)
    assert denied.status_code == 403


def test_the_groups_parent_is_a_path_and_membership_is_a_count(world):
    client, _, project, token = world
    base = BASE.format(pid=project["id"])
    parent = _group(client, token, base, "Customers")
    child = _group(client, token, base, "Acme", parent["id"], exclusive_children=True)
    stakeholder = _make(world, STAKEHOLDER)
    assert client.post(
        f"{base}/stakeholder-groups/{child['id']}/members", json={"stakeholder_id": stakeholder["id"]}, headers=auth_headers(token),
    ).status_code in (200, 201, 204)
    rows = {r["name"]: r for r in _rows(_export(client, token, project, GROUP))}
    assert (rows["Acme"]["parent"], rows["Acme"]["members"], rows["Acme"]["exclusive_children"]) == ("Customers", "1", "true")
    assert (rows["Customers"]["parent"], rows["Customers"]["members"]) == ("", "0")
    result = _import(client, token, project, GROUP, _csv(["code", "exclusive_children"], [child["unique_code"], "no"]), apply=True).json()
    assert result["updated"] == 1
    assert _get(client, token, project, GROUP, child["id"])["exclusive_children"] is False


def test_an_engagements_channel_date_facilitators_and_retention_round_trip(world):
    client, _, project, token = world
    engagement = _make(world, ENGAGEMENT)
    code = engagement["unique_code"]
    email = client.get("/api/v1/auth/me", headers=auth_headers(token)).json()["email"]
    result = _import(
        client, token, project, ENGAGEMENT,
        _csv(["code", "channel", "engagement_date", "facilitators", "consent_recorded", "retain_until"],
             [code, "Focus group", "2026-02-03", email, "yes", "2027-02-03"]),
        apply=True,
    ).json()
    assert result["updated"] == 1, result
    row = _rows(_export(client, token, project, ENGAGEMENT))[0]
    assert (row["channel"], row["engagement_date"], row["facilitators"], row["consent_recorded"], row["retain_until"]) == (
        "Focus group", "2026-02-03", email, "true", "2027-02-03",
    )
    assert _import(client, token, project, ENGAGEMENT, _csv(["code", "engagement_date"], [code, "03/02/2026"])).json()["failed"] == 1
    assert _import(client, token, project, ENGAGEMENT, _csv(["code", "channel"], [code, "Carrier pigeon"])).json()["failed"] == 1
    cleared = _import(client, token, project, ENGAGEMENT, _csv(["code", "facilitators", "retain_until"], [code, "", ""]), apply=True).json()
    assert cleared["updated"] == 1
    row = _rows(_export(client, token, project, ENGAGEMENT))[0]
    assert (row["facilitators"], row["retain_until"]) == ("", "")


def test_an_engagements_notes_and_summary_are_personal_data_and_follow_the_policy(client, admin_token):
    org, project, token = _setup(client, admin_token, f"SH Notes {uuid.uuid4().hex[:6]}")
    _create_engagement(client, token, project["id"], summary="Mentioned Jo by name", notes="Jo said no")
    header = _rows(_export(client, token, project, ENGAGEMENT))[0]
    assert "notes" not in header and "summary" not in header and header["title"]
    _allow_personal_data(client, org, token)
    full = _rows(_export(client, token, project, ENGAGEMENT))[0]
    assert (full["notes"], full["summary"]) == ("Jo said no", "Mentioned Jo by name")


def test_the_engagement_list_filters_reach_the_export(world):
    client, _, project, token = world
    call = _make(world, ENGAGEMENT, title="A call", channel="call")
    meeting = _make(world, ENGAGEMENT, title="A meeting", channel="meeting", engagement_date="2020-01-01")
    codes = functools.partial(_codes, client, token, project, ENGAGEMENT)
    assert codes(type="Call") == {call["unique_code"]} and codes(channel="meeting") == {meeting["unique_code"]}
    assert codes(date_to="2021-01-01") == {meeting["unique_code"]}
    assert codes(search="meeting") == {meeting["unique_code"]}
    assert _export(client, token, project, ENGAGEMENT, type="Carrier pigeon").status_code == 422


def test_a_finding_belongs_to_an_engagement_and_cannot_move(client, admin_token):
    org, project, token = _research_setup(client, admin_token, f"SH Findings {uuid.uuid4().hex[:6]}")
    world = (client, org, project, token)
    first, second = _make(world, ENGAGEMENT, title="First"), _make(world, ENGAGEMENT, title="Second")
    created = _import(
        client, token, project, FINDING,
        _csv(["code", "title", "description", "engagement"], ["", "Users skip step 3", "Seen in 4 of 5", first["unique_code"]]),
        apply=True,
    ).json()
    assert created["created"] == 1, created
    row = _rows(_export(client, token, project, FINDING))[0]
    assert (row["title"], row["engagement"]) == ("Users skip step 3", first["unique_code"])
    code = row["code"]
    assert _import(client, token, project, FINDING, _csv(["code", "title"], [code, "Users skip step three"]), apply=True).json()["updated"] == 1
    moved = _import(client, token, project, FINDING, _csv(["code", "engagement"], [code, second["unique_code"]])).json()
    assert moved["failed"] == 1 and "cannot be moved" in moved["rows"][0]["message"]
    unknown = _import(client, token, project, FINDING, _csv(["code", "title", "engagement"], ["", "x", "ENG-999"])).json()
    assert unknown["failed"] == 1 and "No engagement" in unknown["rows"][0]["message"]
    assert _import(client, token, project, FINDING, _csv(["code", "title"], ["", "No engagement named"])).json()["failed"] == 1
    assert _codes(client, token, project, FINDING, search="step three") == {code}


def test_the_research_extras_gate_hides_findings_until_they_are_switched_on(client, admin_token):
    _, project, token = _setup(client, admin_token, f"SH Gate {uuid.uuid4().hex[:6]}")
    assert _export(client, token, project, FINDING).status_code == 404


def test_persona_and_stakeholder_and_need_filters_reach_the_export(world):
    client, _, project, token = world
    base = BASE.format(pid=project["id"])
    active = _make(world, PERSONA, name="Active one")
    draft = _make(world, PERSONA, name="Draft one")
    assert client.post(f"{base}/personas/{active['id']}/activate", json={}, headers=auth_headers(token)).status_code == 200
    codes = functools.partial(_codes, client, token, project, PERSONA)
    assert codes(status="active") == {active["unique_code"]} and codes(status="draft") == {draft["unique_code"]}
    assert codes(search="draft one") == {draft["unique_code"]} and codes(type="Primary") == set()
    assert _export(client, token, project, PERSONA, status="bogus").status_code == 422
    need = _make(world, NEED, name="Fast reports")
    assert _codes(client, token, project, NEED, search="reports") == {need["unique_code"]}
    org_stakeholder = _create_org_stakeholder(client, token, world[1]["id"], name="Org person")
    own = _make(world, STAKEHOLDER, name="Own person")
    assert _codes(client, token, project, STAKEHOLDER, include_org="false") == {own["unique_code"]}
    assert len(_codes(client, token, project, STAKEHOLDER)) == 2 and org_stakeholder["unique_code"]


def test_a_need_owner_round_trips_and_a_blank_name_is_refused(world):
    client, _, project, token = world
    need = _make(world, NEED)
    email = client.get("/api/v1/auth/me", headers=auth_headers(token)).json()["email"]
    assert _import(client, token, project, NEED, _csv(["code", "owner"], [need["unique_code"], email]), apply=True).json()["updated"] == 1
    assert _rows(_export(client, token, project, NEED))[0]["owner"] == email
    assert _import(client, token, project, NEED, _csv(["code", "name"], [need["unique_code"], ""])).json()["failed"] == 1
    assert _import(client, token, project, NEED, _csv(["code", "owner"], [need["unique_code"], "nobody@example.com"])).json()["failed"] == 1


def test_a_stakeholder_group_filter_reaches_the_export_with_and_without_its_subgroups(world):
    client, _, project, token = world
    base = BASE.format(pid=project["id"])
    parent = _group(client, token, base, "Customers")
    child = _group(client, token, base, "Acme", parent["id"])
    direct = _make(world, STAKEHOLDER, name="Direct")
    nested = _make(world, STAKEHOLDER, name="Nested")
    outside = _make(world, STAKEHOLDER, name="Out")
    for group, stakeholder in ((parent, direct), (child, nested)):
        assert client.post(
            f"{base}/stakeholder-groups/{group['id']}/members", json={"stakeholder_id": stakeholder["id"]}, headers=auth_headers(token),
        ).status_code in (200, 201, 204)
    codes = functools.partial(_codes, client, token, project, STAKEHOLDER)
    assert codes(group_id=parent["id"]) == {direct["unique_code"], nested["unique_code"]}
    assert codes(group_id=parent["id"], direct_only="true") == {direct["unique_code"]}
    assert outside["unique_code"] not in codes(group_id=parent["id"])
    assert _export(client, token, project, STAKEHOLDER, group_id="not-an-id").status_code == 422
    assert _export(client, token, project, STAKEHOLDER, group_id=str(uuid.uuid4())).status_code == 404


# The columns that hold what a person said or is: a column added later that names one of these must be tagged.
PERSONAL_STAKEHOLDER_COLUMNS = {
    "name": "personal", "role": "personal", "organisation_group": "personal", "contact_info": "contact",
    "availability_constraints": "contact", "description": "free_text_people", "interests": "free_text_people",
    "responsibilities": "free_text_people", "goals_needs": "free_text_people", "priorities": "free_text_people",
    "constraints": "free_text_people", "workflows_scenarios": "free_text_people",
}
PERSONAL_ENGAGEMENT_COLUMNS = {"summary": "free_text_people", "notes": "free_text_people"}


def test_every_column_that_holds_a_persons_data_is_tagged_and_a_persona_holds_none(world):
    from app.database import SessionLocal
    from app.models.project import Project
    from app.modules.registry import get_record_table_providers

    _, _, project, _ = world
    providers = get_record_table_providers()
    db = SessionLocal()
    try:
        row = db.get(Project, uuid.UUID(project["id"]))
        by_key = {t: {c.key: c.sensitivity for c in providers[t].columns(db, row)} for t in (STAKEHOLDER, ENGAGEMENT, PERSONA, NEED, GROUP, FINDING)}
    finally:
        db.close()
    for key, tag in PERSONAL_STAKEHOLDER_COLUMNS.items():
        assert by_key[STAKEHOLDER][key] == tag, f"stakeholder.{key} must be tagged {tag}"
    for key, tag in PERSONAL_ENGAGEMENT_COLUMNS.items():
        assert by_key[ENGAGEMENT][key] == tag, f"engagement.{key} must be tagged {tag}"
    assert not {k for k, tag in by_key[PERSONA].items() if tag != "none"}, "a persona is a fictional archetype"
