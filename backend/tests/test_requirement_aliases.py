"""Tests for requirement aliases: a requirement placed in further components and categories, each with a code of its
own; the setting that allows them; resolving any code to the one record; and making an alias independent.

Each test builds its own organisation (`tests.link_world.World`), so none depends on state left by another test.
"""

from __future__ import annotations

import csv
import io
import uuid

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.models.relationship import ArtefactLink
from app.models.requirement_alias import RequirementAlias
from tests.conftest import auth_headers, create_org_user, login
from tests.link_world import REQ, World


@pytest.fixture
def world(client, admin_token) -> World:
    return World(client, admin_token, "Alias Org")


def _base(project: dict) -> str:
    return f"/api/v1/projects/{project['id']}"


def _tree(world: World, project: dict, name: str, prefix: str) -> tuple[str, str]:
    """A component and a category under it; returns their ids."""
    component = world.client.post(
        f"{_base(project)}/components", json={"name": name, "prefix": prefix}, headers=auth_headers(world.token)
    )
    assert component.status_code == 201, component.text
    category = world.client.post(
        f"{_base(project)}/categories",
        json={"name": f"{name} Interfaces", "prefix": "IF", "component_id": component.json()["id"]},
        headers=auth_headers(world.token),
    )
    assert category.status_code == 201, category.text
    return component.json()["id"], category.json()["id"]


