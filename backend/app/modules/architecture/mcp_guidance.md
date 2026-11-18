Understand the structure of the product: elements, the typed connections between them, and where an interface is realised in the layer below.

Two things to do with these tools: read the structure (reports and the list and get tools) and, when the person asks, change the model (create, edit and move elements, ports, connections and state machines). Writes need `MCP_WRITES_ENABLED` and the Architect role; the server refuses what the person could not do on the screen.

Model: an **element** is a part of the product (a system, service, board) in a tree, with ports. A **connection** joins two elements and has a type (REST API, SPI, Power). A connection is **outer** for an element when exactly one of its ends is inside that element (the element itself or something below it): it crosses the element's boundary. An inner connection **realises** an outer one when it lies inside the interface the outer one declares; an outer connection is **Covered** when at least one connection realises it.

The tools are read-only project reports (the generated reference lists each tool's name and parameters):
- **Boundary coverage** (AR1): for each element that contains others (or the one named by `element`, a code such as `ELM-003` or a name), the outer connections with the connections that realise them, and the ones nothing realises.
- **Allocation coverage** (AR2): requirements with no allocated element (with the elements suggested for each), elements and connections with no requirement, and leaf elements with no owner.
- **Interface list** (AR3): every live connection with both ends, type, protocol, direction and linked requirements; `element` and `type` narrow it.
- **Element breakdown** (AR4): the element tree, a parent before its children, with a `Level` column.
- **Diagram** (AR5): the elements and lines one diagram shows (`diagram`, a code or name); the picture is for documents, not for this tool.
- **Unconnected elements** (AR6): elements with no connection (counting what is inside them), and elements no diagram shows.
- **State machines** (AR7): each element's state machine diagrams with their states and transitions; `element` narrows it, `state_machine` names the one to draw.

Read and write tools (names start `architecture_`; the generated reference lists every parameter):
- **Look up types first.** `list_element_types` and `list_connection_types` give the ids `create_element`, `update_element`, `create_connection` and `create_port` need. Connection types are a tree; a type's `default_protocol` fills a new connection's protocol when you leave `protocol` out.
- **Elements:** `list_elements` (filter by `parent_id`, `roots_only`, `element_type_id`, `search`), `get_element` (with ports), `create_element` (`ports` creates them in the same call), `update_element`, `change_element_status`, `archive_element`, `delete_element`, and `create_port`, `update_port`, `delete_port`. `list_shared_elements` lists elements other owners share (read only).
- **Connections:** `list_connections` (`element_id` for either end), `get_connection`, `create_connection` (source and target elements, optional ports), `update_connection`, `change_connection_status`, `archive_connection`, `delete_connection`, and `set_connection_realisations` (which outer connections an inner one realises; the list replaces the old one).
- **Block diagrams are read only:** `list_diagrams`, `get_diagram`, and `get_diagram_view` (the elements and lines shown). Edit the model, not the drawing.
- **State machines:** `list_state_machine_diagrams`, `get_state_machine_model` (states, transitions and validation issues in one call), `get_state_machine_mermaid`, then `create_state_machine_diagram`, `add_state`, `add_transition`, `update_state`, `update_transition`, `delete_state`, `delete_transition`, and the diagram's `change_state_machine_status`, `archive_state_machine_diagram`, `delete_state_machine_diagram`. Build in this order: the diagram, its initial state, the other states, the transitions; a diagram cannot become `active` while validation reports an error (for example no initial state).
- **Links are core tools.** Allocate a requirement to an element, constrain a connection, or link a risk or decision with `create_artefact_link` (read the types with `list_artefact_link_types`); this module has no link tools of its own.
- **Versions.** An update, a status change and every state or transition change quotes the `version` you last read (a state machine's change quotes the diagram's `version`, and the answer carries the new one). A 409 means someone else changed it first: read it again and retry.
- **Status moves are server-defined** (`draft`, `proposed`, `active`, `retired`, `rejected`); there is no approval gate. A move the server does not allow is refused with the reason.
- **Prefer archive to delete.** `archive_*` is reversible; `delete_*` is permanent and removes the record's links, tags and places. An element with children or connections cannot be deleted.
- **Shared elements** (owned by another project or the organisation) read only, through a grant. An end you may not read is a locked placeholder; do not try to infer its name.

Rules and gotchas:
- Do not read "Not covered" or an unallocated requirement as an error: some interfaces are deliberately not refined further. Report the figures; let the person decide.
- A shared element (owned by another project or the organisation) is shown as "Shared element", with no code or name.
- Codes (`ELM-001`, `CON-001`) name records in conversation; do not invent them, read them from the report.
