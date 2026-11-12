"""
Module: modules.architecture.diagram_svg

Renders a resolved diagram (`schemas.DiagramView`) as one SVG document, for the server's SVG endpoint and the report
part, so a document shows what the screen shows.

Responsibilities:
- Draw each visible node as its symbol or its type's shape, its code and name, and its ports as small tabs.
- Draw each line between the node boxes, dashed when indirect, with an arrowhead when it has one direction, a count
  when several connections collapse into it, and (with connection detail on) its type and protocol.
- Draw notes as plain text.

Design decisions:
- **Everything user-supplied is text.** Names, codes, notes and labels are XML-escaped and stripped of control
  characters before they enter the document; a symbol is the one place markup is embedded, and only the sanitised SVG
  of `symbols.symbol_svg` is ever used (a symbol that cannot be read falls back to the type's shape).
- **Light-theme colours.** The server document is for reports and files, so it uses the type's light colour (or a
  neutral default) on a transparent background; the browser themes its own canvas.
- **Deterministic.** Elements are drawn in the order of the view, so equal views give equal bytes.
- A node a toggle hides, and a line with a hidden end, are not drawn; a locked node is a dashed box with its code.

Dependencies: `schemas` (the view), `symbols` (the safe markup), `models` (symbol rows).
"""

from __future__ import annotations

import math
import re
import uuid
from xml.sax.saxutils import escape

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.architecture.models import ArchitectureSymbol
from app.modules.architecture.schemas import DiagramView, ViewEdge, ViewNode
from app.modules.architecture.symbols import symbol_svg

_DEFAULT_COLOR = "#475569"
_TEXT_COLOR = "#1E293B"
_MARGIN = 32.0
_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
_CONTROL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")
_ROOT = re.compile(r"<svg\b[^>]*>", re.IGNORECASE)
_VIEWBOX = re.compile(r'viewBox\s*=\s*"([^"]*)"', re.IGNORECASE)
_SIZE = re.compile(r'\b(width|height)\s*=\s*"\s*([0-9.]+)\s*(?:px)?\s*"', re.IGNORECASE)
_BOX_ATTR = re.compile(r'\s(?:x|y|width|height)\s*=\s*"[^"]*"', re.IGNORECASE)


def _text(value: str) -> str:
    """User text made safe to put in an XML text node or attribute."""
    return escape(_CONTROL.sub("", value), {'"': "&quot;"})


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
    faded = ' opacity="0.55"' if node.status == "retired" else ""
    parts = [f'<g data-element="{node.element_id}"{faded}>']
    drawing = symbols.get(node.symbol_id) if node.symbol_id else None
    group = None
    if drawing is not None:
        size = max(min(h - 28, w * 0.5, 56), 16)
        group = _symbol_group(drawing, x + w / 2 - size / 2, y + 6, size)
    if group is not None:
        parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="6" fill="#FFFFFF" fill-opacity="0.92" '
                     f'stroke="{color}" stroke-width="2"/>')
        parts.append(f'<g color="{color}" style="color:{color}">{group}</g>')
        text_y = y + 6 + size + 12
    else:
        parts.append(_shape(node.shape, x, y, w, h, color))
        text_y = y + h / 2 - 4 if node.name else y + h / 2
    parts.append(
        f'<text x="{x + w / 2:.1f}" y="{text_y:.1f}" text-anchor="middle" font-size="10" fill="#64748B">{_text(node.unique_code)}</text>'
    )
    for i, line in enumerate(_wrap(node.name, max(int(w / 7), 6), 2)):
        parts.append(
            f'<text x="{x + w / 2:.1f}" y="{text_y + 13 + i * 13:.1f}" text-anchor="middle" font-size="12" font-weight="600" '
            f'fill="{_TEXT_COLOR}">{_text(line)}</text>'
        )
    for i, port in enumerate(node.ports[:12]):
        px = x + (i + 1) * w / (min(len(node.ports), 12) + 1)
        parts.append(f'<circle cx="{px:.1f}" cy="{y + h:.1f}" r="3.5" fill="{color}"><title>{_text(port.name)}</title></circle>')
    parts.append("</g>")
    return "".join(parts)


def _clip(cx: float, cy: float, w: float, h: float, tx: float, ty: float) -> tuple[float, float]:
    """Where the line from a box's centre toward `(tx, ty)` leaves the box."""
    dx, dy = tx - cx, ty - cy
    if dx == 0 and dy == 0:
        return cx, cy
    scale = min((w / 2) / abs(dx) if dx else math.inf, (h / 2) / abs(dy) if dy else math.inf)
    return cx + dx * scale, cy + dy * scale


