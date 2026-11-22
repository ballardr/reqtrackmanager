"""The access review's targeted attacks: an Architect of project 1 sends well-formed requests that name records of a project
they cannot open, or of another organisation. Every one is refused with a client error and stores nothing; the shared
routes the core owns (links, tags, comments, record lists) answer nothing about such a record.
Every test builds its own organisations.
"""

from __future__ import annotations

import uuid

import pytest

from app.modules.architecture.tests._helpers import (
    connection_types,
    element_types,
    make_collection,
    make_connection,
    make_diagram,
    make_element,
    make_machine,
    project_base,
)
from app.modules.architecture.tests._security_world import World, build
from tests.conftest import auth_headers, create_org_user

_REFUSED = {400, 403, 404, 409, 422}


@pytest.fixture
def world(client, admin_token) -> World:
    return build(client, admin_token, "Review writes")


def _send(client, world: World, method: str, url: str, body=None, *, token: str | None = None):
    kwargs = {"headers": auth_headers(token or world.architect)}
    if body is not None:
        kwargs["json"] = body
    return client.request(method, url, **kwargs)


def _refused(client, world: World, method: str, url: str, body=None, *, token: str | None = None) -> None:
    resp = _send(client, world, method, url, body, token=token)
    assert resp.status_code in _REFUSED, f"{method} {url} {body} -> {resp.status_code} {resp.text[:200]}"
    assert not [n for n in world.secrets if n in resp.text], resp.text[:300]


def _base(world: World) -> str:
    return project_base(world.a.p1["id"])


def _own(client, world: World) -> dict[str, dict]:
    """An own element, connection, diagram, state machine and collection of project 1, for the attacks to change."""
    token = world.a.admin
    p1 = world.a.p1["id"]
    first = make_element(client, token, p1, "Own first", activate=True)
    second = make_element(client, token, p1, "Own second", activate=True)
    connection = make_connection(client, token, p1, first["id"], second["id"])
    diagram = make_diagram(client, token, p1, "Own diagram")
    machine = make_machine(client, token, p1, first["id"], "Own machine")
    collection = make_collection(client, token, project_base(p1), "Own collection", members=[first["id"]])
    return {"first": first, "second": second, "connection": connection, "diagram": diagram, "machine": machine, "collection": collection}


# --- Elements and connections ----------------------------------------------------------------------------------


def test_an_element_cannot_name_a_foreign_type_symbol_folder_parent_or_owner(client, world):
    base = _base(world)
    own = _own(client, world)
    foreign = [world.a.ids, world.b.ids]
    stranger = create_org_user(client, world.b.admin, world.b.org["id"], f"stranger.{uuid.uuid4().hex[:6]}@example.com")
    component = element_types(client, world.a.admin, world.a.p1["id"])["Component"]
    for ids in foreign:
        for field_name, value in (
            ("element_type_id", ids["element_type"]), ("parent_id", ids["element"]),
            ("folder_id", ids["folder_element"]), ("symbol_id", world.b.ids["symbol"]),
        ):
            create = {"name": "Attack", "element_type_id": component, field_name: value}
            _refused(client, world, "POST", f"{base}/elements", create)
            update = {"version": own["first"]["version"], field_name: value}
            _refused(client, world, "PUT", f"{base}/elements/{own['first']['id']}", update)
    for owner in ({"type": "user", "id": stranger}, {"type": "org_group", "id": str(uuid.uuid4())}):
        _refused(client, world, "POST", f"{base}/elements", {"name": "Attack", "element_type_id": component, "owner": owner})
    for ids in foreign:
        ports = [{"name": "p", "connection_type_id": ids["connection_type"]}]
        _refused(client, world, "POST", f"{base}/elements", {"name": "Attack", "element_type_id": component, "ports": ports})
        _refused(client, world, "POST", f"{base}/elements/{own['first']['id']}/ports", ports[0])
    assert {e["name"] for e in client.get(f"{base}/elements", headers=auth_headers(world.architect)).json()} == {
        "Own element", "Own first", "Own second",
    }


