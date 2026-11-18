"""
Module: modules.architecture.mcp_tools

Declares the System Architecture module's MCP tools: read, create, change, retire and delete for elements, ports,
connections, block diagrams (read only) and state machine diagrams with their states and transitions.

Responsibilities:
- One `McpToolDefinition` per project-router endpoint an agent needs. The module key prefixes each name
  (`architecture_create_element`); `build_mcp_tool_manifest` checks every path and method against the real routes.
- The report tools (`report_mcp_tools`) are added in `module.py`; they are not repeated here.

Design decisions:
- **A tool is a plain proxy to the same endpoint the screen calls.** The route applies the Architect role, the module
  and sub-component gates, the visibility resolver (a shared element is read through collection grants only, a foreign
  end is a locked placeholder) and the audit event. No tool reaches a record by a path the route does not.
- **Links use the core link tools.** Allocation, constraint, risk and decision links are ordinary artefact links
  (`create_artefact_link`), so this module declares none of its own. Realisation between connections has its own
  endpoint and tool.
- **Block diagrams are read only.** A block diagram is a drawing (placements, routes, notes); an agent reads the
  elements and lines it shows (`architecture_get_diagram_view`) and edits the model, not the layout. A state machine
  diagram is structure (states, transitions), so it is edited.
- **No tool changes access.** Collections, grants and symbol upload are left to people (a grant widens who can read an
  element; an upload is a file).
- **Deletion is declared, never the default.** Each deletion tool says in its description that archiving is the
  reversible alternative; the route refuses an element with children or connections.

Dependencies: `app.modules.registry` (`McpToolDefinition`). No route, model or service imports, so the module imports
with nothing else loaded.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Literal

from app.modules.registry import McpToolDefinition

_STATUSES = "One of draft, proposed, active, retired, rejected; the server refuses a move it does not allow."


def _param(name: str, kind: str, description: str, *, where: str, required: bool = False) -> dict:
    """One tool parameter in the manifest's shape."""
    return {"name": name, "type": kind, "required": required, "in": where, "description": description}


def _path(name: str, description: str) -> dict:
    """A required path parameter."""
    return _param(name, "uuid", description, where="path", required=True)


def _body(name: str, kind: str, description: str, *, required: bool = False) -> dict:
    """A body field; a field left out of an update is kept."""
    return _param(name, kind, description, where="body", required=required)


def _query(name: str, kind: str, description: str) -> dict:
    """An optional query filter."""
    return _param(name, kind, description, where="query")


_PROJECT = _path("project_id", "The project.")
_ELEMENT = _path("element_id", "The element.")
_CONNECTION = _path("connection_id", "The connection.")
_DIAGRAM = _path("diagram_id", "The diagram.")
_MACHINE = _path("diagram_id", "The state machine diagram.")
_STATE = _path("state_id", "The state.")
_PORT = _path("port_id", "The port.")
_TRANSITION = _path("transition_id", "The transition.")
_VERSION = _body("version", "integer", "The record's `version` as last read (409 when another change came first).", required=True)
_MACHINE_VERSION = _body(
    "version",
    "integer",
    "The state machine diagram's `version` as last read; every change to its states and " "transitions raises it (409 when stale).",
    required=True,
)
_INCLUDE_ARCHIVED = _query("include_archived", "boolean", "Also list archived records.")
_OPEN_ONLY = _query("open_only", "boolean", "Leave out retired records.")
_SEARCH = _query("search", "string", "Text matched against the code, name and description.")
_STATUS_FILTER = _query("status", "string", "Only records with this status.")


def _tool(
    name: str,
    description: str,
    method: Literal["GET", "POST", "PUT", "DELETE"],
    path: str,
    params: list[dict],
) -> McpToolDefinition:
    """A tool whose path is relative to the project router; `build_mcp_tools` puts the router's prefix in front."""
    return McpToolDefinition(name=name, description=description, method=method, path_template=path, params=[_PROJECT, *params])


