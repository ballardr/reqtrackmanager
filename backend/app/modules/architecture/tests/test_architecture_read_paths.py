"""The read-path enumeration for shared elements: for a person with no access an element appears on no read path (detail,
the shared list, a connection's end, the global search, the summary hook, the organisation list), for a person with access
it appears on each, and the statements behind the shared reads do not grow with the number of elements. Later phases add
their own paths (link candidates, diagram, report, interchange, MCP) here. Every test builds its own organisation."""

from __future__ import annotations

import uuid

from sqlalchemy import event

from app.database import SessionLocal, engine
from app.modules.architecture.tests._helpers import (
    add_member,
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
from app.modules.registry import get_artefact_summaries_in_project
from tests.conftest import auth_headers, create_project

ALL_FIELDS = ["id", "title", "description", "ports", "protocol"]


def _hits(client, token, project_id, text):
    resp = client.post(
        "/api/v1/search", json={"q": text, "scope": "project", "project_id": project_id, "fields": ALL_FIELDS},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    return [h["title"] for h in resp.json()["hits"] if h["type"] == "architecture_element"]


def _world(client, admin_token, name):
    org, owner, token = setup(client, admin_token, name)
    consumer = create_project(client, token, org["id"], f"{name} consumer")
    outsider = create_project(client, token, org["id"], f"{name} outsider")
    _i, consumer_member = add_member(client, token, org["id"], consumer["id"], f"{name.replace(' ', '.')}.c@example.com")
    _j, outsider_member = add_member(client, token, org["id"], outsider["id"], f"{name.replace(' ', '.')}.o@example.com")
    return org, owner, consumer, outsider, token, consumer_member, outsider_member


def test_an_organisation_element_appears_on_every_read_path_only_for_a_granted_project(client, admin_token):
    org, owner, consumer, outsider, token, member, outsider_member = _world(client, admin_token, "Arch reads org")
    element = make_org_element(client, token, org["id"], "Zephyr platform", activate=True)
    base = org_base(org["id"])
    collection = make_collection(client, token, base, "Org infra", members=[element["id"]])
    grant(client, token, base, collection["id"], project_id=consumer["id"])
    local = make_element(client, token, consumer["id"], "Local app")
    architect = make_architect(client, token, org["id"], consumer["id"], "arch.reads.org@example.com")
    connection = make_connection(client, architect, consumer["id"], local["id"], element["id"])

    # With access.
    assert _hits(client, member, consumer["id"], "zephyr") == ["Zephyr platform"]
    shown = client.get(f"{project_base(consumer['id'])}/connections/{connection['id']}", headers=auth_headers(member)).json()
    assert shown["target_element_name"] == "Zephyr platform" and shown["target_locked"] is False

    # Without access.
    assert _hits(client, _outsider_token(client, token, org, outsider), outsider["id"], "zephyr") == []
    with SessionLocal() as db:
        found = get_artefact_summaries_in_project(db, uuid.UUID(outsider["id"]), "architecture_element", [uuid.UUID(element["id"])])
    assert found == {}
    assert client.get(f"{base}/elements", headers=auth_headers(outsider_member)).json() == []


def _outsider_token(client, token, org, outsider):
    return make_architect(client, token, org["id"], outsider["id"], f"outsider.{uuid.uuid4().hex[:6]}@example.com")


def test_a_project_owned_element_is_found_from_a_project_the_person_can_open_but_not_one_they_cannot(client, admin_token):
    org, owner, consumer, outsider, token, member, outsider_member = _world(client, admin_token, "Arch reads project")
    make_element(client, token, owner["id"], "Quasar bus", activate=True)
    assert _hits(client, token, owner["id"], "quasar") == ["Quasar bus"]
    # The outsider is not a member of the owning project, so the project search does not reach it.
    assert _hits(client, outsider_member, outsider["id"], "quasar") == []


def test_the_shared_reads_use_the_same_number_of_statements_however_many_elements_are_shared(client, admin_token):
    org, owner, consumer, _o, token, member, _out = _world(client, admin_token, "Arch reads flat")
    base = project_base(owner["id"])
    first = [make_element(client, token, owner["id"], f"Shared {i}", ports=[{"name": "Main"}]) for i in range(2)]
    collection = make_collection(client, token, base, "Infra", members=[e["id"] for e in first])
    grant(client, token, base, collection["id"], project_id=consumer["id"])
    architect = make_architect(client, token, org["id"], consumer["id"], "arch.reads.flat@example.com")
    local = make_element(client, token, consumer["id"], "Local app")
    for e in first:
        make_connection(client, architect, consumer["id"], local["id"], e["id"])
    urls = [
        f"{project_base(consumer['id'])}/elements/shared", f"{project_base(consumer['id'])}/connections",
        f"{project_base(consumer['id'])}/elements/{first[0]['id']}",
    ]

    def count(url) -> int:
        seen: list[str] = []

        def record(_conn, _cursor, statement, *_args):
            seen.append(statement)

        event.listen(engine, "before_cursor_execute", record)
        try:
            assert client.get(url, headers=auth_headers(architect)).status_code == 200
        finally:
            event.remove(engine, "before_cursor_execute", record)
        return len(seen)

    few = [count(u) for u in urls]
    more = [make_element(client, token, owner["id"], f"More {i}", ports=[{"name": "Main"}]) for i in range(6)]
    client.post(f"{base}/collections/{collection['id']}/members", json={"element_ids": [e["id"] for e in more]}, headers=auth_headers(token))
    for e in more[:4]:
        make_connection(client, architect, consumer["id"], local["id"], e["id"])
    assert [count(u) for u in urls] == few


def test_the_diagram_view_and_svg_use_the_same_number_of_statements_however_large_the_diagram(client, admin_token):
    """The resolved view and the server SVG read a diagram's placements, connections, toggles and ancestors in bulk, so
    a larger diagram (more boxes, connections, toggles and shared elements) costs no more statements."""
    from app.modules.architecture.tests._helpers import make_diagram, place_all, save_toggles, view

    org, owner, consumer, _o, token, member, _out = _world(client, admin_token, "Arch reads diagram")
    base = project_base(owner["id"])
    shared = make_element(client, token, owner["id"], "Shared platform", activate=True)
    collection = make_collection(client, token, base, "Infra", members=[shared["id"]])
    grant(client, token, base, collection["id"], project_id=consumer["id"])
    architect = make_architect(client, token, org["id"], consumer["id"], "arch.reads.diagram@example.com")
    root = make_element(client, token, consumer["id"], "Root", type_name="System")
    diagram = make_diagram(client, architect, consumer["id"], "Context", connection_detail=True)
    first = [make_element(client, token, consumer["id"], f"Part {i}", parent_id=root["id"], ports=[{"name": "Main"}]) for i in range(2)]
    make_connection(client, architect, consumer["id"], first[0]["id"], first[1]["id"])
    make_connection(client, architect, consumer["id"], first[0]["id"], shared["id"])
    diagram = place_all(client, architect, consumer["id"], diagram, root["id"], shared["id"], *[e["id"] for e in first])
    diagram = save_toggles(client, architect, consumer["id"], diagram, [{"name": "Hardware", "rule": {"domains": ["hardware"], "tags": ["x"]}}])
    toggle_id = view(client, architect, consumer["id"], diagram["id"])["toggles"][0]["id"]
    urls = [
        f"{project_base(consumer['id'])}/diagrams/{diagram['id']}/view",
        f"{project_base(consumer['id'])}/diagrams/{diagram['id']}/svg",
    ]

    def count(url) -> int:
        seen: list[str] = []

        def record(_conn, _cursor, statement, *_args):
            seen.append(statement)

        event.listen(engine, "before_cursor_execute", record)
        try:
            assert client.get(url, params={"toggle_off": toggle_id}, headers=auth_headers(architect)).status_code == 200
        finally:
            event.remove(engine, "before_cursor_execute", record)
        return len(seen)

    few = [count(u) for u in urls]
    more = [make_element(client, token, consumer["id"], f"More {i}", parent_id=root["id"], ports=[{"name": "Main"}]) for i in range(8)]
    for i, e in enumerate(more[:6]):
        make_connection(client, architect, consumer["id"], e["id"], first[i % 2]["id"])
    make_connection(client, architect, consumer["id"], more[0]["id"], shared["id"])
    everything = [root["id"], shared["id"], *[x["id"] for x in first], *[x["id"] for x in more]]
    client.put(
        f"{project_base(consumer['id'])}/diagrams/{diagram['id']}/layout",
        json={"version": diagram["version"], "placements": [{"element_id": e} for e in everything]},
        headers=auth_headers(architect),
    )
    assert [count(u) for u in urls] == few