def test_a_connection_cannot_join_a_foreign_element_or_use_a_foreign_type_port_or_folder(client, world):
    base = _base(world)
    own = _own(client, world)
    types = connection_types(client, world.a.admin, world.a.p1["id"])
    rest = types["REST API"]
    for ids in (world.a.ids, world.b.ids):
        for end in ("source_element_id", "target_element_id"):
            other = "target_element_id" if end == "source_element_id" else "source_element_id"
            body = {"connection_type_id": rest, end: ids["element"], other: own["second"]["id"]}
            _refused(client, world, "POST", f"{base}/connections", body)
            _refused(client, world, "PUT", f"{base}/connections/{own['connection']['id']}",
                     {"version": own["connection"]["version"], end: ids["element"]})
        _refused(client, world, "POST", f"{base}/connections", {
            "connection_type_id": ids["connection_type"], "source_element_id": own["first"]["id"], "target_element_id": own["second"]["id"],
        })
        _refused(client, world, "POST", f"{base}/connections", {
            "connection_type_id": rest, "source_element_id": own["first"]["id"], "target_element_id": own["second"]["id"],
            "source_port_id": ids["port"],
        })
        _refused(client, world, "POST", f"{base}/connections", {
            "connection_type_id": rest, "source_element_id": own["first"]["id"], "target_element_id": own["second"]["id"],
            "folder_id": ids["folder_connection"],
        })
        _refused(client, world, "PUT", f"{base}/connections/{own['connection']['id']}/realisations",
                 {"version": own["connection"]["version"], "outer_connection_ids": [ids["connection"]]})


# --- Diagrams --------------------------------------------------------------------------------------------------


def test_a_diagram_cannot_place_scope_or_point_at_a_foreign_record(client, world):
    base = _base(world)
    own = _own(client, world)
    diagram = own["diagram"]
    box = {"x": 0, "y": 0, "width": 100, "height": 50}
    for ids in (world.a.ids, world.b.ids):
        _refused(client, world, "POST", f"{base}/diagrams", {"name": "Attack", "scope_element_id": ids["element"]})
        _refused(client, world, "POST", f"{base}/diagrams", {"name": "Attack", "folder_id": ids["folder_diagram"]})
        _refused(client, world, "PUT", f"{base}/diagrams/{diagram['id']}", {"version": diagram["version"], "scope_element_id": ids["element"]})
        _refused(client, world, "POST", f"{base}/diagrams/{diagram['id']}/placements",
                 {"version": diagram["version"], "element_id": ids["element"], **box})
        _refused(client, world, "PUT", f"{base}/diagrams/{diagram['id']}/layout", {
            "version": diagram["version"], "placements": [{"element_id": ids["element"], **box}],
        })
        placed = [{"element_id": own["first"]["id"], **box}, {"element_id": own["second"]["id"], **box}]
        _refused(client, world, "PUT", f"{base}/diagrams/{diagram['id']}/layout", {
            "version": diagram["version"], "placements": placed,
            "anchors": [{
                "source_element_id": own["first"]["id"], "target_element_id": own["second"]["id"],
                "connection_id": ids["connection"], "source_point": "n",
            }],
        })
        _refused(client, world, "PUT", f"{base}/diagrams/{diagram['id']}/layout", {
            "version": diagram["version"], "placements": placed,
            "notes": [{"text": "n", "leaders": [{"kind": "connection", "connection_id": ids["connection"]}]}],
        })
        _refused(client, world, "PUT", f"{base}/diagrams/{diagram['id']}/layout", {
            "version": diagram["version"], "placements": placed, "boundaries": [{"connection_id": ids["connection"], **box}],
        })
        _refused(client, world, "PUT", f"{base}/diagrams/{diagram['id']}/toggles", {
            "version": diagram["version"],
            "toggles": [{"name": "t", "rule": {"element_type_ids": [ids["element_type"]], "domain_ids": [ids["domain"]]},
                         "element_ids": [ids["element"]], "connection_ids": [ids["connection"]]}],
        })
    # Nothing foreign was stored on the diagram.
    stored = client.get(f"{base}/diagrams/{diagram['id']}", headers=auth_headers(world.architect))
    assert stored.status_code == 200 and stored.json()["version"] == diagram["version"]


