"""Tests for sharing: collections, their members and grants, the visibility rules (owner access, collection grants to a
project or its descendants, groups, union, children following a member, the organisation administrator), what a recipient
may and may not do, revocation and locked placeholders, organisation-owned elements and tenant isolation.
Every test builds its own organisation."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.database import SessionLocal
from app.models.audit import AuditEvent
from app.modules.architecture.models import ArchitectureElement
from app.modules.architecture.tests._helpers import (
    add_member,
    grant,
    grant_org_role,
    make_architect,
    make_collection,
    make_connection,
    make_element,
    make_org_element,
    org_base,
    org_element_types,
    project_base,
    setup,
    shared_names,
    status_of,
)
from tests.conftest import (
    auth_headers,
    create_org_admin_in,
    create_org_group,
    create_org_user,
    create_project,
    create_project_group,
    login,
)


def _world(client, admin_token, name):
    """An organisation with an owner project, a consumer project and an outsider project, each with a member who holds
    no module role there: `(org, owner project, consumer project, outsider project, admin token, consumer token,
    outsider token)`."""
    org, owner, admin = setup(client, admin_token, name)
    consumer = create_project(client, admin, org["id"], f"{name} consumer")
    outsider = create_project(client, admin, org["id"], f"{name} outsider")
    _cid, consumer_token = add_member(client, admin, org["id"], consumer["id"], f"{name.replace(' ', '.')}.c@example.com")
    _oid, outsider_token = add_member(client, admin, org["id"], outsider["id"], f"{name.replace(' ', '.')}.o@example.com")
    return org, owner, consumer, outsider, admin, consumer_token, outsider_token


def test_a_collection_is_created_renamed_and_deleted_by_an_architect_only(client, admin_token):
    org, owner, _c, _o, admin, member, _out = _world(client, admin_token, "Arch coll crud")
    base = project_base(owner["id"])
    element = make_element(client, admin, owner["id"], "Bus")
    collection = make_collection(client, admin, base, "Platform", members=[element["id"]])
    assert (collection["name"], collection["member_count"], collection["grant_count"]) == ("Platform", 0, 0)
    listed = client.get(f"{base}/collections", headers=auth_headers(admin)).json()
    assert [(c["name"], c["member_count"]) for c in listed] == [("Platform", 1)]

    assert client.post(f"{base}/collections", json={"name": "x"}, headers=auth_headers(member)).status_code in (403, 404)
    make_collection(client, admin, base, "platform", expect=400)
    renamed = client.put(f"{base}/collections/{collection['id']}", json={"name": "Shared infra"}, headers=auth_headers(admin))
    assert renamed.status_code == 200 and renamed.json()["name"] == "Shared infra"
    assert client.delete(f"{base}/collections/{collection['id']}", headers=auth_headers(admin)).status_code == 204
    assert client.get(f"{base}/collections/{collection['id']}", headers=auth_headers(admin)).status_code == 404
    with SessionLocal() as db:
        assert db.get(ArchitectureElement, uuid.UUID(element["id"])) is not None


def test_a_collection_holds_only_its_owners_elements(client, admin_token):
    org, owner, consumer, _o, admin, _m, _out = _world(client, admin_token, "Arch coll owner")
    mine = make_element(client, admin, owner["id"], "Mine")
    theirs = make_element(client, admin, consumer["id"], "Theirs")
    base = project_base(owner["id"])
    collection = make_collection(client, admin, base, "Mixed", members=[mine["id"]])
    resp = client.post(
        f"{base}/collections/{collection['id']}/members", json={"element_ids": [theirs["id"]]}, headers=auth_headers(admin),
    )
    assert resp.status_code == 400
    org_element = make_org_element(client, admin, org["id"], "Org one")
    resp = client.post(
        f"{base}/collections/{collection['id']}/members", json={"element_ids": [org_element["id"]]}, headers=auth_headers(admin),
    )
    assert resp.status_code == 400


def test_a_project_grant_shares_the_element_and_its_children_with_that_project_only(client, admin_token):
    org, owner, consumer, outsider, admin, member, outsider_member = _world(client, admin_token, "Arch grant project")
    top = make_element(client, admin, owner["id"], "Platform", type_name="System")
    child = make_element(client, admin, owner["id"], "Broker", parent_id=top["id"])
    unrelated = make_element(client, admin, owner["id"], "Unshared")
    base = project_base(owner["id"])
    assert status_of(client, member, consumer["id"], top["id"]) == 404
    collection = make_collection(client, admin, base, "Infra", members=[top["id"]])
    grant(client, admin, base, collection["id"], project_id=consumer["id"])

    assert status_of(client, member, consumer["id"], top["id"]) == 200
    assert status_of(client, member, consumer["id"], child["id"]) == 200
    assert status_of(client, member, consumer["id"], unrelated["id"]) == 404
    assert status_of(client, outsider_member, outsider["id"], top["id"]) == 404
    assert shared_names(client, member, consumer["id"]) == {"Platform", "Broker"}
    assert shared_names(client, outsider_member, outsider["id"]) == set()
    shown = client.get(f"{project_base(consumer['id'])}/elements/{top['id']}", headers=auth_headers(member)).json()
    assert shown["shared"] is True and shown["project_id"] == owner["id"]


def test_a_second_collection_adds_access_and_a_revoked_grant_removes_it(client, admin_token):
    org, owner, consumer, outsider, admin, member, outsider_member = _world(client, admin_token, "Arch grant union")
    a = make_element(client, admin, owner["id"], "A")
    b = make_element(client, admin, owner["id"], "B")
    base = project_base(owner["id"])
    first = make_collection(client, admin, base, "First", members=[a["id"], b["id"]])
    second = make_collection(client, admin, base, "Second", members=[a["id"]])
    one = grant(client, admin, base, first["id"], project_id=consumer["id"])
    two = grant(client, admin, base, second["id"], project_id=consumer["id"])
    assert shared_names(client, member, consumer["id"]) == {"A", "B"}
    assert client.delete(f"{base}/collections/{first['id']}/grants/{one['id']}", headers=auth_headers(admin)).status_code == 204
    assert shared_names(client, member, consumer["id"]) == {"A"}
    assert client.delete(f"{base}/collections/{second['id']}/grants/{two['id']}", headers=auth_headers(admin)).status_code == 204
    assert shared_names(client, member, consumer["id"]) == set()
    assert status_of(client, member, consumer["id"], a["id"]) == 404


def test_a_grant_with_descendants_reaches_child_projects_now_and_later(client, admin_token):
    org, owner, _consumer, _o, admin, _m, _out = _world(client, admin_token, "Arch grant nested")
    parent = create_project(client, admin, org["id"], "Arch grant nested parent", can_be_parent=True)
    element = make_element(client, admin, owner["id"], "Platform")
    base = project_base(owner["id"])
    collection = make_collection(client, admin, base, "Infra", members=[element["id"]])
    child = create_project(client, admin, org["id"], "Arch grant nested child", parent_project_id=parent["id"])
    _id, child_member = add_member(client, admin, org["id"], child["id"], "nested.child@example.com")
    grant(client, admin, base, collection["id"], project_id=parent["id"])
    assert status_of(client, child_member, child["id"], element["id"]) == 404

    other_grant = client.get(f"{base}/collections/{collection['id']}", headers=auth_headers(admin)).json()["grants"][0]
    client.delete(f"{base}/collections/{collection['id']}/grants/{other_grant['id']}", headers=auth_headers(admin))
    grant(client, admin, base, collection["id"], project_id=parent["id"], descendants=True)
    assert status_of(client, child_member, child["id"], element["id"]) == 200
    later = create_project(client, admin, org["id"], "Arch grant nested later", parent_project_id=parent["id"])
    _lid, later_member = add_member(client, admin, org["id"], later["id"], "nested.later@example.com")
    assert status_of(client, later_member, later["id"], element["id"]) == 200


def test_a_group_grant_reaches_its_members_in_any_project_and_a_stranger_does_not(client, admin_token):
    org, owner, consumer, outsider, admin, member, outsider_member = _world(client, admin_token, "Arch grant group")
    element = make_element(client, admin, owner["id"], "Platform")
    base = project_base(owner["id"])
    collection = make_collection(client, admin, base, "Infra", members=[element["id"]])
    member_id = create_org_user(client, admin, org["id"], "grp.member@example.com")
    client.post(f"/api/v1/projects/{outsider['id']}/roles", json={"user_id": member_id, "role": "member"}, headers=auth_headers(admin))
    token = login(client, "grp.member@example.com", "Password123!")
    group = create_org_group(client, admin, org["id"], "Platform users", users=[member_id])
    grant(client, admin, base, collection["id"], group={"type": "org_group", "id": group})
    assert status_of(client, token, outsider["id"], element["id"]) == 200
    assert status_of(client, outsider_member, outsider["id"], element["id"]) == 404
    assert shared_names(client, token, outsider["id"]) == {"Platform"}


def test_a_nested_organisation_group_and_a_project_group_grant_through_membership(client, admin_token):
    org, owner, consumer, outsider, admin, member, outsider_member = _world(client, admin_token, "Arch grant nested group")
    element = make_element(client, admin, owner["id"], "Platform")
    base = project_base(owner["id"])
    collection = make_collection(client, admin, base, "Infra", members=[element["id"]])
    user_id = create_org_user(client, admin, org["id"], "nested.grp@example.com")
    client.post(f"/api/v1/projects/{outsider['id']}/roles", json={"user_id": user_id, "role": "member"}, headers=auth_headers(admin))
    token = login(client, "nested.grp@example.com", "Password123!")
    inner = create_org_group(client, admin, org["id"], "Inner", users=[user_id])
    outer = create_org_group(client, admin, org["id"], "Outer", nested=[inner])
    grant(client, admin, base, collection["id"], group={"type": "org_group", "id": outer})
    assert status_of(client, token, outsider["id"], element["id"]) == 200

    other = make_element(client, admin, owner["id"], "Other")
    second = make_collection(client, admin, base, "Squad share", members=[other["id"]])
    squad = create_project_group(client, admin, consumer["id"], "Squad")
    grant(client, admin, base, second["id"], group={"type": "project_group", "id": squad})
    assert status_of(client, token, outsider["id"], other["id"]) == 404
    client.post(f"/api/v1/projects/{consumer['id']}/groups/{squad}/members", json={"user_id": user_id}, headers=auth_headers(admin))
    assert status_of(client, token, outsider["id"], other["id"]) == 200


def test_grants_cannot_leave_the_organisation_or_name_a_person(client, admin_token):
    org, owner, consumer, _o, admin, _m, _out = _world(client, admin_token, "Arch grant tenancy")
    other_org, other_admin = create_org_admin_in(client, admin_token, "Arch grant tenancy foreign")
    foreign_project = create_project(client, other_admin, other_org["id"], "Arch grant tenancy foreign project")
    foreign_group = create_org_group(client, other_admin, other_org["id"], "Foreign group")
    element = make_element(client, admin, owner["id"], "Platform")
    base = project_base(owner["id"])
    collection = make_collection(client, admin, base, "Infra", members=[element["id"]])
    grant(client, admin, base, collection["id"], project_id=foreign_project["id"], expect=400)
    grant(client, admin, base, collection["id"], group={"type": "org_group", "id": foreign_group}, expect=400)
    grant(client, admin, base, collection["id"], group={"type": "user", "id": str(uuid.uuid4())}, expect=400)
    grant(client, admin, base, collection["id"], project_id=owner["id"], expect=400)
    grant(client, admin, base, collection["id"], expect=400)
    grant(client, admin, base, collection["id"], project_id=consumer["id"])
    grant(client, admin, base, collection["id"], project_id=consumer["id"], expect=409)


def test_another_organisations_collection_looks_absent(client, admin_token):
    org, owner, _c, _o, admin, _m, _out = _world(client, admin_token, "Arch coll cross")
    other_org, other_admin, = create_org_admin_in(client, admin_token, "Arch coll cross foreign")
    from app.modules.architecture.tests._helpers import enable_module

    enable_module(client, other_admin, other_org["id"])
    foreign_project = create_project(client, other_admin, other_org["id"], "Arch coll cross foreign project")
    collection = make_collection(client, other_admin, project_base(foreign_project["id"]), "Theirs")
    url = f"{project_base(owner['id'])}/collections/{collection['id']}"
    assert client.get(url, headers=auth_headers(admin)).status_code == 404
    assert client.delete(url, headers=auth_headers(admin)).status_code == 404


def test_a_recipient_may_connect_to_a_shared_element_but_never_change_it(client, admin_token):
    org, owner, consumer, _o, admin, member, _out = _world(client, admin_token, "Arch recipient")
    shared = make_element(client, admin, owner["id"], "Platform", activate=True)
    mine = make_element(client, admin, consumer["id"], "Local app")
    base = project_base(owner["id"])
    collection = make_collection(client, admin, base, "Infra", members=[shared["id"]])
    grant(client, admin, base, collection["id"], project_id=consumer["id"])
    architect = make_architect(client, admin, org["id"], consumer["id"], "arch.recipient@example.com")

    link = make_connection(client, architect, consumer["id"], mine["id"], shared["id"])
    assert link["target_shared"] is True and link["target_element_name"] == "Platform" and link["source_shared"] is False

    mine_base = project_base(consumer["id"])
    h = auth_headers(architect)
    assert client.put(f"{mine_base}/elements/{shared['id']}", json={"version": 1, "name": "x"}, headers=h).status_code == 404
    assert client.post(f"{mine_base}/elements/{shared['id']}/archive", headers=h).status_code == 404
    assert client.delete(f"{mine_base}/elements/{shared['id']}", headers=h).status_code == 404
    assert client.post(f"{mine_base}/elements/{shared['id']}/ports", json={"name": "p"}, headers=h).status_code == 404
    stolen = client.post(
        f"{mine_base}/collections/{collection['id']}/members", json={"element_ids": [mine["id"]]}, headers=h,
    )
    assert stolen.status_code == 404
    counted = client.get(f"{mine_base}/elements/{shared['id']}", headers=h).json()
    assert counted["connection_count"] == 1


def test_the_owner_cannot_delete_an_element_another_project_connects_to_but_may_retire_it(client, admin_token):
    org, owner, consumer, _o, admin, _m, _out = _world(client, admin_token, "Arch in use")
    shared = make_element(client, admin, owner["id"], "Platform", activate=True)
    mine = make_element(client, admin, consumer["id"], "Local app")
    base = project_base(owner["id"])
    collection = make_collection(client, admin, base, "Infra", members=[shared["id"]])
    grant(client, admin, base, collection["id"], project_id=consumer["id"])
    make_connection(client, admin, consumer["id"], mine["id"], shared["id"])
    h = auth_headers(admin)
    assert client.delete(f"{base}/elements/{shared['id']}", headers=h).status_code == 409

    retired = client.post(f"{base}/elements/{shared['id']}/status", json={"version": shared["version"], "status": "retired"}, headers=h)
    assert retired.status_code == 200
    # Still visible to the project using it, but out of its pickers, and no new connection to it.
    architect = make_architect(client, admin, org["id"], consumer["id"], "arch.inuse@example.com")
    assert status_of(client, architect, consumer["id"], shared["id"]) == 200
    assert shared_names(client, architect, consumer["id"], open_only="true") == set()
    assert shared_names(client, architect, consumer["id"]) == {"Platform"}
    another = make_element(client, admin, consumer["id"], "Second app")
    make_connection(client, architect, consumer["id"], another["id"], shared["id"], expect=400)


def test_a_revoked_end_is_a_locked_placeholder_showing_only_its_code(client, admin_token):
    org, owner, consumer, _o, admin, _m, _out = _world(client, admin_token, "Arch placeholder")
    shared = make_element(client, admin, owner["id"], "Platform secret name", activate=True)
    mine = make_element(client, admin, consumer["id"], "Local app")
    base = project_base(owner["id"])
    collection = make_collection(client, admin, base, "Infra", members=[shared["id"]])
    given = grant(client, admin, base, collection["id"], project_id=consumer["id"])
    architect = make_architect(client, admin, org["id"], consumer["id"], "arch.placeholder@example.com")
    made = make_connection(client, architect, consumer["id"], mine["id"], shared["id"])
    client.delete(f"{base}/collections/{collection['id']}/grants/{given['id']}", headers=auth_headers(admin))

    shown = client.get(f"{project_base(consumer['id'])}/connections/{made['id']}", headers=auth_headers(architect)).json()
    assert shown["target_locked"] is True and shown["target_element_code"] == shared["unique_code"]
    assert shown["target_element_name"] == "" and shown["target_port_name"] is None
    assert "secret" not in str(shown)
    assert status_of(client, architect, consumer["id"], shared["id"]) == 404


def test_grants_members_and_collections_are_audited_without_names(client, admin_token):
    org, owner, consumer, _o, admin, _m, _out = _world(client, admin_token, "Arch coll audit")
    element = make_element(client, admin, owner["id"], "Platform")
    base = project_base(owner["id"])
    collection = make_collection(client, admin, base, "Confidential name", members=[element["id"]])
    given = grant(client, admin, base, collection["id"], project_id=consumer["id"], descendants=True)
    client.delete(f"{base}/collections/{collection['id']}/grants/{given['id']}", headers=auth_headers(admin))
    client.delete(f"{base}/collections/{collection['id']}/members/{element['id']}", headers=auth_headers(admin))
    client.delete(f"{base}/collections/{collection['id']}", headers=auth_headers(admin))
    with SessionLocal() as db:
        events = list(db.scalars(
            select(AuditEvent).where(AuditEvent.entity_type == "architecture_collection").order_by(AuditEvent.created_at)
        ))
    assert [e.action for e in events] == [
        "created", "members_added", "grant_added", "grant_revoked", "member_removed", "deleted",
    ]
    assert "Confidential" not in " ".join(str(e.detail) for e in events)
    added = events[2].detail
    assert added is not None and added["target"] == "project" and added["target_id"] == consumer["id"] and added["include_descendants"] is True


# --- Organisation-owned elements ----------------------------------------------


def test_an_organisation_element_is_numbered_from_the_organisation_and_only_an_admin_manages_it(client, admin_token):
    org, owner, consumer, _o, admin, member, _out = _world(client, admin_token, "Arch org element")
    first = make_org_element(client, admin, org["id"], "Platform")
    second = make_org_element(client, admin, org["id"], "Gateway", activate=True)
    project_element = make_element(client, admin, owner["id"], "Project one")
    assert (first["unique_code"], second["unique_code"]) == ("ELM-001", "ELM-002")
    assert project_element["unique_code"] == "ELM-001"
    assert first["organization_id"] == org["id"] and first["project_id"] is None

    plain = create_org_user(client, admin, org["id"], "arch.plain.org@example.com")
    plain_token = login(client, "arch.plain.org@example.com", "Password123!")
    resp = client.post(
        f"{org_base(org['id'])}/elements",
        json={"name": "x", "element_type_id": org_element_types(client, admin, org["id"])["System"]},
        headers=auth_headers(plain_token),
    )
    assert resp.status_code == 403
    grant_org_role(client, admin, org["id"], plain, "architecture_org_admin")
    assert client.get(f"{org_base(org['id'])}/elements", headers=auth_headers(plain_token)).status_code == 200


def test_an_organisation_element_uses_organisation_types_and_can_have_children_and_ports(client, admin_token):
    org, owner, _c, _o, admin, _m, _out = _world(client, admin_token, "Arch org tree")
    project_type = client.post(f"{project_base(owner['id'])}/element-types", json={"name": "Local"}, headers=auth_headers(admin)).json()
    make_org_element(client, admin, org["id"], "Bad", type_name="System", element_type_id=project_type["id"], expect=400)
    parent = make_org_element(client, admin, org["id"], "Platform")
    child = make_org_element(client, admin, org["id"], "Broker", parent_id=parent["id"], ports=[{"name": "Main"}])
    assert child["parent_id"] == parent["id"] and [p["name"] for p in child["ports"]] == ["Main"]
    project_parent = make_element(client, admin, owner["id"], "Project parent")
    make_org_element(client, admin, org["id"], "Cross", parent_id=project_parent["id"], expect=400)
    listed = client.get(f"{org_base(org['id'])}/elements", params={"roots_only": "true"}, headers=auth_headers(admin)).json()
    assert [e["name"] for e in listed] == ["Platform"]


def test_an_organisation_element_is_visible_to_a_project_only_through_a_grant(client, admin_token):
    org, owner, consumer, outsider, admin, member, outsider_member = _world(client, admin_token, "Arch org share")
    element = make_org_element(client, admin, org["id"], "Platform", activate=True)
    assert status_of(client, member, consumer["id"], element["id"]) == 404
    base = org_base(org["id"])
    collection = make_collection(client, admin, base, "Org infra", members=[element["id"]])
    grant(client, admin, base, collection["id"], project_id=consumer["id"])
    seen = client.get(f"{project_base(consumer['id'])}/elements/{element['id']}", headers=auth_headers(member))
    assert seen.status_code == 200 and seen.json()["shared"] is True and seen.json()["project_id"] is None
    assert status_of(client, outsider_member, outsider["id"], element["id"]) == 404
    assert client.get(f"{base}/elements/{element['id']}", headers=auth_headers(member)).status_code in (403, 404)
    # Only an administrator reads the organisation list in full; the grant does not widen the organisation page.
    assert client.get(f"{base}/collections", headers=auth_headers(member)).status_code in (403, 404)


def test_an_organisation_element_in_no_granted_collection_is_hidden_from_other_members(client, admin_token):
    org, owner, consumer, _o, admin, member, _out = _world(client, admin_token, "Arch org hidden")
    element = make_org_element(client, admin, org["id"], "Platform")
    h = auth_headers(member)
    assert client.get(f"{org_base(org['id'])}/elements", headers=h).json() == []
    assert client.get(f"{org_base(org['id'])}/elements/{element['id']}", headers=h).status_code == 404
    assert shared_names(client, member, consumer["id"]) == set()
    # Search and the link graph go through the summary hook, which must not show it either.
    from app.modules.registry import get_artefact_summaries_in_project

    with SessionLocal() as db:
        found = get_artefact_summaries_in_project(db, uuid.UUID(consumer["id"]), "architecture_element", [uuid.UUID(element["id"])])
    assert found == {}


def test_an_organisation_element_in_use_by_a_connection_cannot_be_deleted(client, admin_token):
    org, owner, consumer, _o, admin, _m, _out = _world(client, admin_token, "Arch org delete")
    element = make_org_element(client, admin, org["id"], "Platform", activate=True)
    mine = make_element(client, admin, consumer["id"], "Local app")
    base = org_base(org["id"])
    collection = make_collection(client, admin, base, "Org infra", members=[element["id"]])
    grant(client, admin, base, collection["id"], project_id=consumer["id"])
    architect = make_architect(client, admin, org["id"], consumer["id"], "arch.orgdelete@example.com")
    made = make_connection(client, architect, consumer["id"], mine["id"], element["id"])
    assert made["target_shared"] is True
    assert client.delete(f"{base}/elements/{element['id']}", headers=auth_headers(admin)).status_code == 409


def test_the_summary_hook_shows_a_project_only_what_is_granted_to_that_project(client, admin_token):
    from app.modules.registry import get_artefact_summaries_in_project

    org, owner, consumer, outsider, admin, _m, _out = _world(client, admin_token, "Arch summary")
    granted = make_element(client, admin, owner["id"], "Granted")
    plain = make_element(client, admin, owner["id"], "Plain")
    group_only = make_element(client, admin, owner["id"], "Group only")
    base = project_base(owner["id"])
    project_share = make_collection(client, admin, base, "To project", members=[granted["id"]])
    grant(client, admin, base, project_share["id"], project_id=consumer["id"])
    group = create_org_group(client, admin, org["id"], "Everyone")
    group_share = make_collection(client, admin, base, "To group", members=[group_only["id"]])
    grant(client, admin, base, group_share["id"], group={"type": "org_group", "id": group})
    ids = [uuid.UUID(x["id"]) for x in (granted, plain, group_only)]
    with SessionLocal() as db:
        for project, expected in ((consumer, {"Granted"}), (outsider, set()), (owner, {"Granted", "Plain", "Group only"})):
            found = get_artefact_summaries_in_project(db, uuid.UUID(project["id"]), "architecture_element", ids)
            assert {s.label.split(" ", 1)[1] for s in (found or {}).values()} == expected
