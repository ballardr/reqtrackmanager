"""Tests for the connection type tree: the seeded groups, parents on create and edit (two parents, tiers, cycles, depth),
a connection typed with a group and refined later, descendant expansion in the connection filter and the view switch
rules, hide and restore with parents, inherited configuration, deletion, and the bundle round trips. Every test builds
its own organisation."""

from __future__ import annotations

import io
import json
import uuid
import zipfile

import pytest
from sqlalchemy import event, select

from app.database import SessionLocal, engine
from app.modules.architecture.connection_tree import MAX_TYPE_DEPTH, check_tree, closure_of
from app.modules.architecture.models import ArchitectureConnectionType
from app.modules.architecture.service import DEFAULT_CONNECTION_TYPE_PARENTS, DEFAULT_CONNECTION_TYPES
from app.modules.architecture.tests._helpers import (
    connection_types,
    enable_module,
    make_connection,
    make_diagram,
    make_element,
    org_base,
    place_all,
    project_base,
    save_toggles,
    setup,
    view,
)
from tests.conftest import auth_headers, create_org_admin_in, create_project


def _ids(n: int) -> list[uuid.UUID]:
    return [uuid.uuid4() for _ in range(n)]


def _rows(client, token, url) -> dict[str, dict]:
    resp = client.get(url, headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    return {r["name"]: r for r in resp.json()}


def _post(client, token, url, expect=201, **body) -> dict:
    resp = client.post(url, json=body, headers=auth_headers(token))
    assert resp.status_code == expect, resp.text
    return resp.json()


def _patch(client, token, url, expect=200, **body) -> dict:
    resp = client.patch(url, json=body, headers=auth_headers(token))
    assert resp.status_code == expect, resp.text
    return resp.json()


# --- The rule on its own ------------------------------------------------------


def test_the_tree_rule_refuses_self_parent_cycles_and_deep_chains():
    a, b, c = _ids(3)
    check_tree({}, a, [])
    check_tree({b: {a}}, c, [b, a])  # two parents, one an ancestor of the other: allowed
    with pytest.raises(ValueError, match="own parent"):
        check_tree({}, a, [a])
    with pytest.raises(ValueError, match="beneath itself"):
        check_tree({b: {a}, c: {b}}, a, [c])  # a > b > c > a

    chain = _ids(MAX_TYPE_DEPTH)
    links = {chain[i]: {chain[i - 1]} for i in range(1, MAX_TYPE_DEPTH)}
    check_tree(links, uuid.uuid4(), [chain[-2]])  # the twelfth level is the last allowed
    with pytest.raises(ValueError, match="at most"):
        check_tree(links, uuid.uuid4(), [chain[-1]])
    # Moving a root beneath a chain deepens everything under that root, so the levels below are counted too.
    short = {chain[i]: {chain[i - 1]} for i in range(1, 10)}
    root, middle, leaf = _ids(3)
    below = {**short, middle: {root}, leaf: {middle}}
    check_tree(below, root, [chain[8]])  # 9 + 3 levels = 12
    with pytest.raises(ValueError, match="at most"):
        check_tree(below, root, [chain[9]])  # 10 + 3 levels = 13


# --- The seeded tree ----------------------------------------------------------


def test_a_new_organisation_is_seeded_with_the_groups_and_their_members(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch tree seed")
    rows = _rows(client, token, f"{org_base(org['id'])}/connection-types")
    assert list(rows) == [d[0] for d in DEFAULT_CONNECTION_TYPES]
    by_id = {r["id"]: r["name"] for r in rows.values()}
    for name, row in rows.items():
        assert sorted(by_id[p] for p in row["parent_ids"]) == sorted(DEFAULT_CONNECTION_TYPE_PARENTS.get(name, ()))
    assert rows["Serial bus"]["parent_ids"] == [] and len(rows["I2C"]["parent_ids"]) == 1
    # A group is itself a usable type, so a connection can start generic and be refined later.
    assert {"Power", "Serial bus", "Unspecified hardware link"} <= set(connection_types(client, token, project["id"]))


# --- Parents on create and edit -----------------------------------------------


def test_a_type_has_several_parents_and_a_change_replaces_them(client, admin_token):
    org, _project, token = setup(client, admin_token, "Arch tree parents")
    base = f"{org_base(org['id'])}/connection-types"
    rows = _rows(client, token, base)
    serial, network = rows["Serial bus"]["id"], rows["Network"]["id"]

    created = _post(client, token, base, name="Board link", parent_ids=[serial, network, serial])
    assert sorted(created["parent_ids"]) == sorted([serial, network])  # a repeated parent counts once

    kept = _patch(client, token, f"{base}/{created['id']}", name="Board-to-board")
    assert sorted(kept["parent_ids"]) == sorted([serial, network])  # an edit that omits parent_ids keeps them
    one = _patch(client, token, f"{base}/{created['id']}", parent_ids=[network])
    assert one["parent_ids"] == [network]
    root = _patch(client, token, f"{base}/{created['id']}", parent_ids=[])
    assert root["parent_ids"] == []
    assert _rows(client, token, base)["Board-to-board"]["parent_ids"] == []


def test_a_cycle_a_self_parent_and_a_chain_that_is_too_deep_are_refused(client, admin_token):
    org, _project, token = setup(client, admin_token, "Arch tree cycle")
    base = f"{org_base(org['id'])}/connection-types"
    a = _post(client, token, base, name="A")
    b = _post(client, token, base, name="B", parent_ids=[a["id"]])
    c = _post(client, token, base, name="C", parent_ids=[b["id"]])
    _patch(client, token, f"{base}/{a['id']}", expect=400, parent_ids=[c["id"]])
    _patch(client, token, f"{base}/{a['id']}", expect=400, parent_ids=[a["id"]])
    _patch(client, token, f"{base}/{b['id']}", expect=400, parent_ids=[c["id"]])

    parent = c
    for level in range(4, MAX_TYPE_DEPTH + 1):
        parent = _post(client, token, base, name=f"L{level}", parent_ids=[parent["id"]])
    _post(client, token, base, expect=400, name="Too deep", parent_ids=[parent["id"]])


def test_a_parent_must_be_a_type_the_owner_can_use(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch tree tiers")
    other_org, other_token = create_org_admin_in(client, admin_token, "Arch tree tiers other")
    enable_module(client, other_token, other_org["id"])
    foreign = _rows(client, other_token, f"{org_base(other_org['id'])}/connection-types")["Serial bus"]["id"]
    org_url, project_url = f"{org_base(org['id'])}/connection-types", f"{project_base(project['id'])}/connection-types"
    serial = _rows(client, token, org_url)["Serial bus"]["id"]

    _post(client, token, org_url, expect=400, name="Leaks", parent_ids=[foreign])
    _post(client, token, org_url, expect=400, name="Unknown", parent_ids=[str(uuid.uuid4())])
    # A project type may sit under an organisation default, but an organisation type never under a project's.
    mine = _post(client, token, project_url, name="Project bus", parent_ids=[serial])
    assert mine["parent_ids"] == [serial] and mine["project_id"] == project["id"]
    _patch(client, token, f"{org_url}/{serial}", expect=400, parent_ids=[mine["id"]])
    _post(client, token, project_url, expect=400, name="Foreign parent", parent_ids=[foreign])


def test_a_hidden_parent_cannot_be_chosen_but_a_link_already_made_is_kept(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch tree hidden parent")
    org_url, project_url = f"{org_base(org['id'])}/connection-types", f"{project_base(project['id'])}/connection-types"
    serial = _rows(client, token, org_url)["Serial bus"]["id"]
    mine = _post(client, token, project_url, name="Project bus", parent_ids=[serial])

    assert client.delete(f"{project_url}/{serial}", headers=auth_headers(token)).status_code == 204  # hides the group
    _post(client, token, project_url, expect=400, name="Another", parent_ids=[serial])
    renamed = _patch(client, token, f"{project_url}/{mine['id']}", name="Project bus 2", parent_ids=[serial])
    assert renamed["parent_ids"] == [serial]
    # The child is still listed (as a root of the project's tree, since its parent is hidden).
    assert "Project bus 2" in _rows(client, token, project_url) and "Serial bus" not in _rows(client, token, project_url)


# --- A connection typed with a group, refined later ---------------------------


def test_a_connection_starts_on_a_group_and_is_refined_later(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch tree refine")
    pid = project["id"]
    types = connection_types(client, token, pid)
    a, b = make_element(client, token, pid, "Board A", type_name="Board"), make_element(client, token, pid, "Board B", type_name="Board")
    made = make_connection(client, token, pid, a["id"], b["id"], type_name="Serial bus")
    assert made["connection_type_name"] == "Serial bus"
    resp = client.put(
        f"{project_base(pid)}/connections/{made['id']}",
        json={"version": made["version"], "connection_type_id": types["I2C"]}, headers=auth_headers(token),
    )
    assert resp.status_code == 200 and resp.json()["connection_type_name"] == "I2C" and resp.json()["version"] == 2


# --- Descendant expansion -----------------------------------------------------


def test_filtering_by_a_group_finds_the_connections_of_every_member(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch tree filter")
    pid = project["id"]
    types = connection_types(client, token, pid)
    a, b = make_element(client, token, pid, "A", type_name="Board"), make_element(client, token, pid, "B", type_name="Board")
    i2c = make_connection(client, token, pid, a["id"], b["id"], type_name="I2C", name="Sensor bus")
    spi = make_connection(client, token, pid, a["id"], b["id"], type_name="SPI", name="Flash bus")
    group = make_connection(client, token, pid, a["id"], b["id"], type_name="Serial bus", name="Generic bus")
    eth = make_connection(client, token, pid, a["id"], b["id"], type_name="Ethernet", name="Backhaul")

    def listed(type_id):
        resp = client.get(f"{project_base(pid)}/connections", params={"connection_type_id": type_id}, headers=auth_headers(token))
        assert resp.status_code == 200, resp.text
        return {c["id"] for c in resp.json()}

    assert listed(types["Serial bus"]) == {i2c["id"], spi["id"], group["id"]}
    assert listed(types["I2C"]) == {i2c["id"]}
    assert listed(types["Network"]) == {eth["id"]}
    assert listed(types["Power"]) == set()


def test_a_view_switch_rule_naming_a_group_hides_its_members_too(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch tree switch")
    pid = project["id"]
    types = connection_types(client, token, pid)
    a, b = make_element(client, token, pid, "A", type_name="Board"), make_element(client, token, pid, "B", type_name="Board")
    i2c = make_connection(client, token, pid, a["id"], b["id"], type_name="I2C")
    eth = make_connection(client, token, pid, a["id"], b["id"], type_name="Ethernet")
    diagram = place_all(client, token, pid, make_diagram(client, token, pid, "Boards"), a["id"], b["id"])
    diagram = save_toggles(client, token, pid, diagram, [
        {"name": "Buses", "default_on": True, "rule": {"connection_type_ids": [types["Serial bus"]]}},
    ])
    toggle = view(client, token, pid, diagram["id"])["toggles"][0]

    on = view(client, token, pid, diagram["id"])
    assert {c["id"] for e in on["edges"] for c in e["connections"]} == {i2c["id"], eth["id"]}
    off = view(client, token, pid, diagram["id"], toggle_off=[toggle["id"]])
    assert {c["id"] for e in off["edges"] for c in e["connections"]} == {eth["id"]}


def test_closure_of_follows_every_parent_to_any_depth(client, admin_token):
    org, _project, token = setup(client, admin_token, "Arch tree closure")
    base = f"{org_base(org['id'])}/connection-types"
    root = _post(client, token, base, name="Root")
    left = _post(client, token, base, name="Left", parent_ids=[root["id"]])
    right = _post(client, token, base, name="Right", parent_ids=[root["id"]])
    leaf = _post(client, token, base, name="Leaf", parent_ids=[left["id"], right["id"]])
    with SessionLocal() as db:
        ids = {n: uuid.UUID(r["id"]) for n, r in {"root": root, "left": left, "right": right, "leaf": leaf}.items()}
        assert closure_of(db, [ids["root"]]) == set(ids.values())
        assert closure_of(db, [ids["right"]]) == {ids["right"], ids["leaf"]}
        assert closure_of(db, [ids["leaf"]]) == {ids["leaf"]}
        assert closure_of(db, []) == set()


# --- Hide, restore, inherit, delete -------------------------------------------


def test_deleting_a_group_makes_its_children_roots_and_a_used_type_stays(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch tree delete")
    base = f"{org_base(org['id'])}/connection-types"
    group = _post(client, token, base, name="Group")
    child = _post(client, token, base, name="Member", parent_ids=[group["id"]])
    assert client.delete(f"{base}/{group['id']}", headers=auth_headers(token)).status_code == 204
    assert _rows(client, token, base)["Member"]["parent_ids"] == []

    pid = project["id"]
    a, b = make_element(client, token, pid, "A"), make_element(client, token, pid, "B")
    make_connection(client, token, pid, a["id"], b["id"], type_name="Member")
    assert client.delete(f"{base}/{child['id']}", headers=auth_headers(token)).status_code == 409


def test_a_child_project_that_changes_an_inherited_configuration_keeps_the_tree(client, admin_token):
    org, token = create_org_admin_in(client, admin_token, "Arch tree inherit")
    enable_module(client, token, org["id"])
    parent = create_project(client, token, org["id"], "Arch tree inherit parent", can_be_parent=True)
    parent_url = f"{project_base(parent['id'])}/connection-types"
    serial = _rows(client, token, parent_url)["Serial bus"]["id"]
    own = _post(client, token, parent_url, name="Parent bus", parent_ids=[serial])
    nested = _post(client, token, parent_url, name="Parent bus detail", parent_ids=[own["id"]])
    child_id = create_project(client, token, org["id"], "Arch tree inherit child", parent_project_id=parent["id"])["id"]
    child_url = f"{project_base(child_id)}/connection-types"
    assert _rows(client, token, child_url)["Parent bus detail"]["id"] == nested["id"]  # inherited, not copied

    added = _post(client, token, child_url, name="Child only", parent_ids=[serial])
    copies = _rows(client, token, child_url)
    assert copies["Child only"]["id"] == added["id"]
    copied_detail, copied_bus = copies["Parent bus detail"], copies["Parent bus"]
    assert copied_detail["id"] != nested["id"] and copied_detail["project_id"] == child_id
    assert copied_detail["parent_ids"] == [copied_bus["id"]]  # points at the child's copy, not the ancestor's row
    assert copied_bus["parent_ids"] == [serial]  # an organisation parent is shared
    assert _rows(client, token, parent_url)["Parent bus detail"]["parent_ids"] == [own["id"]]  # the ancestor is untouched


# --- Bundles ------------------------------------------------------------------


def test_the_organisation_tree_survives_an_organisation_bundle(client, admin_token):
    org, _project, token = setup(client, admin_token, "Arch tree org bundle")
    h = auth_headers(token)
    base = f"{org_base(org['id'])}/connection-types"
    serial = _rows(client, token, base)["Serial bus"]["id"]
    _post(client, token, base, name="Board link", parent_ids=[serial])

    export = client.get(f"/api/v1/orgs/{org['id']}/export", headers=h)
    assert export.status_code == 200, export.text
    entries = json.loads(zipfile.ZipFile(io.BytesIO(export.content)).read("org.json"))["architecture_connection_types"]
    assert next(e for e in entries if e["name"] == "Board link")["parent_names"] == ["Serial bus"]
    assert next(e for e in entries if e["name"] == "Serial bus")["parent_names"] == []

    imported = client.post(
        "/api/v1/orgs/import", data={"name": "Arch tree org bundle copy"},
        files={"file": ("bundle.zip", export.content, "application/zip")}, headers=auth_headers(admin_token),
    )
    assert imported.status_code == 201, imported.text
    new_org = uuid.UUID(imported.json()["organization"]["id"])
    with SessionLocal() as db:
        rows = {r.name: r for r in db.scalars(select(ArchitectureConnectionType).where(ArchitectureConnectionType.organization_id == new_org))}
        by_id = {r.id: r.name for r in rows.values()}
        assert [by_id[p] for p in rows["Board link"].parent_ids] == ["Serial bus"]
        assert [by_id[p] for p in rows["I2C"].parent_ids] == ["Serial bus"]  # a seeded type is not doubled or re-parented
        assert len(rows) == len(DEFAULT_CONNECTION_TYPES) + 1


def test_a_project_tree_survives_a_project_bundle(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch tree project bundle")
    h = auth_headers(token)
    base = f"{project_base(project['id'])}/connection-types"
    serial = _rows(client, token, base)["Serial bus"]["id"]
    # The child comes first in the order, its parent after: the import links once every row exists.
    child = _post(client, token, base, name="Local detail")
    parent = _post(client, token, base, name="Local bus", parent_ids=[serial])
    _patch(client, token, f"{base}/{child['id']}", parent_ids=[parent["id"]])

    export = client.get(f"/api/v1/projects/{project['id']}/export", headers=h)
    assert export.status_code == 200, export.text
    entries = json.loads(zipfile.ZipFile(io.BytesIO(export.content)).read("project.json"))["architecture_project_connection_types"]
    assert {e["name"]: e["parent_names"] for e in entries} == {"Local detail": ["Local bus"], "Local bus": ["Serial bus"]}

    imported = client.post(
        "/api/v1/projects/import", data={"organization_id": org["id"], "name": "Arch tree project copy"},
        files={"file": ("bundle.zip", export.content, "application/zip")}, headers=h,
    )
    assert imported.status_code == 201, imported.text
    copy_url = f"{project_base(imported.json()['project']['id'])}/connection-types"
    rows = _rows(client, token, copy_url)
    by_id = {r["id"]: r["name"] for r in rows.values()}
    assert [by_id[p] for p in rows["Local detail"]["parent_ids"]] == ["Local bus"]
    assert [by_id[p] for p in rows["Local bus"]["parent_ids"]] == ["Serial bus"]


def test_a_parent_missing_from_the_target_is_reported_not_guessed(client, admin_token):
    org, project, token = setup(client, admin_token, "Arch tree missing parent")
    h = auth_headers(token)
    base = f"{project_base(project['id'])}/connection-types"
    serial = _rows(client, token, base)["Serial bus"]["id"]
    _post(client, token, base, name="Local bus", parent_ids=[serial])
    export = client.get(f"/api/v1/projects/{project['id']}/export", headers=h)
    # The organisation drops the group before the import.
    assert client.delete(f"{org_base(org['id'])}/connection-types/{serial}", headers=h).status_code == 204

    imported = client.post(
        "/api/v1/projects/import", data={"organization_id": org["id"], "name": "Arch tree missing parent copy"},
        files={"file": ("bundle.zip", export.content, "application/zip")}, headers=h,
    )
    assert imported.status_code == 201, imported.text
    assert any("Serial bus" in w for w in imported.json().get("warnings", []))
    rows = _rows(client, token, f"{project_base(imported.json()['project']['id'])}/connection-types")
    assert rows["Local bus"]["parent_ids"] == []


# --- Cost ---------------------------------------------------------------------


def test_listing_the_types_costs_the_same_however_many_there_are(client, admin_token):
    org, _project, token = setup(client, admin_token, "Arch tree statements")
    base = f"{org_base(org['id'])}/connection-types"
    serial = _rows(client, token, base)["Serial bus"]["id"]

    statements: list[str] = []

    def record(conn, cursor, statement, *rest):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        client.get(base, headers=auth_headers(token))
        small = len(statements)
        for i in range(12):
            _post(client, token, base, name=f"Extra {i}", parent_ids=[serial])
        statements.clear()
        client.get(base, headers=auth_headers(token))
        large = len(statements)
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert large == small