def test_a_state_machine_cannot_describe_or_link_a_foreign_record(client, world):
    base = _base(world)
    own = _own(client, world)
    machine = own["machine"]
    for ids in (world.a.ids, world.b.ids):
        _refused(client, world, "POST", f"{base}/state-machine-diagrams", {"name": "Attack", "element_id": ids["element"]})
        current = client.get(f"{base}/state-machine-diagrams/{machine['id']}", headers=auth_headers(world.architect)).json()["version"]
        _refused(client, world, "POST", f"{base}/state-machine-diagrams/{machine['id']}/states",
                 {"version": current, "name": "s", "parent_state_id": ids["state"]})
        mine = client.post(
            f"{base}/state-machine-diagrams/{machine['id']}/states", json={"version": current, "name": f"mine {ids['state'][:4]}"},
            headers=auth_headers(world.architect),
        )
        assert mine.status_code == 201, mine.text
        version = client.get(f"{base}/state-machine-diagrams/{machine['id']}", headers=auth_headers(world.architect)).json()["version"]
        _refused(client, world, "POST", f"{base}/state-machine-diagrams/{machine['id']}/transitions",
                 {"version": version, "source_state_id": mine.json()["id"], "target_state_id": ids["state"]})
        _refused(client, world, "POST", f"{base}/state-machine-diagrams/{machine['id']}/transitions",
                 {"version": version, "source_state_id": ids["state"], "target_state_id": mine.json()["id"]})
        _refused(client, world, "PUT", f"{base}/state-machine-diagrams/{machine['id']}/transitions/{ids['transition']}",
                 {"version": version, "event": "x"})
        _refused(client, world, "PUT", f"{base}/states/{ids['state']}", {"version": version, "name": "renamed"})
        _refused(client, world, "GET", f"{base}/states/{ids['state']}")
        _refused(client, world, "GET", f"{base}/states/{ids['state']}/impact")
        _refused(client, world, "DELETE", f"{base}/states/{ids['state']}?version={version}")


# --- Folders, collections, allocation --------------------------------------------------------------------------


def test_folders_and_collections_cannot_be_moved_into_or_out_of_another_owner(client, world):
    base = _base(world)
    own = _own(client, world)
    mine = client.post(f"{base}/element-folders", json={"name": "Mine"}, headers=auth_headers(world.architect)).json()
    for ids in (world.a.ids, world.b.ids):
        _refused(client, world, "POST", f"{base}/element-folders/move-records", {"record_ids": [ids["element"]], "folder_id": mine["id"]})
        _refused(client, world, "POST", f"{base}/element-folders/move-records",
                 {"record_ids": [own["first"]["id"]], "folder_id": ids["folder_element"]})
        _refused(client, world, "POST", f"{base}/connection-folders/move-records",
                 {"record_ids": [ids["connection"]], "folder_id": None})
        _refused(client, world, "POST", f"{base}/diagram-folders/move-records", {"record_ids": [ids["diagram"]], "folder_id": None})
        _refused(client, world, "POST", f"{base}/element-folders", {"name": "Child", "parent_id": ids["folder_element"]})
        _refused(client, world, "PUT", f"{base}/element-folders/{mine['id']}", {"parent_id": ids["folder_element"]})
        _refused(client, world, "PUT", f"{base}/element-folders/{ids['folder_element']}", {"name": "Taken"})
        _refused(client, world, "DELETE", f"{base}/element-folders/{ids['folder_element']}")
        _refused(client, world, "POST", f"{base}/symbol-folders", {"name": "Child", "parent_id": ids["folder_symbol"]})
        _refused(client, world, "PUT", f"{base}/symbol-folders/{ids['folder_symbol']}", {"name": "Taken"})
        _refused(client, world, "DELETE", f"{base}/symbol-folders/{ids['folder_symbol']}")
        # A collection takes only its owner's elements and is read and changed only through its owner.
        collection = own["collection"]["id"]
        _refused(client, world, "POST", f"{base}/collections/{collection}/members", {"element_ids": [ids["element"]]})
        _refused(client, world, "GET", f"{base}/collections/{ids['collection']}")
        _refused(client, world, "POST", f"{base}/collections/{ids['collection']}/grants", {"project_id": world.a.p1["id"]})
        _refused(client, world, "DELETE", f"{base}/collections/{ids['collection']}/grants/{world.a.ids['grant']}")
    # A grant can name only a project or group of the owner's organisation.
    _refused(client, world, "POST", f"{base}/collections/{own['collection']['id']}/grants", {"project_id": world.b.p1["id"]})
    _refused(client, world, "POST", f"{base}/collections/{own['collection']['id']}/grants",
             {"group": {"type": "org_group", "id": str(uuid.uuid4())}})


