"""Tests for the organisation tier of the record tables (`routers.org_record_tables`, `services.record_tables`):
the six types an organisation can own (Strategy, Future State, Guiding Principle, Persona, Stakeholder, Stakeholder
Group) export their organisation-level list as the CSV they import, a row with a code updates that record through the
organisation endpoints' own path, a blank code creates one, a project's records and another organisation's are never
matched, personal data follows the organisation policy with the organisation-level grant, and the file is also a
PDF, Word or CSV document.

Each test builds its own organisation, so none depends on state left by another test.
"""

from __future__ import annotations

import csv
import io
import uuid

import pytest

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.modules.context_strategy.tests.test_context_strategy_relationships_api import (
    _create_org_future_state,
    _create_org_strategy,
    _create_strategy,
)
from app.modules.context_strategy.tests.test_context_strategy_relationships_api import (
    _enable_module as _enable_context_strategy,
)
from app.modules.registry import get_record_table_providers
from app.modules.stakeholders.tests.test_persona_api import (
    _create_org_persona,
    _create_project_persona,
)
from app.modules.stakeholders.tests.test_persona_api import _enable_module as _enable_stakeholders
from app.modules.stakeholders.tests.test_stakeholder_api import _create_org_stakeholder
from app.modules.stakeholders.tests.test_stakeholder_groups import _group
from tests.conftest import auth_headers, create_org_admin_in, create_org_user, create_project, login

STRATEGY, FUTURE_STATE, GUIDING_PRINCIPLE, PERSONA, STAKEHOLDER, GROUP = (
    "strategy", "future_state", "guiding_principle", "persona", "stakeholder", "stakeholder_group",
)
ORG_TYPES = (STRATEGY, FUTURE_STATE, GUIDING_PRINCIPLE, PERSONA, STAKEHOLDER, GROUP)
CS = "/api/v1/orgs/{oid}/modules/context_strategy"
SH = "/api/v1/orgs/{oid}/modules/stakeholders"

#: type -> (the column a test edits, its new value, a minimal create row)
EDIT = {
    STRATEGY: ("objective", "Win every segment", {"title": "New strategy", "objective": "Grow"}),
    FUTURE_STATE: ("desired_state", "Fully automated", {"title": "New future state"}),
    GUIDING_PRINCIPLE: ("rationale", "People get hurt otherwise", {"name": "New principle", "principle_statement": "Be safe"}),
    PERSONA: ("goals", "Finish the day early", {"name": "New persona"}),
    STAKEHOLDER: ("target_cadence", "Monthly", {"name": "New stakeholder"}),
    GROUP: ("description", "Everyone in the field", {"name": "New group"}),
}


