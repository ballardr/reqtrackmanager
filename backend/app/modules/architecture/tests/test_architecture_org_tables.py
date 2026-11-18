"""Tests for the organisation tier of the element record table (organisation-owned elements export as the CSV they
import, through the organisation endpoints' own path and gate) and for the connection table's shared ends: an end
another owner shares is exported qualified by its owner's code and, imported, resolves only to an element the person can
read. Every test builds its own organisation."""

from __future__ import annotations

import csv
import io

from app.modules.architecture.tests._helpers import (
    grant,
    make_architect,
    make_collection,
    make_connection,
    make_element,
    make_org_element,
    org_base,
    project_base,
    setup,
)
from tests.conftest import auth_headers, create_org_user, create_project, login

ELEMENT = "architecture_element"
CONNECTION = "architecture_connection"


def _rows(resp) -> list[dict]:
    assert resp.status_code == 200, resp.text
    return list(csv.DictReader(io.StringIO(resp.content.decode("utf-8-sig"))))


def _csv(header: list[str], *rows: list[str]) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(header)
    writer.writerows(rows)
    return out.getvalue()


def _import(client, token, tier, text, *, apply=True):
    return client.post(
        f"{tier}/import", params={"dry_run": "false" if apply else "true"},
        files={"file": ("records.csv", text.encode("utf-8"), "text/csv")}, headers=auth_headers(token),
    )


def _import_ok(client, token, tier, text, *, apply=True) -> dict:
    resp = _import(client, token, tier, text, apply=apply)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_the_organisation_elements_export_qualified_and_reimport_unchanged(client, admin_token):
    org, _project, token = setup(client, admin_token, "Arch org tables")
    parent = make_org_element(client, token, org["id"], "Platform", activate=True, ports=[{"name": "Main", "direction": "in"}])
    make_org_element(client, token, org["id"], "Broker", parent_id=parent["id"])
    tier = f"/api/v1/orgs/{org['id']}/records/{ELEMENT}"
    exported = client.get(f"{tier}/export", headers=auth_headers(token))
    rows = {r["name"]: r for r in _rows(exported)}
    assert set(rows) == {"Platform", "Broker"}
    assert rows["Platform"]["code"].endswith("-ELM-001") and rows["Broker"]["parent"] == "ELM-001"
    assert rows["Platform"]["ports"] == "Main:In" and rows["Platform"]["status"] == "Active"

    result = _import_ok(client, token, tier, exported.content.decode("utf-8-sig"))
    assert (result["created"], result["updated"], result["unchanged"], result["failed"]) == (0, 0, 2, 0)