def _required(fields: list[dict], names: set[str]) -> list[dict]:
    """`fields` with the ones named in `names` marked required (a create form's needs, over an update's all-optional set)."""
    return [{**p, "required": p["name"] in names} for p in fields]


_PORT_FIELDS = [
    _body("name", "string", "The port's name, unique on its element."),
    _body("direction", "string", "in, out or both, seen from the element."),
    _body("connection_type_id", "uuid", "The connection type the port carries (from `architecture_list_connection_types`)."),
]

_ELEMENT_FIELDS = [
    _body("description", "string", "What the element is and does."),
    _body("display_note", "string", "A short note drawn inside the element's box (up to 500 characters)."),
    _body("element_type_id", "uuid", "The element type (from `architecture_list_element_types`)."),
    _body("parent_id", "uuid", "The element this one sits inside; null on an update makes it a top-level element."),
    _body("owner", "object", 'Who owns it: {"type": "user" | "org_group" | "project_group", "id": uuid}.'),
    _body("folder_id", "uuid", "The folder the element is listed in."),
]

_CONNECTION_FIELDS = [
    _body("name", "string", "A short name; may be empty."),
    _body("connection_type_id", "uuid", "The connection type (from `architecture_list_connection_types`)."),
    _body("source_element_id", "uuid", "The element the connection starts at."),
    _body("source_port_id", "uuid", "A port on the source element."),
    _body("target_element_id", "uuid", "The element the connection ends at."),
    _body("target_port_id", "uuid", "A port on the target element."),
    _body("protocol", "string", "The protocol or detail; left out takes the connection type's default, an empty string means none."),
    _body("description", "string", "What the connection carries and why."),
    _body("folder_id", "uuid", "The folder the connection is listed in."),
]

_STATE_FIELDS = [
    _body("description", "string", "What the state means."),
    _body("kind", "string", "state, initial, final or choice (initial is the single start marker of a level)."),
    _body("parent_state_id", "uuid", "The composite state this one is inside; null on an update makes it top level."),
    _body("entry_action", "string", "What happens on entering the state."),
    _body("exit_action", "string", "What happens on leaving the state."),
    _body("activity", "string", "What continues while in the state."),
    _body("label", "string", "Text drawn beside the symbol of an initial, final or choice marker."),
]

_TRANSITION_FIELDS = [
    _body("event", "string", "The trigger."),
    _body("guard", "string", "The condition that must hold."),
    _body("action", "string", "What happens on the transition."),
    _body("description", "string", "Notes on the transition."),
]


