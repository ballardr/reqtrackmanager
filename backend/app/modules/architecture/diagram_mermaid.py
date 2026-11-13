"""
Module: modules.architecture.diagram_mermaid

Renders a resolved diagram (`schemas.DiagramView`) as Mermaid flowchart text, for the Mermaid export endpoint, so a
diagram can be pasted into documentation that renders Mermaid.

Responsibilities:
- Write one node per visible placed element (code and name, outline from the element type's shape) and one line per
  resolved line (dotted when indirect, a head at each end only when two-way, labelled with its type and protocol or its
  count).
- Escape every user-supplied text so no name, code or label can end its string, start a directive or add markup.

Design decisions:
- **Same resolver as the screen and the SVG.** It reads the view's already resolved nodes and lines (toggles, bridging,
  roll-up and merging), so the text cannot disagree with the drawing. A node a toggle hides, and any line with a hidden
  end, are not written, so nothing hidden leaves in the text.
- **Flat.** Placed elements are not nested as subgraphs: a rolled-up line already joins the nearest placed ancestors, and
  a line to a subgraph is drawn unreliably by Mermaid.
- **Positions, notes and colours are left out**: Mermaid lays the graph out itself, and a note has no flowchart form.
- A boundary box is one node in the outline of its direction (a trapezoid each way for an input or an output, a hexagon
  for two-way, a circle where none is disclosed), labelled with the outer connection's code and the element outside.
- A locked node (an element the viewer cannot read) is written with its code only.

Dependencies: `schemas` (the view).
"""

from __future__ import annotations

import re
import uuid

from app.modules.architecture.schemas import DiagramView, ViewBoundary, ViewEdge, ViewNode

_CONTROL = re.compile(r"[\x00-\x1f\x7f￾￿]+")
#: Characters Mermaid would read as syntax inside a quoted label, written as its numeric entity (`#35;`).
_ESCAPES = {"#": "#35;", '"': "#quot;", "<": "#lt;", ">": "#gt;", "&": "#amp;", "`": "#96;"}
#: Opening and closing marks of a node's outline, by element shape; any other shape is a plain rectangle.
_SHAPES = {
    "rounded": ("(", ")"),
    "cylinder": ("[(", ")]"),
    "hexagon": ("{{", "}}"),
    "ellipse": ("([", "])"),
    "parallelogram": ("[/", "/]"),
    "folder": ("[[", "]]"),
}


def _text(value: str) -> str:
    """User text made safe to put in a quoted Mermaid label: control characters become a space and syntax characters
    become entities."""
    return "".join(_ESCAPES.get(ch, ch) for ch in _CONTROL.sub(" ", value).strip())


def _node(key: str, node: ViewNode) -> str:
    """One node line."""
    label = _text(node.unique_code) if node.locked else f"{_text(node.unique_code)}<br/>{_text(node.name)}"
    opening, closing = _SHAPES.get(node.shape, ("[", "]"))
    return f'    {key}{opening}"{label}"{closing}'


#: Opening and closing marks of a boundary box's outline, by shape.
_BOUNDARY_SHAPES = {"input": ("[/", "\\]"), "output": ("[\\", "/]"), "bidirectional": ("{{", "}}"), "dot": ("((", "))")}


def _boundary(key: str, box: ViewBoundary) -> str:
    """One boundary box node line."""
    name = box.outside_element_code if box.locked else f"{box.outside_element_code} {box.outside_element_name}"
    opening, closing = _BOUNDARY_SHAPES.get(box.shape, ("((", "))"))
    return f'    {key}{opening}"{_text(box.connection_code)}<br/>{_text(name)}"{closing}'


def _edge(source: str, target: str, edge: ViewEdge) -> str:
    """One line: an arrow head at each end for a two-way line, dotted for an indirect one, labelled when it has a
    label or stands for several connections."""
    text = edge.label or (f"×{edge.count}" if edge.count > 1 else "")
    arrow = ("<-.->" if edge.indirect else "<-->") if edge.two_way else ("-.->" if edge.indirect else "-->")
    return f'    {source} {arrow}|"{_text(text)}"| {target}' if text else f"    {source} {arrow} {target}"


def render_mermaid(view: DiagramView) -> str:
    """The diagram as Mermaid flowchart text.

    Args:
        view: The resolved diagram (`diagram_view.build_view`).

    Returns:
        The Mermaid text, ending in a newline.
    """
    visible = [n for n in view.nodes if not n.hidden]
    keys: dict[uuid.UUID, str] = {n.element_id: f"n{i}" for i, n in enumerate(visible, start=1)}
    lines = [f"%% {_CONTROL.sub(' ', f'{view.diagram.unique_code} {view.diagram.name}').strip()}", "flowchart LR"]
    keys.update({b.id: f"b{i}" for i, b in enumerate(view.boundaries, start=1)})
    lines += [_node(keys[n.element_id], n) for n in visible]
    lines += [_boundary(keys[b.id], b) for b in view.boundaries]
    if not visible and not view.boundaries:
        lines.append('    empty["Empty diagram"]')
    lines += [
        _edge(keys[e.source_element_id], keys[e.target_element_id], e)
        for e in view.edges if e.source_element_id in keys and e.target_element_id in keys
    ]
    return "\n".join(lines) + "\n"
