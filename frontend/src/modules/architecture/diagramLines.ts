/**
 * Module: modules/architecture/diagramLines
 *
 * Turns a diagram's model data and the state of the editor (the boxes placed, the view switches that are off, connection
 * detail) into the lines the canvas draws, with the same fields the server's resolved view gives, so the editor shows
 * the effect of an edit before it is saved.
 *
 * Responsibilities:
 * - Combine the model's plain ids (parents, connections, what each view switch hides) with the editor's state and run
 *   `resolveLines` over them.
 * - Shape each resolved line like the server's `ViewEdge`: its connections, label, type attributes and the hidden
 *   elements it passes through, drawn only for what the viewer can read.
 *
 * Design decisions:
 * - Display only. Nothing here is stored or sent: a diagram saves its boxes and notes, and the server validates them, so a
 *   wrong line can never change stored data and the next load shows the server's own view.
 * - The line shaping mirrors `diagram_view._edges`; the label is `diagram_edge_label.edge_label`'s port; the rule behind the
 *   lines is `diagramResolver`.
 *
 * Dependencies: `diagramResolver`, `types`.
 */
import { outerSide, resolveLines, type ResolvedLine, type ResolverBoundary } from "./diagramResolver";
import type { ArchitectureConnection, DiagramModel, DiagramViewEdge, DiagramViewHop, ModelConnectionType } from "./types";

/** What the editor knows besides the model. */
export interface LineState {
  /** The elements on the diagram (hidden ones included). */
  placed: Iterable<string>;
  /** The view switches that are off in this view. */
  togglesOff: ReadonlySet<string>;
  /** Whether the diagram shows connection detail (types, labels); off merges parallel lines. */
  connectionDetail: boolean;
  /** Whether a line is labelled with the names of its connections. */
  showConnectionNames?: boolean;
  /** The element the diagram shows the inside of, or null for the system context (no boundary boxes). */
  scopeId?: string | null;
  /** The boundary boxes drawn on the diagram (a scoped diagram's outer connections); none for the system context. */
  boundaries?: readonly BoundaryState[];
  /** `{connection id: the two boxes its own route joins}`: connections routed on their own, each drawn as a line apart from its pair's. */
  routed?: ReadonlyMap<string, readonly [string, string]>;
}

/** A boundary box as the editor holds it: its id, the outer connection it stands for and where it sits. */
export interface BoundaryState {
  id: string;
  connectionId: string;
}

/** The lines and the facts about boxes the same resolution gives. */
export interface ResolvedDiagram {
  edges: DiagramViewEdge[];
  /** The placed elements a view switch hides. */
  hidden: Set<string>;
  /** `{placed element id: connections wholly inside it}`. */
  internal: Map<string, string[]>;
}

/** The most connection names written beside one line; the rest are counted ("+2 more"). Mirrors `diagram_edge_label.NAME_LINES_MAX`. */
const NAME_LINES_MAX = 3;

/** The longest a written name may be before it is cut with an ellipsis. Mirrors `diagram_edge_label.NAME_LINE_MAX`. */
const NAME_LINE_MAX = 60;

/** @param names The connection names in the order to write them. @returns The name lines (blank names ignored, at most three, then "+N more"). */
function nameLines(names: readonly string[]): string[] {
  const named = names.map((n) => n.split(/\s+/).filter(Boolean).join(" ")).filter((n) => n !== "");
  // `Array.from` counts characters as the server does (a code point, not a UTF-16 unit).
  const shown = named.slice(0, NAME_LINES_MAX).map((n) => (Array.from(n).length <= NAME_LINE_MAX ? n : `${Array.from(n).slice(0, NAME_LINE_MAX - 1).join("")}…`));
  if (named.length > NAME_LINES_MAX) shown.push(`+${named.length - NAME_LINES_MAX} more`);
  return shown;
}

/**
 * The text on a line: the names of its connections (when the diagram shows them), then the type and protocol connection
 * detail adds, or the count of a merged line. The port of `diagram_edge_label.edge_label`, pinned by `diagramLabelCases.json`.
 *
 * @param count How many connections the line stands for.
 * @param typeName The connections' shared type, when they have one.
 * @param protocol The connections' shared protocol, or blank.
 * @param detail Whether the diagram shows connection detail.
 * @param names The connection names to write, in code order; empty when the diagram does not show connection names.
 * @returns The label (lines joined by a line break), or null when there is nothing to write.
 */
export function edgeLabelText(count: number, typeName: string | undefined, protocol: string, detail: boolean, names: readonly string[] = []): string | null {
  const parts = nameLines(names);
  if (detail) {
    const text = count === 1
      ? (typeName && protocol ? `${typeName} · ${protocol}` : typeName || protocol || null)
      : (typeName ? `${typeName} ×${count}` : `${count} connections`);
    if (text) parts.push(text);
  } else if (parts.length > 0 && count > 1) {
    parts.push(`×${count}`);
  }
  return parts.length > 0 ? parts.join("\n") : null;
}