def _reads() -> list[McpToolDefinition]:
    """The read tools."""
    return [
        _tool(
            "list_element_types",
            "Lists the element types the project can use (the organisation's defaults it has not hidden, then its own).",
            "GET",
            "/element-types",
            [],
        ),
        _tool(
            "list_connection_types",
            "Lists the connection types, a tree: a type names its `parent_ids` and `default_protocol`.",
            "GET",
            "/connection-types",
            [],
        ),
        _tool(
            "list_elements",
            "Lists the project's elements (code, name, type, parent, status, ports, connection count). `parent_id` lists one "
            "element's children, `roots_only` the top level.",
            "GET",
            "/elements",
            [
                _INCLUDE_ARCHIVED,
                _OPEN_ONLY,
                _SEARCH,
                _STATUS_FILTER,
                _query("element_type_id", "uuid", "Only elements of this type."),
                _query("parent_id", "uuid", "Only the children of this element."),
                _query("roots_only", "boolean", "Only top-level elements."),
            ],
        ),
        _tool(
            "list_shared_elements",
            "Lists the elements other owners share with this project (read only here).",
            "GET",
            "/elements/shared",
            [_INCLUDE_ARCHIVED, _OPEN_ONLY, _SEARCH],
        ),
        _tool(
            "get_element",
            "Fetches one element with its ports: the project's own, or one shared with it.",
            "GET",
            "/elements/{element_id}",
            [_ELEMENT],
        ),
        _tool(
            "list_connections",
            "Lists the project's connections with both ends, type, protocol and status. `element_id` lists those at either end of an element.",
            "GET",
            "/connections",
            [
                _INCLUDE_ARCHIVED,
                _OPEN_ONLY,
                _SEARCH,
                _STATUS_FILTER,
                _query("connection_type_id", "uuid", "Only connections of this type or one below it in the tree."),
                _query("element_id", "uuid", "Only connections with this element at either end."),
            ],
        ),
        _tool("get_connection", "Fetches one connection.", "GET", "/connections/{connection_id}", [_CONNECTION]),
        _tool(
            "list_diagrams",
            "Lists the project's block diagrams (code, name, scope element, status).",
            "GET",
            "/diagrams",
            [_INCLUDE_ARCHIVED, _OPEN_ONLY, _SEARCH, _STATUS_FILTER],
        ),
        _tool("get_diagram", "Fetches one block diagram's record.", "GET", "/diagrams/{diagram_id}", [_DIAGRAM]),
        _tool(
            "get_diagram_view",
            "The elements and lines one block diagram shows, resolved for the diagram's scope and view switches (no layout or drawing).",
            "GET",
            "/diagrams/{diagram_id}/view",
            [_DIAGRAM],
        ),
        _tool(
            "list_state_machine_diagrams",
            "Lists the project's state machine diagrams (code, name, the element described, status, counts and validation counts).",
            "GET",
            "/state-machine-diagrams",
            [
                _INCLUDE_ARCHIVED,
                _OPEN_ONLY,
                _SEARCH,
                _STATUS_FILTER,
                _query("element_id", "uuid", "Only the diagrams that describe this element."),
            ],
        ),
        _tool("get_state_machine_diagram", "Fetches one state machine diagram's record.", "GET", "/state-machine-diagrams/{diagram_id}", [_MACHINE]),
        _tool(
            "get_state_machine_model",
            "A state machine diagram with all its states and transitions and its validation issues (the whole behaviour in one call).",
            "GET",
            "/state-machine-diagrams/{diagram_id}/model",
            [_MACHINE],
        ),
        _tool(
            "get_state_machine_mermaid",
            "A state machine diagram as Mermaid `stateDiagram-v2` text.",
            "GET",
            "/state-machine-diagrams/{diagram_id}/mermaid",
            [_MACHINE],
        ),
        _tool(
            "list_states",
            "Lists the states of the project's state machine diagrams.",
            "GET",
            "/states",
            [
                _INCLUDE_ARCHIVED,
                _SEARCH,
                _query("state_machine_diagram_id", "uuid", "Only the states of this diagram."),
                _query("kind", "string", "state, initial, final or choice."),
            ],
        ),
        _tool("get_state", "Fetches one state.", "GET", "/states/{state_id}", [_STATE]),
    ]


def _element_writes() -> list[McpToolDefinition]:
    """Create, change, retire and delete for elements and their ports."""
    return [
        _tool(
            "create_element",
            "Creates an element (a draft, or active with `activate`). `ports` creates its ports in the same call. Needs the Architect role.",
            "POST",
            "/elements",
            [
                _body("name", "string", "The element's name.", required=True),
                *_required(_ELEMENT_FIELDS, {"element_type_id"}),
                _body("activate", "boolean", "Create it active instead of draft."),
                _body("ports", "array", "Ports to create: a list of {name, direction, connection_type_id}."),
            ],
        ),
        _tool(
            "update_element",
            "Edits an element; a field left out is kept. Needs the Architect role.",
            "PUT",
            "/elements/{element_id}",
            [_ELEMENT, _VERSION, _body("name", "string", "The new name."), *_ELEMENT_FIELDS],
        ),
        _tool(
            "change_element_status",
            "Moves an element to another status. Retiring needs every child retired or archived. " + _STATUSES,
            "POST",
            "/elements/{element_id}/status",
            [_ELEMENT, _VERSION, _body("status", "string", _STATUSES, required=True)],
        ),
        _tool(
            "archive_element",
            "Archives an element (every child must be retired or archived); it can be restored.",
            "POST",
            "/elements/{element_id}/archive",
            [_ELEMENT],
        ),
        _tool("unarchive_element", "Restores an archived element.", "POST", "/elements/{element_id}/unarchive", [_ELEMENT]),
        _tool(
            "delete_element",
            "Permanently deletes an element with no children and no connection (409 otherwise), with its links, tags and places. "
            "Archive it instead when it may be needed again.",
            "DELETE",
            "/elements/{element_id}",
            [_ELEMENT],
        ),
        _tool(
            "create_port",
            "Adds a port to an element. Needs the Architect role.",
            "POST",
            "/elements/{element_id}/ports",
            [_ELEMENT, *_required(_PORT_FIELDS, {"name"})],
        ),
        _tool(
            "update_port",
            "Edits a port; `connection_type_id` null clears its type.",
            "PUT",
            "/elements/{element_id}/ports/{port_id}",
            [_ELEMENT, _PORT, *_PORT_FIELDS],
        ),
        _tool("delete_port", "Deletes a port.", "DELETE", "/elements/{element_id}/ports/{port_id}", [_ELEMENT, _PORT]),
    ]