def _edges(edges: list[ViewEdge], boxes: dict[uuid.UUID, ViewNode]) -> tuple[str, str]:
    """The `<defs>` (arrowheads) and the lines."""
    colors: dict[str, int] = {}
    lines: list[str] = []
    rank: dict[frozenset, int] = {}
    totals: dict[frozenset, int] = {}
    for edge in edges:
        key = frozenset((edge.source_element_id, edge.target_element_id))
        totals[key] = totals.get(key, 0) + 1
    for edge in edges:
        a, b = boxes.get(edge.source_element_id), boxes.get(edge.target_element_id)
        if a is None or b is None:
            continue
        key = frozenset((edge.source_element_id, edge.target_element_id))
        index = rank.get(key, 0)
        rank[key] = index + 1
        offset = (index - (totals[key] - 1) / 2) * 16
        ax, ay, bx, by = a.x + a.width / 2, a.y + a.height / 2, b.x + b.width / 2, b.y + b.height / 2
        length = math.hypot(bx - ax, by - ay) or 1.0
        nx, ny = -(by - ay) / length * offset, (bx - ax) / length * offset
        x1, y1 = _clip(ax, ay, a.width, a.height, bx + nx, by + ny)
        x2, y2 = _clip(bx, by, b.width, b.height, ax + nx, ay + ny)
        x1, y1, x2, y2 = x1 + nx, y1 + ny, x2 + nx, y2 + ny
        color = _color(edge.color_light)
        marker = colors.setdefault(color, len(colors))
        dash = ' stroke-dasharray="7 5"' if edge.indirect else (
            ' stroke-dasharray="2 4"' if edge.line_style == "dotted" else (' stroke-dasharray="7 5"' if edge.line_style == "dashed" else "")
        )
        arrow = f' marker-end="url(#arrow{marker})"' if not edge.two_way else ""
        lines.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{color}" stroke-width="2"{dash}{arrow}/>'
        )
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        if edge.label:
            lines.append(
                f'<text x="{mx:.1f}" y="{my - 5:.1f}" text-anchor="middle" font-size="10" fill="{_TEXT_COLOR}" '
                f'stroke="#FFFFFF" stroke-width="3" paint-order="stroke">{_text(edge.label)}</text>'
            )
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


def render_diagram(db: Session, view: DiagramView) -> str:
    """The diagram as an SVG document.

    Args:
        db: Session, used to read the symbols the nodes are drawn with.
        view: The resolved diagram (`diagram_view.build_view`).

    Returns:
        The SVG text.
    """
    visible = [n for n in view.nodes if not n.hidden]
    symbol_ids = {n.symbol_id for n in visible if n.symbol_id}
    symbols: dict[uuid.UUID, str] = {}
    if symbol_ids:
        for row in db.scalars(select(ArchitectureSymbol).where(ArchitectureSymbol.id.in_(symbol_ids))):
            try:
                symbols[row.id] = symbol_svg(db, row)
            except LookupError:
                continue
    boxes = {n.element_id: n for n in visible}
    drawn_edges = [e for e in view.edges if e.source_element_id in boxes and e.target_element_id in boxes]
    xs = [v for n in visible for v in (n.x, n.x + n.width)] + [v for n in view.notes for v in (n.x, n.x + n.width)]
    ys = [v for n in visible for v in (n.y - 6, n.y + n.height + 6)] + [v for n in view.notes for v in (n.y, n.y + n.height)]
    if not xs:
        min_x, min_y, width, height = 0.0, 0.0, 320.0, 120.0
        body = '<text x="160" y="60" text-anchor="middle" font-size="12" fill="#64748B">Empty diagram</text>'
        defs = ""
    else:
        min_x, min_y = min(xs) - _MARGIN, min(ys) - _MARGIN
        width, height = max(xs) - min_x + _MARGIN, max(ys) - min_y + _MARGIN
        defs, edge_svg = _edges(drawn_edges, boxes)
        notes = "".join(
            f'<g><rect x="{n.x:.1f}" y="{n.y:.1f}" width="{n.width:.1f}" height="{n.height:.1f}" fill="#FEF9C3" stroke="#CA8A04"/>'
            + "".join(
                f'<text x="{n.x + 6:.1f}" y="{n.y + 16 + i * 13:.1f}" font-size="11" fill="{_TEXT_COLOR}">{_text(line)}</text>'
                for i, line in enumerate(_wrap(n.text, max(int(n.width / 6.5), 6), max(int((n.height - 8) / 13), 1)))
            ) + "</g>"
            for n in view.notes
        )
        body = f"{edge_svg}{''.join(_node(n, symbols) for n in visible)}{notes}"
    title = _text(f"{view.diagram.unique_code} {view.diagram.name}")
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{min_x:.1f} {min_y:.1f} {width:.1f} {height:.1f}" '
        f'width="{width:.0f}" height="{height:.0f}" font-family="Helvetica, Arial, sans-serif" role="img" aria-label="{title}">'
        f"<title>{title}</title><defs>{defs}</defs>{body}</svg>"
    )
