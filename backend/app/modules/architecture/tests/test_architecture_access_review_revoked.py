"""The access review of what stays behind when a grant ends: a project drew a connection to a shared element, placed it on a
diagram, described its behaviour and took a baseline while it was shared, and then the owner revoked the grant. Every read
route of the module, the core's record routes and the exports must stop naming the element's name, description, note and
ports (its code stays, as a locked placeholder). Every test builds its own organisation.
"""

from __future__ import annotations

import uuid

from app.modules.architecture.tests._helpers import (
    add_member,
    add_state,
    grant,
    make_architect,
    make_collection,
    make_connection,
    make_diagram,
    make_element,
    make_machine,
    place,
    project_base,
    setup,
)
from app.modules.architecture.tests._security_sweep import call, fill, routes
from tests.conftest import auth_headers, create_project

_PRIVATE = ["PrivateSharedName", "PrivateSharedDescription", "PrivateSharedNote", "PrivateSharedPort"]


def _revoked_world(client, admin_token):
    """A consumer project that connected, placed, described and baselined an element, after which the grant was revoked.
    Returns `(org, owner, consumer, token, member, architect, ids)`."""
    org, owner, token = setup(client, admin_token, f"Review revoked {uuid.uuid4().hex[:6]}")
    consumer = create_project(client, token, org["id"], "Consumer")
    shared = make_element(
        client, token, owner["id"], _PRIVATE[0], description=_PRIVATE[1], display_note=_PRIVATE[2], activate=True,
        ports=[{"name": _PRIVATE[3]}],
    )
    owner_base = project_base(owner["id"])
    collection = make_collection(client, token, owner_base, "Out", members=[shared["id"]])
    given = grant(client, token, owner_base, collection["id"], project_id=consumer["id"])
    architect = make_architect(client, token, org["id"], consumer["id"], f"arch.{uuid.uuid4().hex[:6]}@example.com")
    _uid, member = add_member(client, token, org["id"], consumer["id"], f"member.{uuid.uuid4().hex[:6]}@example.com")
    mine = make_element(client, architect, consumer["id"], "Consumer box", activate=True)
    connection = make_connection(client, architect, consumer["id"], mine["id"], shared["id"], name="Consumer link")
    diagram = make_diagram(client, architect, consumer["id"], "Consumer diagram")
    diagram = place(client, architect, consumer["id"], diagram, mine["id"], x=0, y=0)
    diagram = place(client, architect, consumer["id"], diagram, shared["id"], x=300, y=0)
    machine = make_machine(client, architect, consumer["id"], shared["id"], "Consumer behaviour")
    state = add_state(client, architect, consumer["id"], machine["id"], "Idle", kind="initial")
    baseline = client.post(
        f"/api/v1/projects/{consumer['id']}/baselines", json={"label": "While shared"}, headers=auth_headers(architect),
    )
    assert baseline.status_code == 201, baseline.text
    view = client.get(f"{project_base(consumer['id'])}/baselines/{baseline.json()['id']}", headers=auth_headers(member))
    assert view.status_code == 200, view.text
    item = view.json()["records"][0]["id"]
    revoked = client.delete(f"{owner_base}/collections/{collection['id']}/grants/{given['id']}", headers=auth_headers(token))
    assert revoked.status_code == 204, revoked.text
    ids = {
        "element": mine["id"], "connection": connection["id"], "diagram": diagram["id"], "machine": machine["id"],
        "state": state["id"], "baseline": baseline.json()["id"], "item": item, "shared": shared["id"],
    }
    return org, owner, consumer, token, member, architect, ids


def test_after_a_grant_ends_no_read_route_names_the_element_that_was_shared(client, admin_token):
    _org, _owner, consumer, _token, member, architect, ids = _revoked_world(client, admin_token)
    owner_ids = {**ids, "element": ids["shared"]}
    failures: list[str] = []
    checked = 0
    for method, path, _route in routes(client.app):
        if method != "GET" or "{project_id}" not in path or "{organization_id}" in path:
            continue
        for token in (member, architect):
            for record_ids in (ids, owner_ids):
                url = fill(path, {"project_id": consumer["id"]}, record_ids)
                resp = call(client, method, url, token)
                checked += 1
                named = [p for p in _PRIVATE if p in resp.text]
                if resp.status_code >= 500 or named:
                    failures.append(f"GET {url} -> {resp.status_code} {named}")
    assert checked > 100
    assert not failures, "\n".join(failures)


def test_after_a_grant_ends_the_core_routes_exports_and_search_do_not_name_the_element(client, admin_token):
    _org, _owner, consumer, _token, _member, architect, ids = _revoked_world(client, admin_token)
    project = f"/api/v1/projects/{consumer['id']}"
    urls = []
    for artefact_type, key in (
        ("architecture_element", "element"), ("architecture_connection", "connection"), ("architecture_diagram", "diagram"),
        ("architecture_state_machine_diagram", "machine"), ("architecture_element", "shared"),
    ):
        record = f"{project}/artefacts/{artefact_type}/{ids[key]}"
        urls += [f"{record}/{suffix}" for suffix in ("link-graph", "link-candidates", "link-types", "tags", "placements", "activity")]
    for artefact_type in ("architecture_element", "architecture_connection", "architecture_diagram",
                          "architecture_state_machine_diagram", "architecture_state"):
        urls += [f"{project}/records/{artefact_type}/export?format=csv", f"{project}/records/{artefact_type}/grid"]
    urls += [f"{project}/history", f"{project}/overview"]
    for url in urls:
        resp = client.get(url, headers=auth_headers(architect))
        assert resp.status_code < 500, f"{url} -> {resp.status_code}"
        assert not [p for p in _PRIVATE if p in resp.text], f"{url} still names the element: {resp.text[:300]}"
    for text in ("PrivateShared", "Private"):
        found = client.post(
            "/api/v1/search", json={"q": text, "scope": "project", "project_id": consumer["id"],
                                    "fields": ["id", "title", "description", "ports", "display_note", "protocol"]},
            headers=auth_headers(architect),
        )
        assert found.status_code == 200, found.text
        assert not [p for p in _PRIVATE if p in found.text]