def _connection_writes() -> list[McpToolDefinition]:
    """Create, change, retire and delete for connections."""
    return [
        _tool(
            "create_connection",
            "Creates a connection between two elements (a draft, or active with `activate`); a port on each end is optional. "
            "Needs the Architect role.",
            "POST",
            "/connections",
            [
                *_required(_CONNECTION_FIELDS, {"connection_type_id", "source_element_id", "target_element_id"}),
                _body("activate", "boolean", "Create it active instead of draft."),
            ],
        ),
        _tool(
            "update_connection",
            "Edits a connection; a field left out is kept, a port set to null is cleared.",
            "PUT",
            "/connections/{connection_id}",
            [_CONNECTION, _VERSION, *_CONNECTION_FIELDS],
        ),
        _tool(
            "set_connection_realisations",
            "Sets which outer connections an inner connection realises (the given list replaces the old one; an empty list clears it).",
            "PUT",
            "/connections/{connection_id}/realisations",
            [_CONNECTION, _VERSION, _body("outer_connection_ids", "array", "The ids of the outer connections it realises.", required=True)],
        ),
        _tool(
            "change_connection_status",
            "Moves a connection to another status. " + _STATUSES,
            "POST",
            "/connections/{connection_id}/status",
            [_CONNECTION, _VERSION, _body("status", "string", _STATUSES, required=True)],
        ),
        _tool("archive_connection", "Archives a connection; it can be restored.", "POST", "/connections/{connection_id}/archive", [_CONNECTION]),
        _tool("unarchive_connection", "Restores an archived connection.", "POST", "/connections/{connection_id}/unarchive", [_CONNECTION]),
        _tool(
            "delete_connection",
            "Permanently deletes a connection with its links. Archive it instead when it may be needed again.",
            "DELETE",
            "/connections/{connection_id}",
            [_CONNECTION],
        ),
    ]