def _create_org_guiding_principle(client, token, org_id, **extra) -> dict:
    payload = {"name": "Be safe", "principle_statement": "Safety first", **extra}
    resp = client.post(CS.format(oid=org_id) + "/guiding-principles", json=payload, headers=auth_headers(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.fixture
def world(client, admin_token):
    """An organisation with both modules on and an admin, a project, and one organisation-owned record of each type."""
    org, token = create_org_admin_in(client, admin_token, f"Org Tables {uuid.uuid4().hex[:6]}")
    _enable_context_strategy(client, token, org["id"])
    _enable_stakeholders(client, token, org["id"])
    project = create_project(client, token, org["id"], "Project")
    for tag in ("personal", "contact", "free_text_people"):
        resp = client.put(
            f"/api/v1/orgs/{org['id']}/record-sensitivity-policy/{tag}", json={"allowed": True}, headers=auth_headers(token),
        )
        assert resp.status_code in (200, 204), resp.text
    records = {
        STRATEGY: _create_org_strategy(client, token, org["id"]),
        FUTURE_STATE: _create_org_future_state(client, token, org["id"]),
        GUIDING_PRINCIPLE: _create_org_guiding_principle(client, token, org["id"]),
        PERSONA: _create_org_persona(client, token, org["id"]),
        STAKEHOLDER: _create_org_stakeholder(client, token, org["id"]),
        GROUP: _group(client, token, SH.format(oid=org["id"]), "Field staff"),
    }
    return {"client": client, "org": org, "token": token, "project": project, "records": records}


def _base(world, record_type: str) -> str:
    return f"/api/v1/orgs/{world['org']['id']}/records/{record_type}"


def _export(world, record_type: str, token: str | None = None, **params):
    return world["client"].get(f"{_base(world, record_type)}/export", params=params, headers=auth_headers(token or world["token"]))


def _rows(resp) -> list[dict]:
    assert resp.status_code == 200, resp.text
    return list(csv.DictReader(io.StringIO(resp.content.decode("utf-8-sig"))))


def _import(world, record_type: str, text: str, *, apply: bool = False, token: str | None = None):
    return world["client"].post(
        f"{_base(world, record_type)}/import", params={"dry_run": "false" if apply else "true"},
        files={"file": ("records.csv", text.encode("utf-8"), "text/csv")}, headers=auth_headers(token or world["token"]),
    )


def _csv(header: list[str], *rows: list[str]) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(header)
    writer.writerows(rows)
    return out.getvalue()


def _plain_member(world) -> str:
    """A user with only the organisation `member` role; returns their token."""
    email = f"member-{uuid.uuid4().hex[:6]}@example.com"
    create_org_user(world["client"], world["token"], world["org"]["id"], email)
    return login(world["client"], email, "Password123!")


# --- the file ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("record_type", ORG_TYPES)
def test_the_organisations_own_records_export_with_the_organisation_qualified_code(world, record_type):
    rows = _rows(_export(world, record_type))
    assert len(rows) == 1
    assert rows[0]["code"].startswith(f"{world['org']['code']}-")


def test_a_projects_records_are_not_in_the_organisation_export(world):
    client, token, project = world["client"], world["token"], world["project"]
    _create_project_persona(client, token, project["id"], name="Project only persona")
    names = [r["name"] for r in _rows(_export(world, PERSONA))]
    assert "Project only persona" not in names and len(names) == 1


@pytest.mark.parametrize("record_type", ORG_TYPES)
def test_reimporting_an_unchanged_export_changes_nothing(world, record_type):
    resp = _import(world, record_type, _export(world, record_type).content.decode("utf-8-sig"))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["created"], body["updated"], body["failed"]) == (0, 0, 0) and body["unchanged"] == 1


@pytest.mark.parametrize("record_type", ORG_TYPES)
def test_editing_a_cell_updates_the_organisations_record_and_a_preview_writes_nothing(world, record_type):
    column, value, _ = EDIT[record_type]
    row = _rows(_export(world, record_type))[0]
    text = _csv(["code", column], [row["code"], value])

    preview = _import(world, record_type, text).json()
    assert preview["applied"] is False and preview["updated"] == 1
    assert _rows(_export(world, record_type))[0][column] == row[column]

    applied = _import(world, record_type, text, apply=True).json()
    assert applied["applied"] is True and applied["updated"] == 1 and applied["failed"] == 0
    assert _rows(_export(world, record_type))[0][column] == value


@pytest.mark.parametrize("record_type", ORG_TYPES)
def test_a_blank_code_creates_an_organisation_record(world, record_type):
    _, _, row = EDIT[record_type]
    applied = _import(world, record_type, _csv(["code", *row], ["", *row.values()]), apply=True).json()
    assert applied["created"] == 1 and applied["failed"] == 0
    exported = _rows(_export(world, record_type))
    assert len(exported) == 2 and all(r["code"].startswith(f"{world['org']['code']}-") for r in exported)


def test_the_bare_code_is_accepted_as_well_as_the_qualified_one(world):
    code = _rows(_export(world, PERSONA))[0]["code"]
    bare = code.removeprefix(f"{world['org']['code']}-")
    body = _import(world, PERSONA, _csv(["code", "goals"], [bare, "Bare code goal"]), apply=True).json()
    assert body["updated"] == 1
    assert _rows(_export(world, PERSONA))[0]["goals"] == "Bare code goal"


def test_a_persona_type_name_resolves_against_the_organisations_types(world):
    types = world["client"].get(SH.format(oid=world["org"]["id"]) + "/persona-types", headers=auth_headers(world["token"])).json()
    name = types[0]["name"]
    body = _import(world, PERSONA, _csv(["code", "name", "type"], ["", "Typed", name]), apply=True).json()
    assert body["created"] == 1
    assert {r["name"]: r["type"] for r in _rows(_export(world, PERSONA))}["Typed"] == name
    bad = _import(world, PERSONA, _csv(["code", "name", "type"], ["", "Bad type", "No such type"])).json()
    assert bad["failed"] == 1 and "Unknown" in bad["rows"][0]["message"]


# --- tenancy ----------------------------------------------------------------------------------------------------


def test_a_code_of_a_project_record_or_another_organisation_is_a_row_error(world, client, admin_token):
    # Codes count per owner, so "PER-001" exists in every project and organisation: use ones this organisation lacks.
    _create_project_persona(world["client"], world["token"], world["project"]["id"], name="Project persona 1")
    project_second = _create_project_persona(world["client"], world["token"], world["project"]["id"], name="Project persona 2")
    other, other_token = create_org_admin_in(client, admin_token, f"Other {uuid.uuid4().hex[:6]}")
    _enable_stakeholders(client, other_token, other["id"])
    for n in (1, 2, 3):
        other_persona = _create_org_persona(client, other_token, other["id"], name=f"Other persona {n}")
    codes = (
        project_second["unique_code"], other_persona["unique_code"], f"{other['code']}-{other_persona['unique_code']}",
        f"{world['project']['code']}-{project_second['unique_code']}",
    )
    assert all(code.endswith(("-002", "-003")) for code in codes)
    for code in codes:
        body = _import(world, PERSONA, _csv(["code", "goals"], [code, "hijack"]), apply=True).json()
        assert body["updated"] == 0 and body["failed"] == 1
        assert body["rows"][0]["message"].startswith("No record with the code")
    assert [r["goals"] for r in _rows(_export(world, PERSONA))] != ["hijack"]


def test_another_organisations_user_cannot_use_the_tables(world, client, admin_token):
    _, stranger = create_org_admin_in(client, admin_token, f"Stranger {uuid.uuid4().hex[:6]}")
    assert _export(world, PERSONA, token=stranger).status_code == 404
    assert _import(world, PERSONA, _csv(["code"], [""]), token=stranger).status_code == 404
    assert client.get(f"{_base(world, PERSONA)}/columns", headers=auth_headers(stranger)).status_code == 404


# --- access -----------------------------------------------------------------------------------------------------


def test_a_member_may_export_but_not_import_what_needs_an_owner_role(world):
    member = _plain_member(world)
    assert _export(world, PERSONA, token=member).status_code == 200
    columns = world["client"].get(f"{_base(world, PERSONA)}/columns", headers=auth_headers(member)).json()
    assert columns["importable"] is True and columns["can_import"] is False
    assert _import(world, PERSONA, _csv(["code", "name"], ["", "Nope"]), token=member).status_code == 403


def test_any_member_may_create_a_strategy_but_not_edit_one(world):
    member = _plain_member(world)
    created = _import(world, STRATEGY, _csv(["code", "title", "objective"], ["", "Member strategy", "Do"]), apply=True, token=member)
    assert created.status_code == 200 and created.json()["created"] == 1
    code = next(r["code"] for r in _rows(_export(world, STRATEGY)) if r["title"] == "Member strategy")
    edit = _import(world, STRATEGY, _csv(["code", "objective"], [code, "Changed"]), apply=True, token=member)
    assert edit.status_code == 200 and edit.json()["failed"] == 1


def test_a_type_without_an_organisation_tier_or_with_its_module_off_is_not_found(world):
    assert _export(world, "requirement").status_code == 404
    assert _export(world, "no_such_type").status_code == 404
    client, token, org_id = world["client"], world["token"], world["org"]["id"]
    resp = client.put(f"/api/v1/orgs/{org_id}/modules/stakeholders", json={"enabled": False}, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    assert _export(world, PERSONA).status_code == 404
    assert _export(world, STRATEGY).status_code == 200


def test_a_filter_the_organisation_list_cannot_honour_is_refused(world):
    assert _export(world, PERSONA, project_scope="both").status_code == 422
    assert _export(world, PERSONA, status="draft").status_code == 200


def test_an_organisation_filter_narrows_the_file(world):
    _create_org_persona(world["client"], world["token"], world["org"]["id"], name="Zebra")
    assert [r["name"] for r in _rows(_export(world, PERSONA, search="zebra"))] == ["Zebra"]
    assert _rows(_export(world, PERSONA, status="retired")) == []


# --- personal data ----------------------------------------------------------------------------------------------


def test_personal_data_columns_follow_the_organisation_policy_and_the_organisation_grant(world):
    client, token, org_id = world["client"], world["token"], world["org"]["id"]
    assert "contact_info" in _rows(_export(world, STAKEHOLDER))[0]
    resp = client.put(f"/api/v1/orgs/{org_id}/record-sensitivity-policy/contact", json={"allowed": False}, headers=auth_headers(token))
    assert resp.status_code in (200, 204), resp.text
    exported = _export(world, STAKEHOLDER)
    assert "contact_info" not in _rows(exported)[0] and exported.headers["x-omitted-sensitivity"] == "contact"
    columns = client.get(f"{_base(world, STAKEHOLDER)}/columns", headers=auth_headers(token)).json()
    assert columns["omitted_sensitivity"] == ["contact"] and columns["omitted_reasons"] == {"contact": "policy"}
    ignored = _import(world, STAKEHOLDER, _csv(["code", "contact_info"], [_rows(exported)[0]["code"], "x@y.z"])).json()
    assert "contact_info" in ignored["ignored_columns"]

    member = _plain_member(world)
    assert "name" not in _rows(_export(world, STAKEHOLDER, token=member))[0]


# --- audit ------------------------------------------------------------------------------------------------------


def test_an_export_and_an_import_are_one_organisation_audit_event_each_without_cell_values(world):
    secret = "Needle goal text"
    code = _rows(_export(world, PERSONA))[0]["code"]
    _import(world, PERSONA, _csv(["code", "goals"], [code, secret]), apply=True)
    db = SessionLocal()
    try:
        events = db.query(AuditEvent).filter(
            AuditEvent.organization_id == world["org"]["id"], AuditEvent.action.in_(("records_exported", "records_imported")),
        ).all()
    finally:
        db.close()
    assert {e.action for e in events} == {"records_exported", "records_imported"}
    assert all(e.entity_type == "organization" and e.project_id is None for e in events)
    assert secret not in "".join(str(e.detail) for e in events)


# --- documents --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("fmt", "magic"), [("pdf", b"%PDF"), ("docx", b"PK"), ("csv", b"\xef\xbb\xbf")])
def test_the_organisations_list_is_also_a_pdf_word_or_csv_document(world, fmt, magic):
    resp = world["client"].get(
        f"/api/v1/orgs/{world['org']['id']}/reports/record-list", params={"record_type": STRATEGY, "format": fmt},
        headers=auth_headers(world["token"]),
    )
    assert resp.status_code == 200, resp.text
    assert resp.content.startswith(magic)


def test_the_document_route_refuses_json_and_a_stranger(world, client, admin_token):
    url = f"/api/v1/orgs/{world['org']['id']}/reports/record-list"
    bad = world["client"].get(url, params={"record_type": STRATEGY, "format": "json"}, headers=auth_headers(world["token"]))
    assert bad.status_code == 422
    _, stranger = create_org_admin_in(client, admin_token, f"Stranger {uuid.uuid4().hex[:6]}")
    denied = client.get(url, params={"record_type": STRATEGY, "format": "pdf"}, headers=auth_headers(stranger))
    assert denied.status_code == 404


# --- the pages still write through the shared path --------------------------------------------------------------


def test_the_organisation_endpoints_still_create_and_edit_through_the_shared_path(world):
    client, token, org_id = world["client"], world["token"], world["org"]["id"]
    strategy = world["records"][STRATEGY]
    resp = client.put(
        CS.format(oid=org_id) + f"/strategies/{strategy['id']}", json={**strategy, "objective": "Edited on the page"}, headers=auth_headers(token),
    )
    assert resp.status_code == 200 and resp.json()["objective"] == "Edited on the page"
    assert _rows(_export(world, STRATEGY))[0]["objective"] == "Edited on the page"
    listed = client.get(CS.format(oid=org_id) + "/strategies", headers=auth_headers(token)).json()
    assert [s["id"] for s in listed] == [strategy["id"]]
    other = _create_strategy(client, token, world["project"]["id"])
    assert other["id"] not in {s["id"] for s in listed}


# --- registry ---------------------------------------------------------------------------------------------------


def test_exactly_the_types_the_organisation_can_own_have_an_organisation_tier():
    providers = get_record_table_providers()
    owned = {key for key, p in providers.items() if p.organization_owned is not None}
    with_tier = {key for key, p in providers.items() if p.organization is not None}
    assert owned <= with_tier
    assert with_tier == set(ORG_TYPES)


def test_every_organisation_tier_declares_its_gate_and_columns_with_the_same_keys_as_the_project_tier():
    for key, provider in get_record_table_providers().items():
        tier = provider.organization
        if tier is None:
            continue
        assert tier.subcomponent
        assert tier.create is not None and tier.update is not None, key
        assert tier.filter_params <= provider.filter_params | {"include_archived"}, key
