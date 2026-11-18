"""Tests for the System Architecture module's MCP tools: every declared tool resolves against the real routes (a wrong
path or method would silently drop it from the manifest), every declared parameter is one its route accepts, and the
tools work when called the way the MCP server calls them (path substitution, query string, JSON body), including the
role gate and the visibility rule a plain proxy must keep."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute
from pydantic import BaseModel

from app.modules.architecture.mcp_tools import build_mcp_tools
from app.modules.architecture.module import _PROJECT_ROUTER_PREFIX
from app.modules.architecture.project_router import router as project_router
from app.modules.architecture.tests._helpers import add_member, make_architect, make_element, setup
from app.modules.registry import ResolvedMcpTool, build_mcp_tool_manifest
from tests.conftest import auth_headers

PREFIX = "architecture_"


def _manifest() -> dict[str, ResolvedMcpTool]:
    return {t.name.removeprefix(PREFIX): t for t in build_mcp_tool_manifest() if t.name.startswith(PREFIX)}


def _query_names(dependant: Dependant) -> set[str]:
    """Every query parameter a route accepts, including those of its dependencies (`TagFilter`, `ProjectScope`)."""
    names = {p.alias or p.name for p in dependant.query_params}
    for sub in dependant.dependencies:
        names |= _query_names(sub)
    return names


def _route_of(tool: ResolvedMcpTool) -> APIRoute:
    path = tool.path_template.removeprefix(_PROJECT_ROUTER_PREFIX)
    for route in project_router.routes:
        if isinstance(route, APIRoute) and route.path == f"{_PROJECT_ROUTER_PREFIX}{path}" and tool.method in route.methods:
            return route
    raise AssertionError(f"{tool.name} has no route")


def _body_fields(route: APIRoute) -> dict[str, Any]:
    """The fields of the pydantic model a route reads its JSON body into."""
    assert route.body_field is not None
    model = route.body_field.field_info.annotation
    assert isinstance(model, type) and issubclass(model, BaseModel), route.path
    return dict(model.model_fields)


def _call(client, token: str, tool: str, **arguments: Any):
    """Calls a tool as `mcp-server`'s declarative proxy does: path values URL-encoded into the template, query values
    in the query string, body values as JSON. Returns the response."""
    spec = _manifest()[tool]
    path = spec.path_template
    query: dict[str, Any] = {}
    body: dict[str, Any] = {}
    for param in spec.params:
        value = arguments.get(param["name"])
        if value is None:
            assert not param["required"], f"{tool}: missing required {param['name']}"
            continue
        if param["in"] == "path":
            path = path.replace("{" + param["name"] + "}", quote(str(value), safe=""))
        elif param["in"] == "query":
            query[param["name"]] = value
        else:
            body[param["name"]] = value
    unknown = set(arguments) - {p["name"] for p in spec.params}
    assert not unknown, f"{tool} does not declare {unknown}"
    return client.request(spec.method, path, params=query or None, json=body or None, headers=auth_headers(token))


def test_every_declared_tool_resolves_against_the_real_routes():
    declared = {t.name for t in build_mcp_tools(_PROJECT_ROUTER_PREFIX)}
    assert declared == set(_manifest()) - {n for n in _manifest() if n.startswith("get_") and n.endswith("_report")}
    assert len(declared) == 44


def test_reads_are_get_and_non_mutating_and_the_rest_mutate():
    for name, tool in _manifest().items():
        reads = name.startswith(("list_", "get_"))
        assert (tool.method == "GET") == reads, name
        assert tool.mutates is not reads, name


def test_every_declared_parameter_is_one_its_route_accepts():
    for name, tool in _manifest().items():
        route = _route_of(tool)
        declared: dict[str, set[str]] = {p["in"]: set() for p in tool.params}
        for param in tool.params:
            declared[param["in"]].add(param["name"])
        assert declared.get("path", set()) == {p.name for p in route.dependant.path_params}, name
        assert declared.get("query", set()) <= _query_names(route.dependant), name
        if "body" in declared:
            fields = set(_body_fields(route))
            assert declared["body"] <= fields, f"{name}: {declared['body'] - fields}"


def test_a_required_body_field_of_a_route_is_required_by_its_tool():
    """A tool may not leave out a field its route requires, or an agent could not call it."""
    for name, tool in _manifest().items():
        route = _route_of(tool)
        if route.body_field is None or route.methods == {"GET"}:
            continue
        needed = {n for n, f in _body_fields(route).items() if f.is_required()}
        required = {p["name"] for p in tool.params if p["in"] == "body" and p["required"]}
        assert needed <= required, f"{name}: {needed - required}"


def test_an_agent_builds_a_system_end_to_end_through_the_tools(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch mcp flow")
    pid = project["id"]

    types = {t["name"]: t["id"] for t in _call(client, token, "list_element_types", project_id=pid).json()}
    connections = {t["name"]: t["id"] for t in _call(client, token, "list_connection_types", project_id=pid).json()}

    system = _call(
        client,
        token,
        "create_element",
        project_id=pid,
        name="Vehicle",
        element_type_id=types["System"],
        activate=True,
    )
    assert system.status_code == 201, system.text
    controller = _call(
        client,
        token,
        "create_element",
        project_id=pid,
        name="Controller",
        element_type_id=types["Component"],
        parent_id=system.json()["id"],
        ports=[{"name": "CAN0", "direction": "both"}],
    )
    assert controller.status_code == 201, controller.text
    sensor = _call(client, token, "create_element", project_id=pid, name="Sensor", element_type_id=types["Component"]).json()
    assert [p["name"] for p in controller.json()["ports"]] == ["CAN0"]

    listed = _call(client, token, "list_elements", project_id=pid, parent_id=system.json()["id"]).json()
    assert [e["name"] for e in listed] == ["Controller"]
    assert _call(client, token, "get_element", project_id=pid, element_id=sensor["id"]).json()["name"] == "Sensor"

    port = _call(client, token, "create_port", project_id=pid, element_id=sensor["id"], name="SPI0", direction="out")
    assert port.status_code == 201, port.text
    renamed = _call(
        client,
        token,
        "update_port",
        project_id=pid,
        element_id=sensor["id"],
        port_id=port.json()["id"],
        name="SPI1",
    )
    assert renamed.json()["name"] == "SPI1"

    connection = _call(
        client,
        token,
        "create_connection",
        project_id=pid,
        connection_type_id=next(iter(connections.values())),
        source_element_id=sensor["id"],
        target_element_id=controller.json()["id"],
        source_port_id=port.json()["id"],
        name="Readings",
    )
    assert connection.status_code == 201, connection.text
    found = _call(client, token, "list_connections", project_id=pid, element_id=sensor["id"]).json()
    assert [c["name"] for c in found] == ["Readings"]

    changed = _call(
        client,
        token,
        "update_connection",
        project_id=pid,
        connection_id=connection.json()["id"],
        version=connection.json()["version"],
        description="Sensor to controller",
    )
    assert changed.json()["description"] == "Sensor to controller"
    moved = _call(
        client,
        token,
        "change_connection_status",
        project_id=pid,
        connection_id=connection.json()["id"],
        version=changed.json()["version"],
        status="active",
    )
    assert moved.json()["status"] == "active"

    stale = _call(
        client,
        token,
        "update_element",
        project_id=pid,
        element_id=sensor["id"],
        version=sensor["version"] + 5,
        name="X",
    )
    assert stale.status_code == 409


def test_an_agent_models_behaviour_through_the_state_machine_tools(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch mcp machine")
    pid = project["id"]
    element = make_element(client, token, pid, "Pump")

    machine = _call(client, token, "create_state_machine_diagram", project_id=pid, name="Modes", element_id=element["id"])
    assert machine.status_code == 201, machine.text
    mid = machine.json()["id"]

    def version() -> int:
        return _call(client, token, "get_state_machine_diagram", project_id=pid, diagram_id=mid).json()["version"]

    start = _call(client, token, "add_state", project_id=pid, diagram_id=mid, version=version(), name="Start", kind="initial")
    running = _call(client, token, "add_state", project_id=pid, diagram_id=mid, version=version(), name="Running")
    stop = _call(client, token, "add_state", project_id=pid, diagram_id=mid, version=version(), name="Stop", kind="final")
    assert {r.status_code for r in (start, running, stop)} == {201}

    first = _call(
        client,
        token,
        "add_transition",
        project_id=pid,
        diagram_id=mid,
        version=version(),
        source_state_id=start.json()["id"],
        target_state_id=running.json()["id"],
    )
    second = _call(
        client,
        token,
        "add_transition",
        project_id=pid,
        diagram_id=mid,
        version=version(),
        source_state_id=running.json()["id"],
        target_state_id=stop.json()["id"],
        event="halt",
        guard="pressure low",
    )
    assert first.status_code == second.status_code == 201

    model = _call(client, token, "get_state_machine_model", project_id=pid, diagram_id=mid).json()
    assert [s["name"] for s in model["states"]] == ["Start", "Running", "Stop"]
    assert {t["event"] for t in model["transitions"]} == {"", "halt"}
    assert "stateDiagram-v2" in _call(client, token, "get_state_machine_mermaid", project_id=pid, diagram_id=mid).text

    assert [s["name"] for s in _call(client, token, "list_states", project_id=pid, state_machine_diagram_id=mid).json()] == [
        "Start",
        "Running",
        "Stop",
    ]
    edited = _call(
        client,
        token,
        "update_state",
        project_id=pid,
        state_id=running.json()["id"],
        version=version(),
        entry_action="spin_up()",
    )
    assert edited.json()["entry_action"] == "spin_up()"
    changed = _call(
        client,
        token,
        "update_transition",
        project_id=pid,
        diagram_id=mid,
        transition_id=second.json()["id"],
        version=version(),
        action="stop_motor()",
    )
    assert changed.json()["action"] == "stop_motor()"

    activated = _call(client, token, "change_state_machine_status", project_id=pid, diagram_id=mid, version=version(), status="active")
    assert activated.status_code == 200, activated.text

    removed = _call(
        client,
        token,
        "delete_transition",
        project_id=pid,
        diagram_id=mid,
        transition_id=first.json()["id"],
        version=version(),
    )
    assert removed.status_code == 200 and "version" in removed.json()
    gone = _call(client, token, "delete_state", project_id=pid, state_id=stop.json()["id"], version=version())
    assert gone.status_code == 200, gone.text


def test_the_tools_keep_the_architect_gate_and_the_visibility_rule(client, admin_token):
    org, project, admin = setup(client, admin_token, "Arch mcp gate")
    pid = project["id"]
    element = make_element(client, admin, pid, "Gateway")
    _uid, member = add_member(client, admin, org["id"], pid, "mcp-member@example.com")

    assert _call(client, member, "get_element", project_id=pid, element_id=element["id"]).status_code == 200
    refused = _call(client, member, "create_element", project_id=pid, name="Nope", element_type_id=element["element_type_id"])
    assert refused.status_code == 403
    assert _call(client, member, "delete_element", project_id=pid, element_id=element["id"]).status_code == 403

    _other_org, other_project, other_admin = setup(client, admin_token, "Arch mcp other")
    foreign = make_element(client, other_admin, other_project["id"], "Foreign")
    seen = _call(client, admin, "get_element", project_id=pid, element_id=foreign["id"])
    assert seen.status_code == 404
    assert _call(client, other_admin, "get_element", project_id=pid, element_id=element["id"]).status_code in (403, 404)

    architect = make_architect(client, admin, org["id"], pid, "mcp-architect@example.com")
    allowed = _call(client, architect, "create_element", project_id=pid, name="Ok", element_type_id=element["element_type_id"])
    assert allowed.status_code == 201, allowed.text


def test_a_delete_is_refused_while_the_element_is_in_use(client, admin_token):
    _org, project, token = setup(client, admin_token, "Arch mcp delete")
    pid = project["id"]
    parent = make_element(client, token, pid, "Parent")
    make_element(client, token, pid, "Child", parent_id=parent["id"])
    assert _call(client, token, "delete_element", project_id=pid, element_id=parent["id"]).status_code == 409
    archived = _call(client, token, "archive_element", project_id=pid, element_id=parent["id"])
    assert archived.status_code == 409