def _get(world: World, project: dict, requirement_id) -> dict:
    resp = world.client.get(f"{_base(project)}/requirements/{requirement_id}", headers=auth_headers(world.token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _alias(world: World, project: dict, requirement_id, places: list[tuple[str, str]], token: str | None = None):
    return world.client.put(
        f"{_base(project)}/requirements/{requirement_id}/aliases",
        json={"places": [{"component_id": c, "category_id": k} for c, k in places]},
        headers=auth_headers(token or world.token),
    )


def _set_mode(world: World, project: dict, mode: str | None):
    return world.client.put(
        f"{_base(project)}/requirement-aliases", json={"mode": mode}, headers=auth_headers(world.token)
    )


def test_an_alias_gets_a_code_from_its_own_pair_and_the_one_counter(world):
    project = world.project()
    hardware, interfaces = _tree(world, project, "Hardware", "HW")
    first = world.requirement(project, "Bus")
    resp = _alias(world, project, first, [(hardware, interfaces)])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [(a["unique_code"], a["is_retired"]) for a in body["aliases"]] == [("HW-IF-002", False)]
    # The next primary code continues the same sequence: the number is never reused or shared.
    second = _get(world, project, world.requirement(project, "Next"))
    assert second["unique_code"].endswith("-003")


def test_creating_a_requirement_with_additional_places(world):
    project = world.project()
    hardware, interfaces = _tree(world, project, "Hardware", "HW")
    resp = world.client.post(
        f"{_base(project)}/requirements",
        json={
            "name": "Bus", "component_id": project["component_id"], "category_id": project["category_id"],
            "additional_places": [{"component_id": hardware, "category_id": interfaces}],
        },
        headers=auth_headers(world.token),
    )
    assert resp.status_code == 201, resp.text
    assert [a["unique_code"] for a in resp.json()["aliases"]] == ["HW-IF-002"]


def test_any_code_finds_the_one_record(world):
    project = world.project()
    hardware, interfaces = _tree(world, project, "Hardware", "HW")
    requirement = world.requirement(project, "Bus")
    code = _alias(world, project, requirement, [(hardware, interfaces)]).json()["aliases"][0]["unique_code"]
    found = world.client.get(
        f"/api/v1/orgs/{world.org['id']}/records/by-code/{project['code']}-{code}", headers=auth_headers(world.token)
    )
    assert found.status_code == 200, found.text
    assert found.json()["id"] == str(requirement)
    assert found.json()["alias_state"] == "alias"
    own = world.client.get(
        f"/api/v1/orgs/{world.org['id']}/records/by-code/{project['code']}-{_get(world, project, requirement)['unique_code']}",
        headers=auth_headers(world.token),
    )
    assert own.json()["alias_state"] is None


def test_the_component_filter_matches_an_alias_and_search_finds_its_code(world):
    project = world.project()
    hardware, interfaces = _tree(world, project, "Hardware", "HW")
    placed = world.requirement(project, "Bus")
    world.requirement(project, "Other")
    code = _alias(world, project, placed, [(hardware, interfaces)]).json()["aliases"][0]["unique_code"]
    by_component = world.client.get(f"{_base(project)}/requirements?component_id={hardware}", headers=auth_headers(world.token))
    assert [r["id"] for r in by_component.json()] == [str(placed)]
    by_category = world.client.get(f"{_base(project)}/requirements?category_id={interfaces}", headers=auth_headers(world.token))
    assert [r["id"] for r in by_category.json()] == [str(placed)]
    by_code = world.client.get(f"{_base(project)}/requirements?search={code}", headers=auth_headers(world.token))
    assert [r["id"] for r in by_code.json()] == [str(placed)]


def test_the_shared_placement_view_lists_primary_then_aliases_with_codes(world):
    project = world.project()
    hardware, interfaces = _tree(world, project, "Hardware", "HW")
    requirement = world.requirement(project, "Bus")
    _alias(world, project, requirement, [(hardware, interfaces)])
    resp = world.client.get(f"{_base(project)}/artefacts/{REQ}/{requirement}/placements", headers=auth_headers(world.token))
    places = resp.json()["placements"]
    assert [p["component_name"] for p in places] == ["Software", "Hardware"]
    assert places[0]["alias_id"] is None and places[1]["alias_id"] is not None
    assert places[1]["code"] == "HW-IF-002"
    assert resp.json()["managed_on_record"] is True


def test_an_alias_cannot_repeat_the_primary_place_or_lack_a_category(world):
    project = world.project()
    requirement = world.requirement(project)
    own = _alias(world, project, requirement, [(project["component_id"], project["category_id"])])
    assert own.status_code == 422
    other = world.client.post(f"{_base(project)}/components", json={"name": "HW", "prefix": "HW"}, headers=auth_headers(world.token))
    bare = world.client.put(
        f"{_base(project)}/requirements/{requirement}/aliases",
        json={"places": [{"component_id": other.json()["id"], "category_id": str(uuid.uuid4())}]},
        headers=auth_headers(world.token),
    )
    assert bare.status_code == 422


def test_removing_an_alias_retires_its_code_which_is_never_reused_and_still_resolves(world):
    project = world.project()
    hardware, interfaces = _tree(world, project, "Hardware", "HW")
    requirement = world.requirement(project, "Bus")
    retired = _alias(world, project, requirement, [(hardware, interfaces)]).json()["aliases"][0]["unique_code"]
    assert _alias(world, project, requirement, []).json()["aliases"] == []
    again = _alias(world, project, requirement, [(hardware, interfaces)]).json()["aliases"][0]["unique_code"]
    assert again != retired
    found = world.client.get(
        f"/api/v1/orgs/{world.org['id']}/records/by-code/{project['code']}-{retired}", headers=auth_headers(world.token)
    )
    assert found.json()["id"] == str(requirement)
    assert found.json()["alias_state"] == "retired_alias"
    with SessionLocal() as db:
        events = db.scalars(select(AuditEvent.action).where(AuditEvent.entity_id == str(requirement))).all()
    assert {"alias_added", "alias_retired"} <= set(events)


def test_promoting_an_alias_swaps_the_places_and_their_codes(world):
    project = world.project()
    hardware, interfaces = _tree(world, project, "Hardware", "HW")
    requirement = world.requirement(project, "Bus")
    before = _get(world, project, requirement)
    alias = _alias(world, project, requirement, [(hardware, interfaces)]).json()["aliases"][0]
    resp = world.client.post(
        f"{_base(project)}/requirements/{requirement}/aliases/{alias['id']}/promote", headers=auth_headers(world.token)
    )
    assert resp.status_code == 200, resp.text
    after = resp.json()
    assert (after["component_id"], after["category_id"], after["unique_code"]) == (hardware, interfaces, alias["unique_code"])
    assert [(a["unique_code"], a["component_id"]) for a in after["aliases"]] == [(before["unique_code"], project["component_id"])]


def test_the_setting_stops_new_aliases_but_keeps_existing_ones(world):
    project = world.project()
    hardware, interfaces = _tree(world, project, "Hardware", "HW")
    requirement = world.requirement(project, "Bus")
    _alias(world, project, requirement, [(hardware, interfaces)])
    assert _set_mode(world, project, "disabled").status_code == 200
    settings = world.client.get(f"{_base(project)}/requirement-aliases", headers=auth_headers(world.token)).json()
    assert (settings["mode"], settings["source"], settings["alias_count"]) == ("disabled", "project", 1)
    # Keeping the same place is not a new alias; a new one is refused.
    keep = _alias(world, project, requirement, [(hardware, interfaces)])
    assert keep.status_code == 200 and len(keep.json()["aliases"]) == 1
    second_component, second_category = _tree(world, project, "Mechanical", "ME")
    refused = _alias(world, project, requirement, [(hardware, interfaces), (second_component, second_category)])
    assert refused.status_code == 409
    assert "disabled" in refused.json()["detail"]
    assert len(_get(world, project, requirement)["aliases"]) == 1


def test_the_setting_resolves_project_then_ancestor_then_organisation(world):
    parent = world.project("Parent")
    child = world.project("Child", parent=parent)
    org_url = f"/api/v1/orgs/{world.org['id']}/requirement-aliases"
    assert world.client.get(f"{_base(child)}/requirement-aliases", headers=auth_headers(world.token)).json()["source"] == "organization"
    assert world.client.put(org_url, json={"mode": "disabled"}, headers=auth_headers(world.token)).status_code == 200
    assert world.client.get(f"{_base(child)}/requirement-aliases", headers=auth_headers(world.token)).json()["mode"] == "disabled"
    assert _set_mode(world, parent, "allowed").status_code == 200
    inherited = world.client.get(f"{_base(child)}/requirement-aliases", headers=auth_headers(world.token)).json()
    assert (inherited["mode"], inherited["source"], inherited["own_mode"]) == ("allowed", "parent_project", None)
    assert _set_mode(world, child, "disabled").status_code == 200
    assert world.client.get(f"{_base(child)}/requirement-aliases", headers=auth_headers(world.token)).json()["source"] == "project"
    assert _set_mode(world, child, "sometimes").status_code == 422
    assert world.client.put(org_url, json={"mode": None}, headers=auth_headers(world.token)).status_code == 422


def test_making_an_alias_independent_creates_a_draft_with_the_alias_code_and_copies(world):
    project = world.project()
    hardware, interfaces = _tree(world, project, "Hardware", "HW")
    original = world.requirement(project, "Bus")
    other = world.requirement(project, "Power")
    related = world.link_types_by_name()["Related to"]
    assert world.generic_link(project, (REQ, original), related["id"], (REQ, other)).status_code == 201
    comment = world.client.post(
        f"{_base(project)}/requirements/{original}/comments", json={"body": "Check the bus width"}, headers=auth_headers(world.token)
    )
    assert comment.status_code == 201, comment.text
    world.client.put(
        f"{_base(project)}/requirements/{original}",
        json={
            "name": "Bus", "component_id": project["component_id"], "category_id": project["category_id"],
            "owner": {"type": "user", "id": str(world.user_id)}, "keywords": ["interface"], "change_note": "tag",
        },
        headers=auth_headers(world.token),
    )
    alias = _alias(world, project, original, [(hardware, interfaces)]).json()["aliases"][0]
    resp = world.client.post(
        f"{_base(project)}/requirements/{original}/aliases/{alias['id']}/make-independent", json={},
        headers=auth_headers(world.token),
    )
    assert resp.status_code == 200, resp.text
    made = resp.json()
    assert made["unique_code"] == alias["unique_code"]
    assert (made["links_copied"], made["comments_copied"], made["tags_copied"], made["related_link_made"]) == (1, 1, 1, True)
    copy = _get(world, project, made["requirement_id"])
    assert (copy["status"], copy["unique_code"], copy["component_id"]) == ("draft", alias["unique_code"], hardware)
    assert copy["owner"]["id"] == str(world.user_id)
    assert _get(world, project, original)["aliases"] == []
    with SessionLocal() as db:
        assert db.scalar(select(RequirementAlias).where(RequirementAlias.id == uuid.UUID(alias["id"]))) is None
        notes = {
            row.note for row in db.scalars(select(ArtefactLink).where(
                (ArtefactLink.source_id == uuid.UUID(made["requirement_id"])) | (ArtefactLink.target_id == uuid.UUID(made["requirement_id"]))
            ))
        }
    assert any(note and note.startswith("Copied from") for note in notes)
    copied_comments = world.client.get(f"{_base(project)}/requirements/{made['requirement_id']}/comments", headers=auth_headers(world.token))
    assert "Copied from" in copied_comments.json()[0]["body"] and "Check the bus width" in copied_comments.json()[0]["body"]


def test_make_independent_asks_for_a_link_type_when_the_organisation_has_no_related_to(world):
    project = world.project()
    hardware, interfaces = _tree(world, project, "Hardware", "HW")
    original = world.requirement(project, "Bus")
    alias = _alias(world, project, original, [(hardware, interfaces)]).json()["aliases"][0]
    from app.models.requirement_link_type import RequirementLinkTypeDefinition

    with SessionLocal() as db:
        for row in db.scalars(select(RequirementLinkTypeDefinition).where(
            RequirementLinkTypeDefinition.organization_id == uuid.UUID(world.org["id"]),
        )):
            if row.forward_name == row.reverse_name:
                row.forward_name = f"{row.forward_name} one way"
        db.commit()
    resp = world.client.post(
        f"{_base(project)}/requirements/{original}/aliases/{alias['id']}/make-independent", json={}, headers=auth_headers(world.token)
    )
    assert resp.status_code == 409 and "link type" in resp.json()["detail"]
    assert len(_get(world, project, original)["aliases"]) == 1


def test_bulk_make_independent_reports_each_alias(world):
    project = world.project()
    hardware, interfaces = _tree(world, project, "Hardware", "HW")
    original = world.requirement(project, "Bus")
    alias = _alias(world, project, original, [(hardware, interfaces)]).json()["aliases"][0]
    resp = world.client.post(
        f"{_base(project)}/requirement-aliases/make-independent",
        json={"alias_ids": [alias["id"], str(uuid.uuid4())]}, headers=auth_headers(world.token),
    )
    assert resp.status_code == 200, resp.text
    assert [m["unique_code"] for m in resp.json()["made"]] == [alias["unique_code"]]
    assert len(resp.json()["failed"]) == 1


def test_a_place_with_an_alias_cannot_be_deleted_until_the_alias_is_removed(world):
    project = world.project()
    hardware, interfaces = _tree(world, project, "Hardware", "HW")
    requirement = world.requirement(project, "Bus")
    _alias(world, project, requirement, [(hardware, interfaces)])
    assert world.client.delete(f"{_base(project)}/categories/{interfaces}", headers=auth_headers(world.token)).status_code == 409
    assert world.client.delete(f"{_base(project)}/components/{hardware}", headers=auth_headers(world.token)).status_code == 409
    _alias(world, project, requirement, [])
    assert world.client.delete(f"{_base(project)}/categories/{interfaces}", headers=auth_headers(world.token)).status_code == 204


def test_deleting_a_category_with_a_replacement_moves_or_retires_aliases(world):
    project = world.project()
    hardware, interfaces = _tree(world, project, "Hardware", "HW")
    other_component, other_category = _tree(world, project, "Mechanical", "ME")
    moved, merged = world.requirement(project, "A"), world.requirement(project, "B")
    _alias(world, project, moved, [(hardware, interfaces)])
    _alias(world, project, merged, [(hardware, interfaces), (other_component, other_category)])
    resp = world.client.delete(
        f"{_base(project)}/categories/{interfaces}?reassign_to={other_category}", headers=auth_headers(world.token)
    )
    assert resp.status_code == 204, resp.text
    assert [a["category_id"] for a in _get(world, project, moved)["aliases"]] == [other_category]
    assert [a["category_id"] for a in _get(world, project, merged)["aliases"]] == [other_category]


# --- the surfaces an alias reaches ------------------------------------------------------------


def _csv_rows(world: World, project: dict) -> list[dict]:
    resp = world.client.get(f"{_base(project)}/records/requirement/export", headers=auth_headers(world.token))
    assert resp.status_code == 200, resp.text
    return list(csv.DictReader(io.StringIO(resp.content.decode("utf-8-sig"))))


def _csv_import(world: World, project: dict, rows: list[dict], *, apply: bool = True):
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return world.client.post(
        f"{_base(project)}/records/requirement/import", params={"dry_run": "false" if apply else "true"},
        files={"file": ("requirements.csv", out.getvalue().encode("utf-8"), "text/csv")}, headers=auth_headers(world.token),
    )


def test_the_csv_carries_the_further_places_and_their_codes_and_an_alias_code_finds_the_row(world):
    project = world.project()
    hardware, interfaces = _tree(world, project, "Hardware", "HW")
    requirement = world.requirement(project, "Bus")
    code = _alias(world, project, requirement, [(hardware, interfaces)]).json()["aliases"][0]["unique_code"]
    [row] = _csv_rows(world, project)
    assert row["additional_places"] == "HW/IF" and row["alias_codes"] == code
    # A row named by the alias code updates the one record.
    row["code"] = code
    row["name"] = "Bus renamed"
    resp = _csv_import(world, project, [row])
    assert resp.status_code == 200, resp.text
    assert [(r["action"], r["code"]) for r in resp.json()["rows"]] == [("update", _get(world, project, requirement)["unique_code"])]
    assert _get(world, project, requirement)["name"] == "Bus renamed"


def test_the_csv_import_sets_and_clears_the_further_places(world):
    project = world.project()
    hardware, interfaces = _tree(world, project, "Hardware", "HW")
    requirement = world.requirement(project, "Bus")
    [row] = _csv_rows(world, project)
    row["additional_places"] = "HW/IF"
    resp = _csv_import(world, project, [row])
    assert resp.status_code == 200, resp.text
    assert [a["component_id"] for a in _get(world, project, requirement)["aliases"]] == [hardware]
    [row] = _csv_rows(world, project)
    row["additional_places"] = ""
    assert _csv_import(world, project, [row]).status_code == 200
    assert _get(world, project, requirement)["aliases"] == []
    # A new alias is refused row by row when the project disables them.
    _set_mode(world, project, "disabled")
    [row] = _csv_rows(world, project)
    row["additional_places"] = "HW/IF"
    refused = _csv_import(world, project, [row]).json()
    assert [r["action"] for r in refused["rows"]] == ["error"]
    assert _get(world, project, requirement)["aliases"] == []


def test_a_disabled_project_refuses_a_new_alias_from_the_form_the_csv_and_the_api(world):
    project = world.project()
    hardware, interfaces = _tree(world, project, "Hardware", "HW")
    assert _set_mode(world, project, "disabled").status_code == 200
    created = world.client.post(
        f"{_base(project)}/requirements",
        json={
            "name": "Bus", "component_id": project["component_id"], "category_id": project["category_id"],
            "additional_places": [{"component_id": hardware, "category_id": interfaces}],
        },
        headers=auth_headers(world.token),
    )
    assert created.status_code == 409
    assert "disabled" in created.json()["detail"]
    requirement = world.requirement(project, "Bus")
    assert _alias(world, project, requirement, [(hardware, interfaces)]).status_code == 409


def test_the_project_bundle_and_a_template_carry_aliases_and_the_setting(world):
    project = world.project("Source")
    hardware, interfaces = _tree(world, project, "Hardware", "HW")
    requirement = world.requirement(project, "Bus")
    code = _alias(world, project, requirement, [(hardware, interfaces)]).json()["aliases"][0]["unique_code"]
    retired_component, retired_category = _tree(world, project, "Mechanical", "ME")
    _alias(world, project, requirement, [(hardware, interfaces), (retired_component, retired_category)])
    _alias(world, project, requirement, [(hardware, interfaces)])
    assert _set_mode(world, project, "disabled").status_code == 200
    exported = world.client.get(f"{_base(project)}/export", headers=auth_headers(world.token))
    imported = world.client.post(
        "/api/v1/projects/import", data={"organization_id": world.org["id"], "name": "Copy"},
        files={"file": ("bundle.zip", exported.content, "application/zip")}, headers=auth_headers(world.token),
    )
    assert imported.status_code == 201, imported.text
    copy = imported.json()["project"]
    [moved] = world.client.get(f"{_base(copy)}/requirements", headers=auth_headers(world.token)).json()
    assert [a["unique_code"] for a in moved["aliases"]] == [code]
    settings = world.client.get(f"{_base(copy)}/requirement-aliases", headers=auth_headers(world.token)).json()
    assert (settings["own_mode"], settings["alias_count"]) == ("disabled", 1)
    # The retired code still resolves in the imported project, and a new code is numbered past every imported one.
    found = world.client.get(
        f"/api/v1/orgs/{world.org['id']}/records/by-code/{copy['code']}-{code}", headers=auth_headers(world.token)
    )
    assert found.json()["id"] == moved["id"]
    world.client.put(f"{_base(copy)}/requirement-aliases", json={"mode": "allowed"}, headers=auth_headers(world.token))
    copy["component_id"], copy["category_id"] = moved["component_id"], moved["category_id"]
    fresh = world.requirement(copy, "Fresh")
    assert _get(world, copy, fresh)["unique_code"].rsplit("-", 1)[1] == "004"  # past the retired 003

    world.client.patch(f"{_base(project)}", json={"is_template": True}, headers=auth_headers(world.token))
    made = world.client.post(
        "/api/v1/projects",
        json={"organization_id": world.org["id"], "name": "From template", "summary": "", "template_project_id": project["id"]},
        headers=auth_headers(world.token),
    )
    assert made.status_code == 201, made.text
    [templated] = world.client.get(f"{_base(made.json())}/requirements", headers=auth_headers(world.token)).json()
    assert [a["unique_code"] for a in templated["aliases"]] == [code]
    assert world.client.get(f"{_base(made.json())}/requirement-aliases", headers=auth_headers(world.token)).json()["own_mode"] == "disabled"


def test_the_organisation_bundle_carries_the_organisation_setting(client, admin_token):
    world = World(client, admin_token, "Alias Bundle Org")
    world.project("Source")
    assert world.client.put(
        f"/api/v1/orgs/{world.org['id']}/requirement-aliases", json={"mode": "disabled"}, headers=auth_headers(world.token)
    ).status_code == 200
    exported = world.client.get(f"/api/v1/orgs/{world.org['id']}/export", headers=auth_headers(world.token))
    assert exported.status_code == 200, exported.text
    imported = world.client.post(
        "/api/v1/orgs/import", data={"name": f"Imported {uuid.uuid4().hex[:6]}"},
        files={"file": ("org.zip", exported.content, "application/zip")}, headers=auth_headers(admin_token),
    )
    assert imported.status_code == 201, imported.text
    org_id = imported.json()["organization"]["id"]
    with SessionLocal() as db:
        from app.models.organization import Organization

        assert db.get(Organization, uuid.UUID(org_id)).requirement_aliases == "disabled"


def test_search_finds_a_requirement_by_an_alias_code_and_by_the_name_of_an_alias_component(world):
    project = world.project()
    hardware, interfaces = _tree(world, project, "Turbine hall", "TH")
    requirement = world.requirement(project, "Bus")
    world.requirement(project, "Other")
    code = _alias(world, project, requirement, [(hardware, interfaces)]).json()["aliases"][0]["unique_code"]

    def hits(text: str, fields: list[str]) -> set[str]:
        resp = world.client.post(
            "/api/v1/search", json={"q": text, "fields": fields, "scope": "all"}, headers=auth_headers(world.token)
        )
        assert resp.status_code == 200, resp.text
        return {h["id"] for h in resp.json()["hits"]}

    assert hits(code, ["id"]) == {str(requirement)}
    assert hits("Turbine", ["placements"]) == {str(requirement)}


def test_the_requirements_report_lists_a_requirement_under_each_place_with_its_code(world):
    project = world.project()
    hardware, interfaces = _tree(world, project, "Hardware", "HW")
    requirement = world.requirement(project, "Bus")
    own = _get(world, project, requirement)["unique_code"]
    code = _alias(world, project, requirement, [(hardware, interfaces)]).json()["aliases"][0]["unique_code"]
    report = world.client.post(f"{_base(project)}/reports", json={"format": "csv"}, headers=auth_headers(world.token))
    assert report.status_code == 200, report.text
    rows = list(csv.DictReader(io.StringIO(report.content.decode("utf-8-sig"))))
    assert {(r["ID"], r["Same as"]) for r in rows} == {(own, ""), (code, own)}
    only_own = world.client.post(
        f"{_base(project)}/reports", json={"format": "csv", "primary_places_only": True}, headers=auth_headers(world.token)
    )
    assert [r["ID"] for r in csv.DictReader(io.StringIO(only_own.content.decode("utf-8-sig")))] == [own]
    by_component = world.client.post(
        f"{_base(project)}/reports", json={"format": "csv", "component_id": hardware}, headers=auth_headers(world.token)
    )
    assert [r["ID"] for r in csv.DictReader(io.StringIO(by_component.content.decode("utf-8-sig")))] == [code]


def test_adding_and_removing_places_needs_the_tag_authority_and_stays_inside_the_project(world):
    project = world.project()
    other = world.project("Other")
    hardware, interfaces = _tree(world, project, "Hardware", "HW")
    elsewhere, elsewhere_category = _tree(world, other, "Elsewhere", "EL")
    requirement = world.requirement(project, "Bus")
    # A plain member may read the requirement but not place it.
    email = f"member-{uuid.uuid4().hex[:6]}@example.com"
    user_id = create_org_user(world.client, world.token, world.org["id"], email)
    world.client.post(f"{_base(project)}/roles", json={"user_id": user_id, "role": "member"}, headers=auth_headers(world.token))
    member = login(world.client, email, "Password123!")
    assert _alias(world, project, requirement, [(hardware, interfaces)], token=member).status_code == 403
    # A component of another project is never accepted.
    assert _alias(world, project, requirement, [(elsewhere, elsewhere_category)]).status_code == 422
    # A requirement of another project is not found through this one.
    foreign = world.requirement(other, "Foreign")
    assert world.client.put(
        f"{_base(project)}/requirements/{foreign}/aliases", json={"places": []}, headers=auth_headers(world.token)
    ).status_code == 404


def test_placing_an_approved_requirement_is_allowed_but_moving_its_own_place_is_not(world):
    project = world.project()
    hardware, interfaces = _tree(world, project, "Hardware", "HW")
    requirement = world.requirement(project, "Bus")
    alias = _alias(world, project, requirement, [(hardware, interfaces)]).json()["aliases"][0]
    approved = world.client.post(
        f"{_base(project)}/requirements/{requirement}/approve", json={"comment": ""}, headers=auth_headers(world.token)
    )
    assert approved.status_code == 200, approved.text
    # Retiring and adding are placement, like a tag; promoting moves the own place, which an approved requirement locks.
    promote = world.client.post(
        f"{_base(project)}/requirements/{requirement}/aliases/{alias['id']}/promote", headers=auth_headers(world.token)
    )
    assert promote.status_code == 409
    assert _alias(world, project, requirement, []).status_code == 200


def test_making_an_alias_independent_respects_the_approved_link_lock_and_reports_what_was_not_copied(world):
    project = world.project()
    hardware, interfaces = _tree(world, project, "Hardware", "HW")
    original, target = world.requirement(project, "Bus"), world.requirement(project, "Power")
    related = world.link_types_by_name()["Related to"]
    assert world.generic_link(project, (REQ, original), related["id"], (REQ, target)).status_code == 201
    alias = _alias(world, project, original, [(hardware, interfaces)]).json()["aliases"][0]
    approved = world.client.post(
        f"{_base(project)}/requirements/{target}/approve", json={"comment": ""}, headers=auth_headers(world.token)
    )
    assert approved.status_code == 200, approved.text
    assert world.client.patch(
        f"{_base(project)}", json={"require_change_request_for_approved_links": True}, headers=auth_headers(world.token)
    ).status_code == 200
    resp = world.client.post(
        f"{_base(project)}/requirements/{original}/aliases/{alias['id']}/make-independent", json={}, headers=auth_headers(world.token)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["links_copied"] == 0
    assert [s["kind"] for s in body["skipped"]] == ["link"]
    assert "change request" in body["skipped"][0]["reason"]
    # The pair is still joined (the original is not approved), and the new draft was made.
    assert body["related_link_made"] is True
    assert _get(world, project, body["requirement_id"])["status"] == "draft"


def test_two_aliases_added_at_the_same_moment_never_share_a_code(world):
    """Alias codes come from the project's one requirement counter, locked and re-read like a requirement's own."""
    import threading

    from app.models.project import Project
    from app.models.requirement import Requirement
    from app.services import requirement_aliases as alias_service
    from app.services.placements import PlacementPair

    project = world.project()
    hardware, interfaces = _tree(world, project, "Hardware", "HW")
    first, second = world.requirement(project, "A"), world.requirement(project, "B")
    barrier = threading.Barrier(2)
    codes: list[str] = []
    guard = threading.Lock()

    def worker(requirement_id: uuid.UUID) -> None:
        with SessionLocal() as db:
            row = db.get(Requirement, requirement_id)
            barrier.wait()
            changed = alias_service.set_aliases(
                db, project=db.get(Project, uuid.UUID(project["id"])), requirement=row, actor_id=world.user_id,
                pairs=[PlacementPair(uuid.UUID(hardware), uuid.UUID(interfaces))],
            )
            db.commit()
            with guard:
                codes.extend(a.unique_code for a in changed.added)

    threads = [threading.Thread(target=worker, args=(rid,)) for rid in (first, second)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(codes) == 2 and len(set(codes)) == 2
