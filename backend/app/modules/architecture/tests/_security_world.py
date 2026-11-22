"""A two-tenant world for the Architecture module's access review: one organisation with an own project, a project the
tester cannot open and the tester's own role holders, and a second organisation with records of its own.

`build(client, admin_token, tag)` returns a `World`. Every record whose name starts with `Secret` must never appear in
a response to someone who may not read it; `World.secrets` lists those names for the leak checks.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from app.modules.architecture.tests._helpers import (
    add_member,
    add_state,
    add_transition,
    connection_types,
    element_types,
    grant,
    grant_project_role,
    make_collection,
    make_connection,
    make_diagram,
    make_element,
    make_machine,
    org_base,
    place,
    project_base,
    setup,
)
from tests.conftest import auth_headers, create_project


@dataclass
class Tenant:
    """The records one organisation holds for the review (project P1 is the tester's own, P2 is hidden from them)."""

    org: dict
    admin: str
    p1: dict
    p2: dict
    p3: dict
    ids: dict[str, str] = field(default_factory=dict)


@dataclass
class World:
    """Both organisations and the people.

    Attributes:
        a: The tester's organisation (project `p1` is theirs, `p2` is not).
        b: Another organisation.
        architect: Token of a person who holds the Architect role in `a.p1` only.
        member: Token of a plain member of `a.p1`.
        secrets: Names that must not reach anyone who may not read their records.
    """

    a: Tenant
    b: Tenant
    architect: str
    member: str
    secrets: list[str]


def _post(client, token, url, body, expect=201):
    resp = client.post(url, json=body, headers=auth_headers(token))
    assert resp.status_code == expect, f"{url}: {resp.status_code} {resp.text}"
    return resp.json()


def records(client, token, project: dict, label: str) -> dict[str, str]:
    """The records of one project a review attacks, named `Secret<label>...`: two elements with a port, a connection, a
    block diagram, a state machine diagram with states and a transition, a folder of each kind (elements, connections,
    diagrams and symbols), a collection, a baseline and a project-tier type of each vocabulary."""
    base = project_base(project["id"])
    ids: dict[str, str] = {}
    first = make_element(client, token, project["id"], f"Secret{label}Alpha", activate=True)
    second = make_element(client, token, project["id"], f"Secret{label}Beta", activate=True)
    port = _post(client, token, f"{base}/elements/{first['id']}/ports", {"name": f"Secret{label}Port"})
    connection = make_connection(client, token, project["id"], first["id"], second["id"], name=f"Secret{label}Link")
    diagram = make_diagram(client, token, project["id"], f"Secret{label}Diagram")
    diagram = place(client, token, project["id"], diagram, first["id"], x=0, y=0)
    machine = make_machine(client, token, project["id"], first["id"], f"Secret{label}Machine")
    start = add_state(client, token, project["id"], machine["id"], f"Secret{label}Start", kind="initial")
    running = add_state(client, token, project["id"], machine["id"], f"Secret{label}Running")
    transition = add_transition(client, token, project["id"], machine["id"], start["id"], running["id"], event=f"Secret{label}Go")
    folders = {
        kind: _post(client, token, f"{base}/{kind}-folders", {"name": f"Secret{label}{kind.title()}Folder"})["id"]
        for kind in ("element", "connection", "diagram", "symbol")
    }
    collection = make_collection(client, token, base, f"Secret{label}Collection", members=[first["id"]])
    element_type = _post(client, token, f"{base}/element-types", {"name": f"Secret{label}ElementType", "shape": "rectangle"})
    connection_type = _post(client, token, f"{base}/connection-types", {"name": f"Secret{label}ConnectionType"})
    domain = _post(client, token, f"{base}/domains", {"name": f"Secret{label}Domain"})
    baseline = _post(client, token, f"/api/v1/projects/{project['id']}/baselines", {"label": f"Secret{label}Baseline"})
    view = client.get(f"/api/v1/projects/{project['id']}/modules/architecture/baselines/{baseline['id']}", headers=auth_headers(token))
    assert view.status_code == 200, view.text
    item = next(r["id"] for r in view.json()["records"])
    ids.update({
        "element": first["id"], "element2": second["id"], "port": port["id"], "connection": connection["id"],
        "diagram": diagram["id"], "machine": machine["id"], "state": start["id"], "state2": running["id"],
        "transition": transition["id"], "folder_element": folders["element"], "folder_connection": folders["connection"],
        "folder_diagram": folders["diagram"], "folder_symbol": folders["symbol"], "collection": collection["id"], "element_type": element_type["id"],
        "connection_type": connection_type["id"], "domain": domain["id"], "baseline": baseline["id"], "item": item,
        "version": str(diagram["version"]),
    })
    return ids


def build(client, admin_token, tag: str) -> World:
    """Two organisations. In `a`: `p1` (the architect and the member belong to it), `p2` (secret records, no one but the
    admin may open it) and `p3` (a project a grant can name). In `b`: the same, none of it reachable from `a`."""
    suffix = uuid.uuid4().hex[:6]
    org_a, p1, token_a = setup(client, admin_token, f"{tag} A {suffix}")
    org_b, b1, token_b = setup(client, admin_token, f"{tag} B {suffix}")
    p2 = create_project(client, token_a, org_a["id"], f"{tag} hidden {suffix}")
    p3 = create_project(client, token_a, org_a["id"], f"{tag} third {suffix}")
    b2 = create_project(client, token_b, org_b["id"], f"{tag} other {suffix}")
    architect_id, architect = add_member(client, token_a, org_a["id"], p1["id"], f"architect.{suffix}@example.com")
    grant_project_role(client, token_a, p1["id"], architect_id, "architect")
    _member_id, member = add_member(client, token_a, org_a["id"], p1["id"], f"member.{suffix}@example.com")

    a = Tenant(org_a, token_a, p1, p2, p3)
    b = Tenant(org_b, token_b, b1, b2, b2)
    a.ids = records(client, token_a, p2, "A")
    b.ids = records(client, token_b, b2, "B")
    own = make_element(client, token_a, p1["id"], "Own element", activate=True)
    a.ids["own_element"] = own["id"]
    a.ids["own_element_type"] = element_types(client, token_a, p1["id"])["Component"]
    a.ids["own_connection_type"] = connection_types(client, token_a, p1["id"])["REST API"]
    # A grant on the hidden project's collection, so a grant id exists to attack.
    a.ids["grant"] = grant(client, token_a, project_base(p2["id"]), a.ids["collection"], project_id=p3["id"])["id"]
    org_types = client.get(f"{org_base(org_b['id'])}/element-types", headers=auth_headers(token_b)).json()
    b.ids["org_element"] = _post(
        client, token_b, f"{org_base(org_b['id'])}/elements", {"name": "SecretBOrgElement", "element_type_id": org_types[0]["id"]},
    )["id"]
    b.ids["symbol"] = client.get(f"{org_base(org_b['id'])}/symbols", headers=auth_headers(token_b)).json()[0]["id"]
    secrets = [
        f"Secret{label}{name}"
        for label in ("A", "B")
        for name in ("Alpha", "Beta", "Port", "Link", "Diagram", "Machine", "Start", "Running", "Go", "ElementFolder",
                     "ConnectionFolder", "DiagramFolder", "Collection", "ElementType", "ConnectionType", "Domain", "Baseline")
    ]
    return World(a, b, architect, member, secrets)
