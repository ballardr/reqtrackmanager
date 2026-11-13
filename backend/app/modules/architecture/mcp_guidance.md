Understand the structure of the product: elements, the typed connections between them, and where an interface is realised in the layer below.

Model: an **element** is a part of the product (a system, service, board) in a tree, with ports. A **connection** joins two elements and has a type (REST API, SPI, Power). A connection is **outer** for an element when exactly one of its ends is inside that element (the element itself or something below it): it crosses the element's boundary. An inner connection **realises** an outer one when it lies inside the interface the outer one declares; an outer connection is **Covered** when at least one connection realises it.

The only tool today is the boundary coverage report (`architecture_get_boundary_coverage_report`, project-level, read-only). It lists, for each element that contains others (or the one named by `element`, a code such as `ELM-003` or a name), the outer connections with the connections that realise them, and a second table of the ones nothing realises.

Rules and gotchas:
- Do not read "Not covered" as an error: some interfaces are deliberately not refined further. Report the figures; let the person decide.
- A shared element (owned by another project or the organisation) is shown as "Shared element", with no code or name.
- Codes (`ELM-001`, `CON-001`) name records in conversation; do not invent them, read them from the report.
