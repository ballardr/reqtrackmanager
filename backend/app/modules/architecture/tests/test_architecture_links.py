"""Tests for how elements and connections take part in the shared link system: the plan's link types exist, a
requirement is allocated to an element and constrains a connection through the generic link endpoint, the link is
readable from both ends, restricted types refuse the wrong ends, and deleting a record removes its links. Every test
builds its own organisation."""

from __future__ import annotations

import uuid

from app.modules.architecture.tests._helpers import make_connection, make_element, project_base
from tests.link_world import World

ELEMENT = "architecture_element"
CONNECTION = "architecture_connection"


def _world(client, admin_token):
    world = World(client, admin_token, "Arch links")
    world.enable("architecture")
    return world


def test_the_architecture_link_types_exist_and_the_module_s_own_are_restricted_to_their_ends(client, admin_token):
    world = _world(client, admin_token)
    types = world.link_types_by_name()
    for forward in ("Allocated to", "Constrains", "Affected by", "Concerns", "Describes", "Verified by"):
        assert forward in types, sorted(types)
    # "Allocated to" and "Verified by" are core defaults the module reuses; the others are the module's own.
    assert types["Allocated to"]["reverse_name"] == "Has allocated" and types["Constrains"]["reverse_name"] == "Constrained by"
    assert types["Constrains"]["allowed_target_types"] == ["architecture_connection"]
    assert sorted(types["Affected by"]["allowed_source_types"]) == ["architecture_connection", "architecture_element"]


def test_a_requirement_is_allocated_to_an_element_and_constrains_a_connection(client, admin_token):
    world = _world(client, admin_token)
    project = world.project("Arch links project")
    requirement = world.requirement(project)
    a = make_element(client, world.token, project["id"], "Sensor node")
    b = make_element(client, world.token, project["id"], "Gateway")
    connection = make_connection(client, world.token, project["id"], a["id"], b["id"])
    types = world.link_types_by_name()

    allocation = world.generic_link(project, ("requirement", requirement), types["Allocated to"]["id"], (ELEMENT, uuid.UUID(a["id"])))
    assert allocation.status_code in (200, 201), allocation.text
    constraint = world.generic_link(project, ("requirement", requirement), types["Constrains"]["id"], (CONNECTION, uuid.UUID(connection["id"])))
    assert constraint.status_code in (200, 201), constraint.text

    from_element = world.graph(project, (ELEMENT, uuid.UUID(a["id"]))).json()
    assert str(requirement) in {n["id"] for n in from_element["nodes"]}
    from_connection = world.graph(project, (CONNECTION, uuid.UUID(connection["id"]))).json()
    assert str(requirement) in {n["id"] for n in from_connection["nodes"]}
    labels = {n["id"]: n["label"] for n in from_element["nodes"]}
    assert labels[a["id"]] == "ELM-001 Sensor node"


def test_a_restricted_link_type_refuses_the_wrong_end(client, admin_token):
    world = _world(client, admin_token)
    project = world.project("Arch links wrong end")
    requirement = world.requirement(project)
    a = make_element(client, world.token, project["id"], "Node")
    constrains = world.link_types_by_name()["Constrains"]["id"]
    wrong = world.generic_link(project, ("requirement", requirement), constrains, (ELEMENT, uuid.UUID(a["id"])))
    assert wrong.status_code in (400, 422), wrong.text


def test_deleting_an_element_removes_its_links(client, admin_token):
    world = _world(client, admin_token)
    project = world.project("Arch links delete")
    requirement = world.requirement(project)
    a = make_element(client, world.token, project["id"], "Doomed")
    allocated = world.link_types_by_name()["Allocated to"]["id"]
    assert world.generic_link(project, ("requirement", requirement), allocated, (ELEMENT, uuid.UUID(a["id"]))).status_code in (200, 201)
    from tests.conftest import auth_headers

    assert world.client.delete(f"{project_base(project['id'])}/elements/{a['id']}", headers=auth_headers(world.token)).status_code == 204
    graph = world.graph(project, ("requirement", requirement)).json()
    assert a["id"] not in {n["id"] for n in graph["nodes"]}


def test_a_requirement_links_to_a_shared_organisation_element_only_while_it_is_granted(client, admin_token):
    from app.modules.architecture.tests._helpers import grant, make_collection, make_org_element, org_base
    from tests.conftest import auth_headers

    world = _world(client, admin_token)
    project = world.project("Arch links shared")
    requirement = world.requirement(project)
    shared = make_org_element(client, world.token, world.org["id"], "Corporate platform", activate=True)
    types = world.link_types_by_name()
    before = world.generic_link(project, ("requirement", requirement), types["Allocated to"]["id"], (ELEMENT, uuid.UUID(shared["id"])))
    assert before.status_code == 404

    base = org_base(world.org["id"])
    collection = make_collection(client, world.token, base, "Org infra", members=[shared["id"]])
    given = grant(client, world.token, base, collection["id"], project_id=project["id"])
    allocation = world.generic_link(project, ("requirement", requirement), types["Allocated to"]["id"], (ELEMENT, uuid.UUID(shared["id"])))
    assert allocation.status_code in (200, 201), allocation.text

    # Used elsewhere: the organisation element can no longer be deleted, only retired.
    assert client.delete(f"{base}/elements/{shared['id']}", headers=auth_headers(world.token)).status_code == 409
    client.delete(f"{base}/collections/{collection['id']}/grants/{given['id']}", headers=auth_headers(world.token))
    after = world.generic_link(project, ("requirement", requirement), types["Allocated to"]["id"], (ELEMENT, uuid.UUID(shared["id"])))
    assert after.status_code == 404


def test_a_requirement_links_to_a_project_owned_element_shared_with_its_project_and_the_owner_cannot_delete_it(client, admin_token):
    """A grant gives the recipient project read, place, connect and link; while it lasts the owner cannot delete the
    element (the sharing is revoked first), and a stranger project still cannot link to it."""
    from app.modules.architecture.tests._helpers import grant, make_collection
    from tests.conftest import auth_headers

    world = _world(client, admin_token)
    consumer = world.project("Arch links consumer")
    owner = world.project("Arch links owner")
    requirement = world.requirement(consumer)
    shared = make_element(client, world.token, owner["id"], "Platform", activate=True)
    base = project_base(owner["id"])
    collection = make_collection(client, world.token, base, "Infra", members=[shared["id"]])
    grant(client, world.token, base, collection["id"], project_id=consumer["id"])
    types = world.link_types_by_name()
    stranger = world.project("Arch links stranger")
    stranger_requirement = world.requirement(stranger)
    denied = world.generic_link(stranger, ("requirement", stranger_requirement), types["Allocated to"]["id"], (ELEMENT, uuid.UUID(shared["id"])))
    assert denied.status_code == 404
    allowed = world.generic_link(consumer, ("requirement", requirement), types["Allocated to"]["id"], (ELEMENT, uuid.UUID(shared["id"])))
    assert allowed.status_code in (200, 201), allowed.text

    h = auth_headers(world.token)
    assert client.delete(f"{base}/elements/{shared['id']}", headers=h).status_code == 409
    revoke = client.get(f"{base}/collections/{collection['id']}", headers=h).json()["grants"][0]
    client.delete(f"{base}/collections/{collection['id']}/grants/{revoke['id']}", headers=h)
    assert client.delete(f"{base}/elements/{shared['id']}", headers=h).status_code == 204