def test_allocation_names_no_record_of_another_project(client, world):
    base = _base(world)
    _own(client, world)
    for ids in (world.a.ids, world.b.ids):
        pair = {"requirement_id": str(uuid.uuid4()), "element_id": ids["element"]}
        for route in ("accept", "dismiss", "restore"):
            body = {"pairs": [pair]} if route == "accept" else pair
            resp = _send(client, world, "POST", f"{base}/allocation/{route}", body)
            assert resp.status_code in _REFUSED | {200, 204}, resp.text
            if resp.status_code == 200:
                assert resp.json()["accepted"] == 0
        # A record of another project reads as an empty allocation, naming nothing.
        resp = client.get(f"{base}/elements/{ids['element']}/allocation", headers=auth_headers(world.architect))
        assert resp.status_code in _REFUSED | {200}
        if resp.status_code == 200:
            assert resp.json()["allocated"] == [] and resp.json()["suggested"] == [] and resp.json()["dismissed"] == []
    listing = client.get(f"{base}/requirements/{uuid.uuid4()}/allocation", headers=auth_headers(world.architect))
    assert listing.status_code == 200 and listing.json()["allocated"] == [] and listing.json()["suggested"] == []


# --- Vocabularies and symbols ----------------------------------------------------------------------------------


def test_a_vocabulary_row_cannot_reference_a_foreign_row(client, world):
    base = _base(world)
    admin = world.a.admin
    for ids in (world.a.ids, world.b.ids):
        _refused(client, world, "POST", f"{base}/element-types",
                 {"name": "Attack1", "symbol_id": world.b.ids["symbol"]}, token=admin)
        _refused(client, world, "POST", f"{base}/element-types",
                 {"name": "Attack2", "suggested_connection_type_ids": [ids["connection_type"]]}, token=admin)
        _refused(client, world, "POST", f"{base}/element-types", {"name": "Attack3", "domain_ids": [ids["domain"]]}, token=admin)
        _refused(client, world, "POST", f"{base}/connection-types", {"name": "Attack4", "parent_ids": [ids["connection_type"]]}, token=admin)
        _refused(client, world, "POST", f"{base}/connection-types", {"name": "Attack5", "domain_ids": [ids["domain"]]}, token=admin)
        _refused(client, world, "PATCH", f"{base}/element-types/{ids['element_type']}", {"name": "Taken"}, token=admin)
        _refused(client, world, "DELETE", f"{base}/connection-types/{ids['connection_type']}", token=admin)
        _refused(client, world, "DELETE", f"{base}/domains/{ids['domain']}", token=admin)
    _refused(client, world, "GET", f"{base}/symbols/{world.b.ids['symbol']}/content")
    _refused(client, world, "GET", f"/api/v1/orgs/{world.a.org['id']}/modules/architecture/symbols/{world.b.ids['symbol']}/content")


# --- Records the core serves -----------------------------------------------------------------------------------