def _state_machine_writes() -> list[McpToolDefinition]:
    """Create, change, retire and delete for state machine diagrams, their states and transitions."""
    transition_ends = [
        _body("source_state_id", "uuid", "The state the transition leaves."),
        _body("target_state_id", "uuid", "The state it enters."),
    ]
    return [
        _tool(
            "create_state_machine_diagram",
            "Creates a state machine diagram for an element (a draft). `activate` is refused while the validation finds an error, "
            "and a new diagram has no initial state. Needs the Architect role.",
            "POST",
            "/state-machine-diagrams",
            [
                _body("name", "string", "The diagram's name.", required=True),
                _body("element_id", "uuid", "The element whose behaviour it describes.", required=True),
                _body("description", "string", "What the diagram covers."),
                _body("activate", "boolean", "Create it active instead of draft."),
            ],
        ),
        _tool(
            "update_state_machine_diagram",
            "Edits a state machine diagram's own fields; a field left out is kept.",
            "PUT",
            "/state-machine-diagrams/{diagram_id}",
            [
                _MACHINE,
                _VERSION,
                _body("name", "string", "The new name."),
                _body("description", "string", "The new description."),
                _body("element_id", "uuid", "The element it describes."),
            ],
        ),
        _tool(
            "change_state_machine_status",
            "Moves a state machine diagram to another status; `active` is refused (409) while the validation finds an error. " + _STATUSES,
            "POST",
            "/state-machine-diagrams/{diagram_id}/status",
            [_MACHINE, _VERSION, _body("status", "string", _STATUSES, required=True)],
        ),
        _tool(
            "archive_state_machine_diagram",
            "Archives a state machine diagram; it can be restored.",
            "POST",
            "/state-machine-diagrams/{diagram_id}/archive",
            [_MACHINE],
        ),
        _tool(
            "unarchive_state_machine_diagram",
            "Restores an archived state machine diagram.",
            "POST",
            "/state-machine-diagrams/{diagram_id}/unarchive",
            [_MACHINE],
        ),
        _tool(
            "delete_state_machine_diagram",
            "Permanently deletes a state machine diagram with its states and transitions (the element is untouched). "
            "Archive it instead when it may be needed again.",
            "DELETE",
            "/state-machine-diagrams/{diagram_id}",
            [_MACHINE],
        ),
        _tool(
            "add_state",
            "Adds a state, or an initial, final or choice marker, to a diagram and answers the state. Needs the Architect role.",
            "POST",
            "/state-machine-diagrams/{diagram_id}/states",
            [_MACHINE, _MACHINE_VERSION, _body("name", "string", "The state's name.", required=True), *_STATE_FIELDS],
        ),
        _tool(
            "update_state",
            "Edits a state; a field left out is kept, `parent_state_id` null moves it to the top level.",
            "PUT",
            "/states/{state_id}",
            [_STATE, _MACHINE_VERSION, _body("name", "string", "The new name."), *_STATE_FIELDS],
        ),
        _tool(
            "delete_state",
            "Deletes a state with its transitions and links (409 while it contains other states); answers what went with it "
            "and the diagram's new `version`.",
            "DELETE",
            "/states/{state_id}",
            [_STATE, _param("version", "integer", "The diagram's `version` as last read.", where="query", required=True)],
        ),
        _tool(
            "add_transition",
            "Adds a transition between two states of a diagram; the answer carries the diagram's new `version`.",
            "POST",
            "/state-machine-diagrams/{diagram_id}/transitions",
            [
                _MACHINE,
                _MACHINE_VERSION,
                *_required(transition_ends, {"source_state_id", "target_state_id"}),
                *_TRANSITION_FIELDS,
            ],
        ),
        _tool(
            "update_transition",
            "Edits a transition; a field left out is kept.",
            "PUT",
            "/state-machine-diagrams/{diagram_id}/transitions/{transition_id}",
            [_MACHINE, _TRANSITION, _MACHINE_VERSION, *transition_ends, *_TRANSITION_FIELDS],
        ),
        _tool(
            "delete_transition",
            "Deletes a transition; answers the diagram's new `version`.",
            "DELETE",
            "/state-machine-diagrams/{diagram_id}/transitions/{transition_id}",
            [_MACHINE, _TRANSITION, _param("version", "integer", "The diagram's `version` as last read.", where="query", required=True)],
        ),
    ]


def build_mcp_tools(project_router_prefix: str) -> tuple[McpToolDefinition, ...]:
    """Every tool this module declares apart from its report tools.

    Args:
        project_router_prefix: The project router's mount prefix, e.g. `/api/v1/projects/{project_id}/modules/<key>`.

    Returns:
        The read tools first, then the element, connection and state machine tools, in declaration order.
    """
    relative = [*_reads(), *_element_writes(), *_connection_writes(), *_state_machine_writes()]
    return tuple(replace(t, path_template=f"{project_router_prefix}{t.path_template}") for t in relative)
