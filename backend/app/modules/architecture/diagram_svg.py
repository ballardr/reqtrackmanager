"""
Module: modules.architecture.diagram_svg

Renders a resolved diagram (`schemas.DiagramView`) as one SVG document, for the server's SVG endpoint and the
report part, so a document shows what the screen shows.

Responsibilities:
- Draw each visible node as its symbol or its type's shape, with its code, name and ports (small tabs), at the
  size its content needs when the stored size is smaller (`diagram_box_fit`), so a line attaches to the frame
  that is drawn.
- Draw each line between two attach points of its boxes (a person's choice, else the nearest pair;
  `diagram_points`), dashed when indirect, with an arrowhead when one-way, a count when several connections
  collapse into it and, with connection detail on, its type and protocol.
- Draw each boundary box (the outer connection a scoped diagram stands for) in the shape of its direction, with
  the connection's code, the element outside and a covered or not covered marker.
- Draw annotation notes (sized by content when Automatic, `diagram_note_layout`, else at the stored size) as
  plain text in a block of their tone (none for the tone None, which draws the text alone; nothing for an empty
  note), with each leader from the note's attach point through its vertices (straight or smooth) to the box,
  the line's midpoint or a free point, with an arrowhead or dot at either end; a leader whose target is not
  drawn is not drawn.
- With the diagram's `line_hops` on, draw a small arc where one line crosses another (`diagram_line_hops`;
  connections and leaders are one set).

Design decisions:
- Everything user-supplied is text: names, codes, notes and labels are XML-escaped and stripped of control
  characters. A symbol is the one place markup is embedded, and only the sanitised SVG of `symbols.symbol_svg`
  is used (an unreadable symbol falls back to the type's shape).
- Light-theme colours: the document is for reports and files, so it uses the type's light colour (or a neutral
  default) on a transparent background; the browser themes its own canvas.
- Boundary shapes are drawn from a flag outline: the tip on the right for an input (flow runs into the scope),
  on the left for an output, at both ends for two-way, and a circle where no direction is disclosed. The
  coverage marker is a filled or empty dot, with no warning colour.
- Deterministic: elements are drawn in the order of the view, so equal views give equal bytes.
- A node a toggle hides and a line with a hidden end are not drawn; a locked node is a dashed box with its code.

Dependencies: `schemas` (the view), `symbols` (safe markup), `models` (symbol rows), `diagram_points`,
`diagram_note_layout`, `diagram_box_fit`, `diagram_line_path`, `diagram_line_hops`.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from xml.sax.saxutils import escape

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.architecture.diagram_box_fit import (
    CAPTION_LINE_HEIGHT,
    INSET_Y,
    NAME_LINE_HEIGHT,
    SYMBOL_GAP,
    SYMBOL_HEIGHT,
    drawn_box_size,
    fit_box,
)
from app.modules.architecture.diagram_line_anchors import AnchorBox, AnchorLine, assign_line_anchors
from app.modules.architecture.diagram_line_hops import HopLine, line_hops
from app.modules.architecture.diagram_line_path import NO_DIRECTIONS, Directions, Point, effective_shape, line_middle, line_path
from app.modules.architecture.diagram_note_layout import (
    NOTE_FONT_SIZE,
    NOTE_LINE_HEIGHT,
    NOTE_PADDING,
    TITLE_PERCENT,
    drawn_size,
    note_lines,
)
from app.modules.architecture.diagram_points import line_directions, line_points, nearest_point, outward_direction, point_xy
from app.modules.architecture.diagram_symbol_label import text_width
from app.modules.architecture.enums import AttachPoint, LeaderKind, LineEnd, LineShape, NoteTone
from app.modules.architecture.labels import INACTIVE_STATUSES
from app.modules.architecture.models import ArchitectureSymbol
from app.modules.architecture.schemas import AnchorOut, DiagramView, LeaderOut, NoteOut, ViewBoundary, ViewEdge, ViewNode
from app.modules.architecture.symbols import symbol_svg

_DEFAULT_COLOR = "#475569"
_TEXT_COLOR = "#1E293B"
_MARGIN = 32.0
_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
# Characters XML 1.0 cannot carry (control characters other than tab, line feed and carriage return, and U+FFFE, U+FFFF),
# listed as code points so the removal is a table lookup rather than a character range.
_XML_FORBIDDEN = dict.fromkeys([*range(0x00, 0x09), 0x0B, 0x0C, *range(0x0E, 0x20), 0xFFFE, 0xFFFF])
_ROOT = re.compile(r"<svg\b[^>]*>", re.IGNORECASE)
_VIEWBOX = re.compile(r'viewBox\s*=\s*"([^"]*)"', re.IGNORECASE)
_SIZE = re.compile(r'\b(width|height)\s*=\s*"\s*([0-9.]+)\s*(?:px)?\s*"', re.IGNORECASE)
_BOX_ATTR = re.compile(r'\s(?:x|y|width|height)\s*=\s*"[^"]*"', re.IGNORECASE)


def _text(value: str) -> str:
    """User text made safe to put in an XML text node or attribute."""
    return escape(value.translate(_XML_FORBIDDEN), {'"': "&quot;"})


def _color(value: str | None) -> str:
    """A `#RRGGBB` colour, or the default."""
    return value if value and _COLOR.match(value) else _DEFAULT_COLOR


def _wrap(value: str, width: int, lines: int) -> list[str]:
    """Greedy word wrap of `value` to at most `lines` lines of about `width` characters (the last ends with an ellipsis
    when text was cut)."""
    words, out, current = value.split(), [], ""
    for word in words:
        word = word if len(word) <= width else word[: width - 1] + "…"
        if current and len(current) + 1 + len(word) > width:
            out.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        out.append(current)
    if len(out) > lines:
        out = out[:lines]
        out[-1] = out[-1][: max(width - 1, 1)].rstrip() + "…"
    return out


def _note_lines(note: str, width: int, lines: int) -> list[str]:
    """A display note as at most `lines` lines of about `width` characters: each paragraph is word-wrapped, and when the
    note does not fit the last line ends with an ellipsis."""
    out: list[str] = []
    for paragraph in note.splitlines():
        out.extend(_wrap(paragraph, width, 1000))
    if len(out) > lines:
        out = out[: max(lines, 0)]
        if out:
            out[-1] = out[-1][: max(width - 1, 1)].rstrip() + "…"
    return out


def _fit_with_ellipsis(line: str, bold: bool, inner_width: int) -> str:
    """`line` cut at the end, as far as needed, so that it and an ellipsis fit `inner_width` (the note's own measure)."""
    percent = TITLE_PERCENT if bold else 100
    cut = line.rstrip()
    while cut and text_width(cut + "…", NOTE_FONT_SIZE, percent) > inner_width * 1000:
        cut = cut[:-1].rstrip()
    return cut + "…"


def _note_block(note: NoteOut) -> list[tuple[str, bool]]:
    """The lines a note draws, top to bottom, as `(text, bold)`: its title in bold, then its text, each wrapped to the note's
    width (`diagram_note_layout`, the lines the editor draws) with typed line breaks kept. When they do not fit the block's
    height the last line ends with an ellipsis."""
    inner = max(int(note.width) - 2 * NOTE_PADDING, 1)
    laid = note_lines(note.title, note.text, inner)
    lines = [(line, True) for line in laid.title] + [(line, False) for line in laid.text]
    room = max(int((note.height - 2 * NOTE_PADDING) // NOTE_LINE_HEIGHT), 1)
    if len(lines) > room:
        lines = lines[:room]
        last, bold = lines[-1]
        lines[-1] = (_fit_with_ellipsis(last, bold, inner), bold)
    return lines


#: The SVG `text-anchor` of a note's lines by alignment.
_NOTE_ANCHOR: dict[str, str] = {"left": "start", "center": "middle", "right": "end"}


def _note_text(note: NoteOut) -> str:
    """The `<text>` of each line of a note, aligned as the note says (left and right keep `NOTE_PADDING` from the block's edge)."""
    align = note.text_align.value
    x = {
        "left": note.x + NOTE_PADDING, "center": note.x + note.width / 2, "right": note.x + note.width - NOTE_PADDING,
    }[align]
    parts: list[str] = []
    for i, (line, bold) in enumerate(_note_block(note)):
        weight = ' font-weight="bold"' if bold else ""
        y = note.y + NOTE_PADDING + 12 + i * NOTE_LINE_HEIGHT
        parts.append(
            f'<text x="{x:.1f}" y="{y:.1f}" font-size="{NOTE_FONT_SIZE}"{weight} text-anchor="{_NOTE_ANCHOR[align]}" '
            f'fill="{_TEXT_COLOR}">{_text(line)}</text>'
        )
    return "".join(parts)


def _framed_notes(notes: list[NoteOut]) -> list[NoteOut]:
    """The notes with the size each is drawn at (`diagram_note_layout.drawn_size`: an Automatic note's computed frame, else
    its stored one), so every later step, the leaders' attach points included, reads one frame."""
    framed: list[NoteOut] = []
    for n in notes:
        width, height = drawn_size(n.size_mode, n.tone, n.title, n.text, n.width, n.height)
        framed.append(n.model_copy(update={"width": width, "height": height}))
    return framed


def _symbol_group(markup: str, x: float, y: float, size: float) -> str | None:
    """The sanitised symbol fitted into a `size` square at `(x, y)`, or `None` if it has no usable root element."""
    match = _ROOT.search(markup)
    if match is None:
        return None
    tag = match.group(0)
    box = _VIEWBOX.search(tag)
    if box is None:
        sizes = {k.lower(): float(v) for k, v in _SIZE.findall(tag)}
        width, height = sizes.get("width", 64.0), sizes.get("height", 64.0)
        view = f' viewBox="0 0 {width:g} {height:g}"'
    else:
        view = ""
    cleaned = _BOX_ATTR.sub("", tag)
    cleaned = cleaned[:-1].rstrip("/ ") + f'{view} x="{x:.1f}" y="{y:.1f}" width="{size:.1f}" height="{size:.1f}">'
    return markup[: match.start()] + cleaned + markup[match.end():]


def _shape(shape: str, x: float, y: float, w: float, h: float, color: str) -> str:
    """The outline of a node for the given shape name (an unknown name draws a rectangle)."""
    style = f'fill="#FFFFFF" fill-opacity="0.92" stroke="{color}" stroke-width="2"'
    if shape == "rounded":
        return f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="14" {style}/>'
    if shape == "ellipse":
        return f'<ellipse cx="{x + w / 2:.1f}" cy="{y + h / 2:.1f}" rx="{w / 2:.1f}" ry="{h / 2:.1f}" {style}/>'
    if shape == "hexagon":
        k = min(w * 0.18, 24)
        pts = [(x + k, y), (x + w - k, y), (x + w, y + h / 2), (x + w - k, y + h), (x + k, y + h), (x, y + h / 2)]
        return f'<polygon points="{" ".join(f"{px:.1f},{py:.1f}" for px, py in pts)}" {style}/>'
    if shape == "parallelogram":
        k = min(w * 0.15, 24)
        pts = [(x + k, y), (x + w, y), (x + w - k, y + h), (x, y + h)]
        return f'<polygon points="{" ".join(f"{px:.1f},{py:.1f}" for px, py in pts)}" {style}/>'
    if shape == "cylinder":
        ry = min(h * 0.14, 14)
        return (
            f'<path d="M{x:.1f},{y + ry:.1f} a{w / 2:.1f},{ry:.1f} 0 0 1 {w:.1f},0 v{h - 2 * ry:.1f} '
            f'a{w / 2:.1f},{ry:.1f} 0 0 1 {-w:.1f},0 z" {style}/>'
            f'<path d="M{x:.1f},{y + ry:.1f} a{w / 2:.1f},{ry:.1f} 0 0 0 {w:.1f},0" fill="none" stroke="{color}" stroke-width="2"/>'
        )
    if shape == "folder":
        tab = min(w * 0.35, 56)
        return (
            f'<path d="M{x:.1f},{y:.1f} h{tab:.1f} l10,10 h{w - tab - 10:.1f} v{h - 10:.1f} h{-w:.1f} z" {style}/>'
        )
    if shape == "chip":
        pins = "".join(
            f'<path d="M{x + w * f:.1f},{y - 6:.1f} v6 M{x + w * f:.1f},{y + h:.1f} v6" stroke="{color}" stroke-width="2"/>'
            for f in (0.25, 0.5, 0.75)
        )
        return f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="3" {style}/>{pins}'
    return f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" {style}/>'


def _caption(node: ViewNode) -> str:
    """The small line a box is measured with: its code and its type (the screen draws both, an export only the code, so the
    frame is the same in each)."""
    return f"{node.unique_code} · {node.element_type_name}" if node.element_type_name else node.unique_code


def _framed_nodes(nodes: list[ViewNode], symbols: dict[uuid.UUID, str]) -> list[ViewNode]:
    """The nodes with the size each is drawn at (`diagram_box_fit.drawn_box_size`: the stored size, larger where its symbol, code
    and name need it), so every later step, a line's attach points included, reads one frame. A locked node is measured on the
    code it draws."""
    framed: list[ViewNode] = []
    for n in nodes:
        if n.locked:
            width, height = drawn_box_size(False, "", n.unique_code, n.width, n.height)
        else:
            has_symbol = n.symbol_id is not None and n.symbol_id in symbols
            width, height = drawn_box_size(has_symbol, _caption(n), n.name, n.width, n.height)
        framed.append(n.model_copy(update={"width": width, "height": height}))
    return framed


def _node(node: ViewNode, symbols: dict[uuid.UUID, str]) -> str:
    """One node: outline or symbol, then its code, name and port tabs."""
    x, y, w, h = node.x, node.y, node.width, node.height
    if node.locked:
        return (
            f'<g data-element="{node.element_id}"><rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" fill="#F1F5F9" '
            f'stroke="#94A3B8" stroke-width="2" stroke-dasharray="6 4"/>'
            f'<text x="{x + w / 2:.1f}" y="{y + h / 2:.1f}" text-anchor="middle" dominant-baseline="middle" font-size="12" '
            f'fill="#64748B">{_text(node.unique_code)}</text></g>'
        )
    color = _color(node.color_light)
    faded = ' opacity="0.55"' if node.status in INACTIVE_STATUSES else ""
    parts = [f'<g data-element="{node.element_id}"{faded}>']
    drawing = symbols.get(node.symbol_id) if node.symbol_id else None
    group = None
    if drawing is not None:
        group = _symbol_group(drawing, x + w / 2 - SYMBOL_HEIGHT / 2, y + INSET_Y, SYMBOL_HEIGHT)
    lines = fit_box(group is not None, _caption(node), node.name, w).lines
    if group is not None:
        parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="6" fill="#FFFFFF" fill-opacity="0.92" '
                     f'stroke="{color}" stroke-width="2"/>')
        parts.append(f'<g color="{color}" style="color:{color}">{group}</g>')
        top = y + INSET_Y + SYMBOL_HEIGHT + SYMBOL_GAP
    else:
        parts.append(_shape(node.shape, x, y, w, h, color))
        block = CAPTION_LINE_HEIGHT + len(lines) * NAME_LINE_HEIGHT
        top = y + INSET_Y if node.display_note else y + (h - block) / 2
    parts.append(
        f'<text x="{x + w / 2:.1f}" y="{top + CAPTION_LINE_HEIGHT - 3:.1f}" text-anchor="middle" font-size="10" fill="#64748B">'
        f"{_text(node.unique_code)}</text>"
    )
    for i, line in enumerate(lines):
        parts.append(
            f'<text x="{x + w / 2:.1f}" y="{top + CAPTION_LINE_HEIGHT + 12 + i * NAME_LINE_HEIGHT:.1f}" text-anchor="middle" '
            f'font-size="12" font-weight="600" fill="{_TEXT_COLOR}">{_text(line)}</text>'
        )
    note_top = top + CAPTION_LINE_HEIGHT + len(lines) * NAME_LINE_HEIGHT + 2
    room = int((y + h - 10 - note_top) // 12) + 1
    for i, line in enumerate(_note_lines(node.display_note, max(int(w / 6), 6), room)):
        parts.append(
            f'<text x="{x + w / 2:.1f}" y="{note_top + i * 12:.1f}" text-anchor="middle" font-size="10" '
            f'fill="#475569">{_text(line)}</text>'
        )
    for i, port in enumerate(node.ports[:12]):
        px = x + (i + 1) * w / (min(len(node.ports), 12) + 1)
        parts.append(f'<circle cx="{px:.1f}" cy="{y + h:.1f}" r="3.5" fill="{color}"><title>{_text(port.name)}</title></circle>')
    parts.append("</g>")
    return "".join(parts)


def _boundary_outline(shape: str, x: float, y: float, w: float, h: float) -> str:
    """The outline of a boundary box: a flag with its tip on the right (input) or left (output), a hexagon (both ways)
    or an ellipse (no direction disclosed)."""
    style = 'fill="#F8FAFC" stroke="#475569" stroke-width="2"'
    k = min(h / 2, 18.0)
    if shape == "input":
        pts = [(x, y), (x + w - k, y), (x + w, y + h / 2), (x + w - k, y + h), (x, y + h)]
    elif shape == "output":
        pts = [(x + k, y), (x + w, y), (x + w, y + h), (x + k, y + h), (x, y + h / 2)]
    elif shape == "bidirectional":
        pts = [(x + k, y), (x + w - k, y), (x + w, y + h / 2), (x + w - k, y + h), (x + k, y + h), (x, y + h / 2)]
    else:
        return f'<ellipse cx="{x + w / 2:.1f}" cy="{y + h / 2:.1f}" rx="{w / 2:.1f}" ry="{h / 2:.1f}" {style}/>'
    return f'<polygon points="{" ".join(f"{px:.1f},{py:.1f}" for px, py in pts)}" {style}/>'


def _boundary(box: ViewBoundary) -> str:
    """One boundary box: its outline, the outer connection's code, the element outside and the coverage marker."""
    x, y, w, h = box.x, box.y, box.width, box.height
    name = box.outside_element_code if box.locked else f"{box.outside_element_code} {box.outside_element_name}".strip()
    marker = "#475569" if box.covered else "none"
    state = "Realised" if box.covered else "Not realised"
    parts = [
        f'<g data-boundary="{box.id}">', _boundary_outline(box.shape, x, y, w, h),
        f'<text x="{x + w / 2:.1f}" y="{y + h / 2 - 3:.1f}" text-anchor="middle" font-size="10" fill="#64748B">'
        f'{_text(box.connection_code)}</text>',
    ]
    for i, line in enumerate(_wrap(name, max(int(w / 7), 6), 1)):
        parts.append(
            f'<text x="{x + w / 2:.1f}" y="{y + h / 2 + 10 + i * 12:.1f}" text-anchor="middle" font-size="11" font-weight="600" '
            f'fill="{_TEXT_COLOR}">{_text(line)}</text>'
        )
    parts.append(
        f'<circle cx="{x + w - 9:.1f}" cy="{y + 9:.1f}" r="4" fill="{marker}" stroke="#475569" stroke-width="1.5">'
        f"<title>{state}</title></circle></g>"
    )
    return "".join(parts)


def _shape_value(shape: LineShape | None) -> str | None:
    """A line's own shape as its plain value, or `None` when it follows the diagram."""
    return shape.value if shape is not None else None


def leader_shape(leader: LeaderOut, default_shape: str) -> str:
    """The shape a note's leader is drawn in: its own, else the diagram's default (shared with the state machine drawing)."""
    return effective_shape(_shape_value(leader.line_shape), default_shape)


def _anchor_route(
    anchors: list[AnchorOut], edge: ViewEdge,
) -> tuple[AttachPoint | None, AttachPoint | None, list[Point], str | None]:
    """How a person routed the line: (source end, target end, vertices from the source to the target, own shape or `None`). A line drawn for
    one connection with a route of its own uses that route; any other line uses its pair's. An anchor stored for the opposite
    direction of the same pair applies with its ends swapped and its vertices reversed."""
    for anchor in anchors:
        if anchor.connection_id != edge.route_connection_id:
            continue
        points: list[Point] = [(p.x, p.y) for p in anchor.points]
        if (anchor.source_element_id, anchor.target_element_id) == (edge.source_element_id, edge.target_element_id):
            return anchor.source_point, anchor.target_point, points, _shape_value(anchor.line_shape)
        if (anchor.source_element_id, anchor.target_element_id) == (edge.target_element_id, edge.source_element_id):
            return anchor.target_point, anchor.source_point, points[::-1], _shape_value(anchor.line_shape)
    return None, None, [], None


@dataclass(frozen=True)
class _Run:
    """One drawn connection line: where it runs (after the sideways offset of parallel lines) and its middle."""

    edge: ViewEdge
    start: Point
    vertices: list[Point]
    end: Point
    shape: str
    middle: Point
    directions: Directions = NO_DIRECTIONS


#: A drawn leader: where it starts, its vertices, where it ends and the directions it leaves its boxes in.
LeaderRun = tuple[Point, list[Point], Point, Directions]


def _edge_runs(
    edges: list[ViewEdge], boxes: dict[uuid.UUID, ViewNode | ViewBoundary], anchors: list[AnchorOut], default_shape: str,
) -> list[_Run]:
    """The geometry of every drawn line, in the model's order: the points each line meets its boxes at come from
    `diagram_line_anchors` (no two lines share a path; lines left on the same points are spread sideways unless a person
    routed them). A line's own shape wins over `default_shape`, the diagram's."""
    routes = {edge.id: _anchor_route(anchors, edge) for edge in edges}
    placed = assign_line_anchors(
        {str(box_id): AnchorBox(b.x, b.y, b.width, b.height) for box_id, b in boxes.items()},
        [
            AnchorLine(
                edge.id, str(edge.source_element_id), str(edge.target_element_id),
                routes[edge.id][0], routes[edge.id][1], tuple(routes[edge.id][2]),
            )
            for edge in edges
        ],
    )
    runs: list[_Run] = []
    for edge in edges:
        a, b = boxes.get(edge.source_element_id), boxes.get(edge.target_element_id)
        anchor = placed.get(edge.id)
        if a is None or b is None or anchor is None or anchor.loop_slot is not None:
            continue
        _, _, vertices, own_shape = routes[edge.id]
        shape = effective_shape(own_shape, default_shape)
        box_a, box_b = (a.x, a.y, a.width, a.height), (b.x, b.y, b.width, b.height)
        (x1, y1), (x2, y2) = point_xy(box_a, anchor.source), point_xy(box_b, anchor.target)
        x1, y1, x2, y2 = x1 + anchor.shift[0], y1 + anchor.shift[1], x2 + anchor.shift[0], y2 + anchor.shift[1]
        # A Curved line leaves each box along its outward direction; no other shape uses the directions.
        directions: Directions = line_directions(box_a, box_b, anchor.source, anchor.target, vertices) if shape == "curved" else NO_DIRECTIONS
        middle = (
            line_middle((x1, y1), vertices, (x2, y2), shape, directions) if vertices or shape == "curved" else ((x1 + x2) / 2, (y1 + y2) / 2)
        )
        runs.append(_Run(edge, (x1, y1), vertices, (x2, y2), shape, middle, directions))
    return runs


def _edges(runs: list[_Run], hops: dict[str, str]) -> tuple[str, str]:
    """The `<defs>` (arrowheads) and the lines. A line in `hops` is drawn along its hop path (`diagram_line_hops`)."""
    colors: dict[str, int] = {}
    lines: list[str] = []
    for run in runs:
        edge, (x1, y1), (x2, y2), vertices = run.edge, run.start, run.end, run.vertices
        mx, my = run.middle
        color = _color(edge.color_light)
        marker = colors.setdefault(color, len(colors))
        dash = ' stroke-dasharray="7 5"' if edge.indirect else (
            ' stroke-dasharray="2 4"' if edge.line_style == "dotted" else (' stroke-dasharray="7 5"' if edge.line_style == "dashed" else "")
        )
        arrow = f' marker-end="url(#arrow{marker})"' if not edge.two_way else ""
        if edge.id in hops or vertices or run.shape != "straight":
            path = hops.get(edge.id) or line_path((x1, y1), vertices, (x2, y2), run.shape, run.directions)
            lines.append(f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2"{dash}{arrow}/>')
        else:
            lines.append(
                f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{color}" stroke-width="2"{dash}{arrow}/>'
            )
        if edge.label:
            lines.append(_edge_label_text(edge.label, mx, my - 5))
        if edge.count > 1:
            lines.append(
                f'<circle cx="{mx:.1f}" cy="{my:.1f}" r="9" fill="#FFFFFF" stroke="{color}" stroke-width="1.5"/>'
                f'<text x="{mx:.1f}" y="{my + 3.5:.1f}" text-anchor="middle" font-size="10" fill="{_TEXT_COLOR}">{edge.count}</text>'
            )
    defs = "".join(
        f'<marker id="arrow{i}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">'
        f'<path d="M0,0 L10,5 L0,10 z" fill="{color}"/></marker>'
        for color, i in colors.items()
    )
    return defs, "".join(lines)


def _edge_label_text(label: str, x: float, bottom: float) -> str:
    """A line's label: one `<text>` per line of it, the last line's baseline at `bottom`, with a white halo so it stays
    readable over a line.

    Args:
        label: The label text; a `\\n` starts a new line (connection names, then the type and protocol).
        x: The middle of the line.
        bottom: The baseline of the last line.

    Returns:
        The SVG text elements, every line XML-escaped.
    """
    rows = [row for row in label.split("\n") if row]
    return "".join(
        f'<text x="{x:.1f}" y="{bottom - (len(rows) - 1 - i) * 12:.1f}" text-anchor="middle" font-size="10" fill="{_TEXT_COLOR}" '
        f'stroke="#FFFFFF" stroke-width="3" paint-order="stroke">{_text(row)}</text>'
        for i, row in enumerate(rows)
    )


#: Fill and stroke of an annotation note by tone (the light-theme values of the product's tone colours).
_TONES: dict[str, tuple[str, str]] = {
    "none": ("none", "#64748B"),
    "neutral": ("#F1F5F9", "#64748B"),
    "info": ("#DBEAFE", "#2563EB"),
    "success": ("#DCFCE7", "#16A34A"),
    "warning": ("#FEF9C3", "#CA8A04"),
    "danger": ("#FEE2E2", "#DC2626"),
}


def _drawn_notes(notes: list[NoteOut]) -> list[NoteOut]:
    """The notes the document draws: all of them, except an empty note with no tone, which would be invisible (the editor
    shows it with a faint outline so it can be found, which is never exported)."""
    return [n for n in notes if n.tone != NoteTone.NONE or n.text.strip() or n.title.strip()]


def _leader_run(
    note: NoteOut, leader: LeaderOut, boxes: dict[uuid.UUID, ViewNode | ViewBoundary], middles: dict[str, tuple[float, float]],
    edges: list[ViewEdge], states: Mapping[uuid.UUID, tuple[float, float, float, float]] | None = None,
    transitions: Mapping[uuid.UUID, Point] | None = None,
) -> LeaderRun | None:
    """Where a leader runs, as `(start, vertices, end, directions)`, or `None` when its target is not drawn.

    The end is a box's attach point (an element of a block diagram, a state of a state machine diagram), a drawn line's middle
    (a connection, or a transition) or the free point. A box end and the start choose their attach points by one rule, held
    equal to the browser's: a point a person chose wins; otherwise an open end is the point of its box nearest the vertex next
    to it, and with no vertices the nearest pair of attach points (a box target) or the note's point nearest the end (a line or a
    free point). The directions are those a Curved leader leaves its boxes in (`diagram_points.line_directions`); an end on a
    line's middle or at a free point has none, so it arrives along the chord.

    Args:
        note: The note the leader belongs to.
        leader: The leader.
        boxes: A block diagram's drawn boxes by element id (and boundary box id).
        middles: A block diagram's drawn lines' middles by drawn edge id.
        edges: A block diagram's drawn edges, to find the one that stands for a connection.
        states: A state machine diagram's drawn state frames by state id (`None` in a block diagram).
        transitions: A state machine diagram's transition middles by transition id (`None` in a block diagram).
    """
    kind = leader.kind
    block = (note.x, note.y, note.width, note.height)
    vertices = [(p.x, p.y) for p in leader.points]
    end: Point
    target_box: tuple[float, float, float, float] | None = None
    if kind == LeaderKind.ELEMENT and leader.element_id is not None:
        target = boxes.get(leader.element_id)
        if target is None:
            return None
        target_box = (target.x, target.y, target.width, target.height)
    elif kind == LeaderKind.STATE and leader.state_id is not None:
        target_box = (states or {}).get(leader.state_id)
        if target_box is None:
            return None
    if target_box is not None:
        if vertices:
            into = nearest_point(target_box, vertices[-1])
            end = point_xy(target_box, into)
            from_point = leader.start_point or nearest_point(block, vertices[0])
            return point_xy(block, from_point), vertices, end, line_directions(block, target_box, from_point, into, vertices)
        from_point, to_point = line_points(block, target_box, leader.start_point, None)
        return point_xy(block, from_point), [], point_xy(target_box, to_point), line_directions(block, target_box, from_point, to_point, [])
    elif kind == LeaderKind.CONNECTION and leader.connection_id is not None:
        drawn = next((e for e in edges if e.id in middles and any(c.id == leader.connection_id for c in e.connections)), None)
        if drawn is None:
            return None
        end = middles[drawn.id]
    elif kind == LeaderKind.TRANSITION and leader.transition_id is not None:
        middle = (transitions or {}).get(leader.transition_id)
        if middle is None:
            return None
        end = middle
    elif kind == LeaderKind.POINT and leader.x is not None and leader.y is not None:
        end = (leader.x, leader.y)
    else:
        return None
    toward = vertices[0] if vertices else end
    start_point = leader.start_point or nearest_point(block, toward)
    return point_xy(block, start_point), vertices, end, (outward_direction(block, start_point, toward), None)


def _leader_marker(tone: str, style: LineEnd, stroke: str, defs: dict[str, str]) -> str:
    """The `url(#…)` of the marker that draws `style` in the tone's colour, registering its definition in `defs` once; the
    empty string for a plain end."""
    if style == LineEnd.NONE:
        return ""
    name = f"leader-{style.value}-{tone}"
    if name not in defs:
        shape = (
            f'<path d="M0,0 L10,5 L0,10 z" fill="{stroke}"/>' if style == LineEnd.ARROW else f'<circle cx="5" cy="5" r="4" fill="{stroke}"/>'
        )
        ref = 9 if style == LineEnd.ARROW else 5
        defs[name] = (
            f'<marker id="{name}" viewBox="0 0 10 10" refX="{ref}" refY="5" markerWidth="8" markerHeight="8" '
            f'orient="auto-start-reverse">{shape}</marker>'
        )
    return f"url(#{name})"


def _leader_runs(
    notes: list[NoteOut], boxes: dict[uuid.UUID, ViewNode | ViewBoundary], middles: dict[str, tuple[float, float]],
    edges: list[ViewEdge], states: Mapping[uuid.UUID, tuple[float, float, float, float]] | None = None,
    transitions: Mapping[uuid.UUID, Point] | None = None,
) -> dict[uuid.UUID, LeaderRun]:
    """Where each drawn leader runs, by leader id (a leader whose target is not drawn is left out); the arguments after `edges`
    are a state machine diagram's targets (see `_leader_run`)."""
    runs: dict[uuid.UUID, LeaderRun] = {}
    for n in _drawn_notes(notes):
        for leader in n.leaders:
            run = _leader_run(n, leader, boxes, middles, edges, states, transitions)
            if run is not None:
                runs[leader.id] = run
    return runs


def _hop_paths(
    runs: list[_Run], leader_runs: dict[uuid.UUID, LeaderRun], notes: list[NoteOut], default_shape: str,
) -> dict[str, str]:
    """The hop path of every connection and leader that crosses another line (`diagram_line_hops`)."""
    lines = [HopLine(str(r.edge.id), r.start, r.vertices, r.end, r.shape, r.directions) for r in runs]
    for n in _drawn_notes(notes):
        for leader in n.leaders:
            if leader.id in leader_runs:
                start, vertices, end, directions = leader_runs[leader.id]
                lines.append(HopLine(str(leader.id), start, vertices, end, leader_shape(leader, default_shape), directions))
    return line_hops(lines)


def _notes(
    notes: list[NoteOut], leader_runs: dict[uuid.UUID, LeaderRun], hops: dict[str, str],
    default_shape: str = "straight",
) -> tuple[str, str, str]:
    """The `<defs>` (a start and an end marker per tone and style used), the leaders (drawn under everything) and the note
    blocks (over it). A leader in `hops` is drawn along its hop path."""
    defs: dict[str, str] = {}
    leaders: list[str] = []
    blocks: list[str] = []
    for n in _drawn_notes(notes):
        tone = n.tone.value if n.tone.value in _TONES else "neutral"
        fill, stroke = _TONES[tone]
        for leader in n.leaders:
            run = leader_runs.get(leader.id)
            if run is None:
                continue
            start, vertices, end, directions = run
            start_marker = _leader_marker(tone, leader.start_style, stroke, defs)
            end_marker = _leader_marker(tone, leader.end_style, stroke, defs)
            marks = (f' marker-start="{start_marker}"' if start_marker else "") + (f' marker-end="{end_marker}"' if end_marker else "")
            shape = leader_shape(leader, default_shape)
            if vertices or str(leader.id) in hops or shape != "straight":
                path = hops.get(str(leader.id)) or line_path(start, vertices, end, shape, directions)
                leaders.append(f'<path d="{path}" fill="none" stroke="{stroke}" stroke-width="1.5"{marks}/>')
            else:
                leaders.append(
                    f'<line x1="{start[0]:.1f}" y1="{start[1]:.1f}" x2="{end[0]:.1f}" y2="{end[1]:.1f}" stroke="{stroke}" '
                    f'stroke-width="1.5"{marks}/>'
                )
        box = (
            "" if tone == "none"
            else f'<rect x="{n.x:.1f}" y="{n.y:.1f}" width="{n.width:.1f}" height="{n.height:.1f}" fill="{fill}" stroke="{stroke}"/>'
        )
        blocks.append(
            f'<g data-note="{n.id}">{box}{_note_text(n)}</g>'
        )
    return "".join(defs.values()), "".join(leaders), "".join(blocks)


def render_diagram(db: Session, view: DiagramView) -> str:
    """The diagram as an SVG document.

    Args:
        db: Session, used to read the symbols the nodes are drawn with.
        view: The resolved diagram (`diagram_view.build_view`).

    Returns:
        The SVG text.
    """
    view = view.model_copy(update={"notes": _framed_notes(view.notes)})
    visible = [n for n in view.nodes if not n.hidden]
    symbol_ids = {n.symbol_id for n in visible if n.symbol_id}
    symbols: dict[uuid.UUID, str] = {}
    if symbol_ids:
        for row in db.scalars(select(ArchitectureSymbol).where(ArchitectureSymbol.id.in_(symbol_ids))):
            try:
                symbols[row.id] = symbol_svg(db, row)
            except LookupError:
                continue
    visible = _framed_nodes(visible, symbols)
    boxes: dict[uuid.UUID, ViewNode | ViewBoundary] = {n.element_id: n for n in visible}
    boxes.update({b.id: b for b in view.boundaries})
    drawn_edges = [e for e in view.edges if e.source_element_id in boxes and e.target_element_id in boxes]
    drawn_boxes: list[ViewNode | ViewBoundary] = [*visible, *view.boundaries]
    drawn_notes = _drawn_notes(view.notes)
    leader_points = [
        (p.x, p.y) for n in drawn_notes for leader in n.leaders for p in leader.points
    ] + [(leader.x, leader.y) for n in drawn_notes for leader in n.leaders if leader.x is not None and leader.y is not None]
    xs = [v for n in drawn_boxes for v in (n.x, n.x + n.width)] + [v for n in drawn_notes for v in (n.x, n.x + n.width)]
    xs += [px for px, _ in leader_points if px is not None]
    xs += [p.x for a in view.anchors for p in a.points]
    ys = [v for n in drawn_boxes for v in (n.y - 6, n.y + n.height + 6)] + [v for n in drawn_notes for v in (n.y, n.y + n.height)]
    ys += [py for _, py in leader_points if py is not None]
    ys += [p.y for a in view.anchors for p in a.points]
    if not xs:
        min_x, min_y, width, height = 0.0, 0.0, 320.0, 120.0
        body = '<text x="160" y="60" text-anchor="middle" font-size="12" fill="#64748B">Empty diagram</text>'
        defs = ""
    else:
        min_x, min_y = min(xs) - _MARGIN, min(ys) - _MARGIN
        width, height = max(xs) - min_x + _MARGIN, max(ys) - min_y + _MARGIN
        default_shape = view.diagram.line_shape.value
        runs = _edge_runs(drawn_edges, boxes, view.anchors, default_shape)
        leader_runs = _leader_runs(view.notes, boxes, {str(r.edge.id): r.middle for r in runs}, drawn_edges)
        hops = _hop_paths(runs, leader_runs, view.notes, default_shape) if view.diagram.line_hops else {}
        defs, edge_svg = _edges(runs, hops)
        note_defs, leaders, notes = _notes(view.notes, leader_runs, hops, default_shape)
        defs += note_defs
        body = (
            f"{edge_svg}{leaders}{''.join(_node(n, symbols) for n in visible)}{''.join(_boundary(b) for b in view.boundaries)}{notes}"
        )
    title = _text(f"{view.diagram.unique_code} {view.diagram.name}")
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{min_x:.1f} {min_y:.1f} {width:.1f} {height:.1f}" '
        f'width="{width:.0f}" height="{height:.0f}" font-family="Helvetica, Arial, sans-serif" role="img" aria-label="{title}">'
        f"<title>{title}</title><defs>{defs}</defs>{body}</svg>"
    )