def test_the_core_routes_for_links_tags_comments_and_places_refuse_a_foreign_record(client, world):
    own = _own(client, world)
    project = f"/api/v1/projects/{world.a.p1['id']}"
    for ids in (world.a.ids, world.b.ids):
        for artefact_type, key in (
            ("architecture_element", "element"), ("architecture_connection", "connection"), ("architecture_diagram", "diagram"),
            ("architecture_state_machine_diagram", "machine"), ("architecture_state", "state"),
        ):
            record = f"{project}/artefacts/{artefact_type}/{ids[key]}"
            for suffix in ("tags", "placements", "comments", "anchored-comments", "link-graph", "link-candidates", "link-types", "activity"):
                _refused(client, world, "GET", f"{record}/{suffix}")
            _refused(client, world, "PUT", f"{record}/tags", {"tags": ["x"]})
            _refused(client, world, "POST", f"{record}/comments", {"body": "hello"})
            _refused(client, world, "POST", f"{record}/links", {
                "link_type_id": str(uuid.uuid4()), "other_type": "architecture_element", "other_id": own["first"]["id"],
            })
        # An own record linking out to a foreign one.
        link_types = client.get(
            f"{project}/artefacts/architecture_element/{own['first']['id']}/link-types", headers=auth_headers(world.architect),
        )
        assert link_types.status_code == 200, link_types.text
        for link_type in link_types.json():
            resp = _send(client, world, "POST", f"{project}/artefacts/architecture_element/{own['first']['id']}/links", {
                "link_type_id": link_type["link_type_id"], "direction": link_type["direction"],
                "other_type": "architecture_element", "other_id": ids["element"],
            })
            assert resp.status_code in _REFUSED, f"{link_type} -> {resp.status_code} {resp.text[:200]}"
        for artefact_type, key in (("architecture_element", "element"), ("architecture_connection", "connection"),
                                   ("architecture_diagram", "diagram")):
            _refused(client, world, "POST", f"{base_comments(world, artefact_type, ids[key])}", {"body": "hi"})


def base_comments(world: World, artefact_type: str, record_id: str) -> str:
    """The module's own comment route of a record, named through the project of the caller."""
    kind = {"architecture_element": "elements", "architecture_connection": "connections", "architecture_diagram": "diagrams"}[artefact_type]
    return f"{_base(world)}/{kind}/{record_id}/comments"


def test_no_list_export_or_search_of_project_1_carries_another_projects_records(client, world):
    base = _base(world)
    project = f"/api/v1/projects/{world.a.p1['id']}"
    _own(client, world)
    urls = [
        f"{base}/elements?include_archived=true", f"{base}/elements/shared", f"{base}/connections?include_archived=true",
        f"{base}/diagrams?include_archived=true", f"{base}/states", f"{base}/collections", f"{base}/element-folders",
        f"{base}/connection-folders", f"{base}/diagram-folders", f"{base}/element-types", f"{base}/connection-types",
        f"{base}/domains", f"{base}/allocation/coverage", f"{base}/interchange/json", f"{base}/interchange/structurizr",
        f"{base}/reports/element-breakdown", f"{base}/reports/interface-list", f"{base}/reports/state-machines",
        f"{base}/reports/unconnected-elements", f"{base}/reports/allocation-coverage", f"{base}/reports/boundary-coverage",
        f"/api/v1/orgs/{world.a.org['id']}/modules/architecture/elements",
        f"/api/v1/orgs/{world.a.org['id']}/modules/architecture/element-types",
    ]
    for artefact_type in ("architecture_element", "architecture_connection", "architecture_diagram",
                          "architecture_state_machine_diagram", "architecture_state"):
        urls += [f"{project}/records/{artefact_type}/export?format=csv", f"{project}/records/{artefact_type}/grid"]
    for url in urls:
        resp = client.get(url, headers=auth_headers(world.architect))
        assert resp.status_code in (200, 403, 404), f"{url} -> {resp.status_code} {resp.text[:200]}"
        assert not [n for n in world.secrets if n in resp.text], f"{url} carries a record of another project"
    for text in ("Secret", "SecretAAlpha", "SecretBAlpha"):
        found = client.post(
            "/api/v1/search", json={"q": text, "scope": "project", "project_id": world.a.p1["id"], "fields": ["id", "title", "description"]},
            headers=auth_headers(world.architect),
        )
        assert found.status_code == 200, found.text
        assert not [n for n in world.secrets if n in found.text]
