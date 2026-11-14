Understand the structure of the product: elements, the typed connections between them, and where an interface is realised in the layer below.

Model: an **element** is a part of the product (a system, service, board) in a tree, with ports. A **connection** joins two elements and has a type (REST API, SPI, Power). A connection is **outer** for an element when exactly one of its ends is inside that element (the element itself or something below it): it crosses the element's boundary. An inner connection **realises** an outer one when it lies inside the interface the outer one declares; an outer connection is **Covered** when at least one connection realises it.

The tools are read-only project reports (the generated reference lists each tool's name and parameters):
- **Boundary coverage** (AR1): for each element that contains others (or the one named by `element`, a code such as `ELM-003` or a name), the outer connections with the connections that realise them, and the ones nothing realises.
- **Allocation coverage** (AR2): requirements with no allocated element (with the elements suggested for each), elements and connections with no requirement, and leaf elements with no owner.
- **Interface list** (AR3): every live connection with both ends, type, protocol, direction and linked requirements; `element` and `type` narrow it.
- **Element breakdown** (AR4): the element tree, a parent before its children, with a `Level` column.
- **Diagram** (AR5): the elements and lines one diagram shows (`diagram`, a code or name); the picture is for documents, not for this tool.
- **Unconnected elements** (AR6): elements with no connection (counting what is inside them), and elements no diagram shows.
- **State machines** (AR7): each element's state machine diagrams with their states and transitions; `element` narrows it, `state_machine` names the one to draw.

Rules and gotchas:
- Do not read "Not covered" or an unallocated requirement as an error: some interfaces are deliberately not refined further. Report the figures; let the person decide.
- A shared element (owned by another project or the organisation) is shown as "Shared element", with no code or name.
- Codes (`ELM-001`, `CON-001`) name records in conversation; do not invent them, read them from the report.