def test_an_import_creates_and_edits_organisation_elements_through_the_same_rules(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch org import")
    existing = make_org_element(client, token, org["id"], "Platform")
    project_element = make_element(client, token, project["id"], "Project one")
    tier = f"/api/v1/orgs/{org['id']}/records/{ELEMENT}"
    result = _import_ok(client, token, tier, _csv(
        ["code", "name", "description", "type", "status", "ports"],
        ["", "Gateway", "New one", "Service", "Active", "In:in"],
        [existing["unique_code"], "Platform core", "", "System", "", ""],
        ["", "Bad type", "", "Nonexistent", "", ""],
        [project_element["unique_code"] + "X", "Unknown code", "", "System", "", ""],
    ))
    assert (result["created"], result["updated"], result["failed"]) == (1, 1, 2), result
    listed = {e["name"]: e for e in client.get(f"{org_base(org['id'])}/elements", headers=auth_headers(token)).json()}
    assert set(listed) == {"Platform core", "Gateway"}
    assert listed["Gateway"]["status"] == "active" and listed["Gateway"]["organization_id"] == org["id"]
    assert [p["name"] for p in listed["Gateway"]["ports"]] == ["In"]
    # The project's own element is never matched by the organisation's table.
    project_list = client.get(f"{project_base(project['id'])}/elements", headers=auth_headers(token)).json()
    assert [e["name"] for e in project_list] == ["Project one"]


def test_only_an_organisation_administrator_may_import_organisation_elements(client, admin_token):
    org, _project, token = setup(client, admin_token, "Arch org import gate")
    create_org_user(client, token, org["id"], "arch.orgtable.member@example.com")
    member = login(client, "arch.orgtable.member@example.com", "Password123!")
    tier = f"/api/v1/orgs/{org['id']}/records/{ELEMENT}"
    columns = client.get(f"{tier}/columns", headers=auth_headers(member))
    assert columns.status_code == 200 and columns.json()["can_import"] is False
    resp = _import(client, member, tier, _csv(["code", "name", "type"], ["", "Sneaky", "System"]))
    assert resp.status_code == 403
    assert client.get(f"{org_base(org['id'])}/elements", headers=auth_headers(token)).json() == []


def test_a_shared_end_is_exported_qualified_and_does_not_collide_with_a_local_code(client, admin_token):
    org, owner, consumer, token = _consumer_world(client, admin_token, "Arch tables shared end")
    shared = make_element(client, token, owner["id"], "Platform", activate=True)
    local = make_element(client, token, consumer["id"], "Local app")
    own_namesake = make_element(client, token, consumer["id"], "Own namesake")
    assert shared["unique_code"] == local["unique_code"]
    base = project_base(owner["id"])
    collection = make_collection(client, token, base, "Infra", members=[shared["id"]])
    grant(client, token, base, collection["id"], project_id=consumer["id"])
    architect = make_architect(client, token, org["id"], consumer["id"], "arch.sharedend@example.com")
    make_connection(client, architect, consumer["id"], local["id"], shared["id"], name="Uses platform")
    make_connection(client, architect, consumer["id"], local["id"], own_namesake["id"], name="Internal")

    tier = f"/api/v1/projects/{consumer['id']}/records/{CONNECTION}"
    exported = client.get(f"{tier}/export", headers=auth_headers(architect))
    rows = {r["name"]: r for r in _rows(exported)}
    qualified = rows["Uses platform"]["target"]
    assert qualified.endswith(f"-{shared['unique_code']}") and qualified != shared["unique_code"]
    assert rows["Internal"]["target"] == own_namesake["unique_code"]

    # The exported file re-imports as no change; a new row naming the qualified code reaches the shared element.
    unchanged = _import_ok(client, architect, tier, exported.content.decode("utf-8-sig"))
    assert (unchanged["updated"], unchanged["failed"]) == (0, 0)
    made = _import_ok(client, architect, tier, _csv(
        ["code", "name", "type", "source", "target"], ["", "Second link", "REST API", local["unique_code"], qualified],
    ))
    assert (made["created"], made["failed"]) == (1, 0), made
    listed = {c["name"]: c for c in client.get(f"{project_base(consumer['id'])}/connections", headers=auth_headers(architect)).json()}
    assert listed["Second link"]["target_element_id"] == shared["id"] and listed["Second link"]["target_shared"] is True


def test_a_qualified_end_naming_an_element_the_person_cannot_read_is_a_row_error(client, admin_token):
    org, owner, consumer, token = _consumer_world(client, admin_token, "Arch tables hidden end")
    hidden = make_element(client, token, owner["id"], "Platform", activate=True)
    local = make_element(client, token, consumer["id"], "Local app")
    architect = make_architect(client, token, org["id"], consumer["id"], "arch.hiddenend@example.com")
    tier = f"/api/v1/projects/{consumer['id']}/records/{CONNECTION}"
    qualified = f"{owner['code']}-{hidden['unique_code']}"
    result = _import_ok(client, architect, tier, _csv(
        ["code", "name", "type", "source", "target"], ["", "Sneaky", "REST API", local["unique_code"], qualified],
    ))
    assert (result["created"], result["failed"]) == (0, 1), result
    assert client.get(f"{project_base(consumer['id'])}/connections", headers=auth_headers(token)).json() == []


def _consumer_world(client, admin_token, name):
    """An organisation with an owner project and a consumer project: `(org, owner, consumer, admin token)`."""
    org, owner, token = setup(client, admin_token, name)
    consumer = create_project(client, token, org["id"], f"{name} consumer")
    return org, owner, consumer, token