/**
 * Orders two connections by code so `CON-9` comes before `CON-10` (the order the server writes names in).
 *
 * @param a A connection.
 * @param b Another connection.
 * @returns Negative when `a` comes first.
 */
function codeOrder(a: { unique_code: string }, b: { unique_code: string }): number {
  return a.unique_code.length - b.unique_code.length || (a.unique_code < b.unique_code ? -1 : a.unique_code > b.unique_code ? 1 : 0);
}

/** @returns The lines to draw, the hidden boxes and the internal connections for the editor's current state. */
export function resolveDiagram(model: DiagramModel, state: LineState): ResolvedDiagram {
  const known = new Map(model.elements.map((e) => [e.id, e]));
  const kinds = new Map(model.connection_types.map((t) => [t.id, t]));
  const byId = new Map(model.connections.map((c) => [c.id, c]));

  const hiddenElements = new Set<string>();
  const hiddenConnections = new Set<string>();
  for (const members of model.toggle_members) {
    if (!state.togglesOff.has(members.toggle_id)) continue;
    members.element_ids.forEach((id) => hiddenElements.add(id));
    members.connection_ids.forEach((id) => hiddenConnections.add(id));
  }

  const parents = new Map(Object.entries(model.parents));
  const realisedBy = new Map<string, string[]>();
  for (const r of model.realisations) realisedBy.set(r.outer_connection_id, [...(realisedBy.get(r.outer_connection_id) ?? []), r.inner_connection_id]);
  const boundaries: ResolverBoundary[] = [];
  for (const box of state.boundaries ?? []) {
    const outer = byId.get(box.connectionId);
    const scope = state.scopeId;
    if (!outer || !scope) continue;
    const side = outerSide(scope, parents, outer.source_element_id, outer.target_element_id);
    if (side === null) continue;
    const outside = side === outer.source_element_id ? outer.target_element_id : outer.source_element_id;
    boundaries.push({
      id: box.id, elementId: side, outsideId: outside,
      connectionIds: (realisedBy.get(outer.id) ?? []).filter((id) => byId.has(id)),
    });
  }

  const resolution = resolveLines({
    placed: state.placed,
    parents,
    connections: model.connections
      .filter((c) => known.has(c.source_element_id) && known.has(c.target_element_id))
      .map((c) => ({ id: c.id, sourceId: c.source_element_id, targetId: c.target_element_id, directional: c.directional })),
    hiddenElements, hiddenConnections, mergeParallel: !state.connectionDetail, boundaries, routed: state.routed,
  });

  const boundaryIds = new Set((state.boundaries ?? []).map((b) => b.id));
  const edges = resolution.lines.map((line) => edgeOf(line, byId, kinds, known, state.connectionDetail, state.showConnectionNames ?? false, boundaryIds));
  return { edges, hidden: resolution.hiddenPlaced, internal: resolution.internal };
}

/** One resolved line in the server's `ViewEdge` shape. */
function edgeOf(
  line: ResolvedLine, connections: ReadonlyMap<string, ArchitectureConnection>, kinds: ReadonlyMap<string, ModelConnectionType>,
  elements: ReadonlyMap<string, { unique_code: string; name: string; locked: boolean }>, detail: boolean, showNames: boolean,
  boundaryIds: ReadonlySet<string>,
): DiagramViewEdge {
  const members = line.connectionIds.map((id) => connections.get(id)).filter((c): c is ArchitectureConnection => c !== undefined);
  const typeIds = new Set(members.map((m) => m.connection_type_id));
  const kind = typeIds.size === 1 ? kinds.get([...typeIds][0]) : undefined;
  const protocols = new Set(members.map((m) => m.protocol));
  const hops: DiagramViewHop[] = [];
  for (const id of line.hops) {
    const hop = elements.get(id);
    if (hop && !hop.locked) hops.push({ element_id: id, unique_code: hop.unique_code, name: hop.name });
  }
  return {
    id: `${line.sourceId}-${line.targetId}-${line.connectionIds[0]}`,
    source_element_id: line.sourceId,
    target_element_id: line.targetId,
    source_is_boundary: boundaryIds.has(line.sourceId),
    target_is_boundary: boundaryIds.has(line.targetId),
    two_way: line.twoWay,
    indirect: line.indirect,
    rolled_up: line.rolledUp,
    bridged: line.bridged,
    count: members.length,
    type_name: detail && kind ? kind.name : null,
    line_style: detail && kind ? kind.line_style : null,
    color_light: detail && kind ? kind.color_light : null,
    color_dark: detail && kind ? kind.color_dark : null,
    label: edgeLabelText(
      members.length, kind?.name, protocols.size === 1 ? [...protocols][0] : "", detail,
      showNames ? [...members].sort(codeOrder).map((m) => m.name) : [],
    ),
    connections: members,
    hops,
    routable_connection_ids: line.routable,
    route_connection_id: line.ownRoute,
  };
}
