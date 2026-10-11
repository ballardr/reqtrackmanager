/**
 * Module: components/linkTrace
 *
 * Pure logic behind the trace views (tree and map) of a record's links: no React,
 * no network. The server resolves each edge's `flow` (upstream / downstream /
 * related) relative to the record the edge starts from, so nothing here
 * re-derives direction from link types.
 *
 * Responsibilities:
 * - `hopsFrom`: the edges leaving one record, optionally in one direction only,
 *   paired with the record at their far end (the tree's children).
 * - `mergeGraphs`: fold a further graph read (an expanded branch) into the graph shown.
 * - `layoutLinkMap`: place a graph in layered columns and return SVG coordinates, optionally
 *   skipping hidden (inactive) records and joining what they link to the record in front.
 * - `wrapLabel`: break a record's label into the few short lines a map node has room for.
 *
 * Design decisions:
 * - A trace keeps its direction of travel: a record reached upstream is only
 *   continued through its own upstream edges, a related one through related
 *   edges, so a branch never doubles back through the record it came from or
 *   crosses into the other side. Edges that would break this are not drawn.
 * - The map is deliberately layered, not force-directed (readable at any size,
 *   stable between renders, and navigable by keyboard in DOM order). Upstream
 *   sits left of the focus record, downstream right, related below.
 * - Depth is unbounded: the layout handles any number of levels and the map
 *   grows as the user expands records. `MAP_NODE_CAP` bounds what is drawn at
 *   once, so a very large graph stays usable; the rest is reachable through the tree.
 */
import type { LinkGraph, LinkGraphEdge, LinkGraphFlow, LinkGraphNode } from "../api/artefactLinks";

/** A record's key in a graph: its type and id. */
export function nodeKey(type: string, id: string): string {
  return `${type}:${id}`;
}

/** An edge leaving a record, with the record at its far end. */
export interface TraceHop {
  edge: LinkGraphEdge;
  node: LinkGraphNode;
  /** Labels of the hidden records this hop was joined through ("Hide inactive"); empty for a direct link. */
  via: string[];
}

/**
 * The hops leaving one record in `graph`, sorted by relationship then label.
 *
 * @param graph A link graph read.
 * @param type The starting record's artefact type.
 * @param id The starting record's id.
 * @param flow When given, only hops in this direction (a branch keeps its direction).
 * @returns Hops whose far end is a node of the graph (an edge to a hidden record is never listed).
 */
export function hopsFrom(graph: LinkGraph, type: string, id: string, flow?: LinkGraphFlow): TraceHop[] {
  const nodes = new Map(graph.nodes.map((n) => [nodeKey(n.type, n.id), n]));
  const hops: TraceHop[] = [];
  for (const edge of graph.edges) {
    if (edge.from_type !== type || edge.from_id !== id) continue;
    if (flow !== undefined && edge.flow !== flow) continue;
    const node = nodes.get(nodeKey(edge.to_type, edge.to_id));
    if (node) hops.push({ edge, node, via: [] });
  }
  return hops.sort(
    (a, b) => (a.edge.phrase ?? "").localeCompare(b.edge.phrase ?? "") || a.node.label.localeCompare(b.node.label),
  );
}

/**
 * Adds `extra` to `base`: nodes and edges already present are kept, the root stays `base`'s,
 * and truncation / hidden counts accumulate as "any".
 */
export function mergeGraphs(base: LinkGraph, extra: LinkGraph): LinkGraph {
  const nodes = new Map(base.nodes.map((n) => [nodeKey(n.type, n.id), n]));
  for (const n of extra.nodes) if (!nodes.has(nodeKey(n.type, n.id))) nodes.set(nodeKey(n.type, n.id), n);
  const edges = new Map(base.edges.map((e) => [e.id, e]));
  for (const e of extra.edges) if (!edges.has(e.id)) edges.set(e.id, e);
  return {
    ...base,
    nodes: [...nodes.values()],
    edges: [...edges.values()],
    truncated: base.truncated || extra.truncated,
    hidden_count: Math.max(base.hidden_count, extra.hidden_count),
    unavailable_count: Math.max(base.unavailable_count, extra.unavailable_count),
  };
}

/**
 * Whether most of a record's typed links have no direction, so the Upstream and Downstream
 * views would be empty for want of configuration rather than for want of links.
 */
export function mostLinksUndirected(graph: LinkGraph): boolean {
  const typed = graph.edges.filter((e) => e.from_id === graph.root.id && e.link_type_id !== null);
  return typed.length >= 2 && typed.filter((e) => e.flow === "related").length * 2 > typed.length;
}

export const MAP_NODE_W = 168;
export const MAP_NODE_H = 70;
/** Space between a node's left edge (its direction stripe) and its text. */
export const MAP_NODE_PAD_X = 14;
export const MAP_GAP_X = 112;
export const MAP_GAP_Y = 18;
export const MAP_PAD = 16;
/** Height reserved at the top of a lane for its heading. */
export const MAP_HEADER_H = 26;
/** How far a lane's background extends beyond the records it holds, sideways. */
export const MAP_LANE_PAD = 8;
/** Room under the lowest record of a lane, for the "Show more" handle that hangs off a node's bottom edge. */
const LANE_BOTTOM_PAD = 16;
/** Vertical space between the main lanes and the related lane, where the focus record's related edges run. */
const LANE_GAP = 22;
/** Vertical room between the related rows, so their connecting lines have somewhere to run. */
const RELATED_ROW_GAP = 44;
/** Most records drawn at once. */
export const MAP_NODE_CAP = 60;
/** Related records per row, at least, so a record with only related links is not a single tall column. */
const MIN_RELATED_PER_ROW = 3;

export type MapBranch = LinkGraphFlow | "focus";

export interface PlacedNode {
  key: string;
  node: LinkGraphNode;
  branch: MapBranch;
  /** Hops from the focus record along the branch (0 for the focus). */
  level: number;
  x: number;
  y: number;
}

export interface PlacedEdge {
  id: string;
  /** The relationship as read from the starting end ("Implements"), or `null` for an untyped link. */
  phrase: string | null;
  fromKey: string;
  toKey: string;
  /** Which lane the far end sits in; upstream and downstream edges carry an arrowhead, related ones do not. */
  branch: MapBranch;
  /** Labels of the hidden records this edge was joined through; empty for a direct link. */
  via: string[];
  /** SVG path data. */
  path: string;
  labelX: number;
  labelY: number;
}

/** A background lane with its heading drawn at its top. */
export interface MapLane {
  flow: MapBranch;
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface MapLayout {
  nodes: PlacedNode[];
  edges: PlacedEdge[];
  width: number;
  height: number;
  /** Background lanes: Upstream | This record | Downstream, and the full-width Related band below them. */
  lanes: MapLane[];
  /** Records reachable but not drawn because of `MAP_NODE_CAP`; `null` when everything is drawn. */
  capped: { shown: number; total: number } | null;
  /** Hidden records the layout joined through whose own links have not been read yet (`options.expanded`),
   * as node keys: the caller reads them and lays out again. */
  unread: string[];
}

/** What the layout may leave out. */
export interface LayoutOptions {
  /** Records to skip over: not drawn, but what they link to (in the same direction) is joined to the record
   * in front of them. The focus record is never skipped. */
  hidden?: (node: LinkGraphNode) => boolean;
  /** Keys of records the user has opened. A skipped record outside it is reported in `unread`, and a record in the
   * related lane outside it shows no further links (related records can be numerous, so they open one hop at a time). */
  expanded?: ReadonlySet<string>;
}

interface Placement {
  branch: MapBranch;
  level: number;
}

/**
 * Lays `graph` out as layered columns around its root: upstream left, downstream right,
 * related below, any number of levels.
 *
 * @param graph The graph to draw (typically accumulated as the user expands records).
 * @param cap Most records to draw.
 * @param options Records to skip over (see {@link LayoutOptions}).
 * @returns Coordinates for every drawn record and edge, and the canvas size.
 */
export function layoutLinkMap(graph: LinkGraph, cap: number = MAP_NODE_CAP, options: LayoutOptions = {}): MapLayout {
  const nodesByKey = new Map(graph.nodes.map((n) => [nodeKey(n.type, n.id), n]));
  const rootKey = nodeKey(graph.root.type, graph.root.id);
  nodesByKey.set(rootKey, graph.root);
  const edgesFrom = new Map<string, LinkGraphEdge[]>();
  for (const edge of graph.edges) {
    const k = nodeKey(edge.from_type, edge.from_id);
    edgesFrom.set(k, [...(edgesFrom.get(k) ?? []), edge]);
  }

  // Breadth-first so the cap keeps the records nearest the focus; a branch only continues in its own direction.
  // A hidden record is skipped: its own edges (same direction) continue from the record in front of it.
  const isHidden = (key: string) => key !== rootKey && !!options.hidden?.(nodesByKey.get(key)!);
  const unread = new Set<string>();
  const candidates: Array<{ edge: LinkGraphEdge; fromKey: string; toKey: string; via: string[] }> = [];
  const placements = new Map<string, Placement>([[rootKey, { branch: "focus", level: 0 }]]);
  const queue = [rootKey];
  const labelFor = (key: string) => nodesByKey.get(key)?.label ?? "";
  for (let head = 0; head < queue.length; head++) {
    const fromKey = queue[head];
    const from = placements.get(fromKey)!;
    // Related records can be numerous, so they are drawn one hop deep until the user opens one.
    const holdBack = from.branch === "related" && options.expanded !== undefined && !options.expanded.has(fromKey);
    const follow = (edge: LinkGraphEdge, via: string[]) => {
      if (holdBack) return;
      if (from.branch !== "focus" && edge.flow !== from.branch) return;
      const toKey = nodeKey(edge.to_type, edge.to_id);
      if (!nodesByKey.has(toKey) || toKey === fromKey) return;
      if (isHidden(toKey)) {
        if (via.includes(toKey)) return;
        if (options.expanded && !options.expanded.has(toKey)) unread.add(toKey);
        // The branch is fixed by the first hop, so every continuation must keep its direction.
        const branchFlow = from.branch === "focus" ? edge.flow : from.branch;
        for (const next of edgesFrom.get(toKey) ?? []) {
          if (next.flow === branchFlow) follow(next, [...via, toKey]);
        }
        return;
      }
      candidates.push({ edge, fromKey, toKey, via });
      if (!placements.has(toKey)) {
        placements.set(toKey, { branch: from.branch === "focus" ? edge.flow : from.branch, level: from.level + 1 });
        queue.push(toKey);
      }
    };
    const outgoing = [...(edgesFrom.get(fromKey) ?? [])].sort((x, y) =>
      labelFor(nodeKey(x.to_type, x.to_id)).localeCompare(labelFor(nodeKey(y.to_type, y.to_id))));
    for (const edge of outgoing) follow(edge, []);
  }
  const total = placements.size;
  const shownKeys = new Set(queue.slice(0, cap));
  const shown = [...placements].filter(([k]) => shownKeys.has(k));

  const levelOf = (branch: MapBranch) =>
    Math.max(0, ...shown.filter(([, p]) => p.branch === branch).map(([, p]) => p.level));
  const maxUp = levelOf("upstream");
  const maxDown = levelOf("downstream");
  const mainCols = maxUp + maxDown + 1;
  const related = shown.filter(([, p]) => p.branch === "related");
  const relatedPerRow = related.length > 0 ? Math.max(mainCols, MIN_RELATED_PER_ROW) : 0;
  const widthCols = Math.max(mainCols, relatedPerRow);
  const colX = (col: number) => MAP_PAD + col * (MAP_NODE_W + MAP_GAP_X);
  const shiftCols = (widthCols - mainCols) / 2;

  const labelOf = (key: string) => nodesByKey.get(key)?.label ?? "";
  const byLabel = (a: [string, Placement], b: [string, Placement]) => labelOf(a[0]).localeCompare(labelOf(b[0]));

  // Main band: upstream | focus | downstream, each column centred on the tallest.
  const mainShown = shown.filter(([, p]) => p.branch !== "related");
  const columnOf = (p: Placement) =>
    p.branch === "upstream" ? maxUp - p.level : p.branch === "downstream" ? maxUp + p.level : maxUp;
  const columns = new Map<number, Array<[string, Placement]>>();
  for (const entry of mainShown) columns.set(columnOf(entry[1]), [...(columns.get(columnOf(entry[1])) ?? []), entry]);
  const tallest = Math.max(1, ...[...columns.values()].map((c) => c.length));
  const colHeight = (n: number) => n * MAP_NODE_H + (n - 1) * MAP_GAP_Y;
  const mainHeight = colHeight(tallest);
  const mainTop = MAP_PAD + MAP_HEADER_H;

  const placed = new Map<string, PlacedNode>();
  const put = (key: string, p: Placement, x: number, y: number) =>
    placed.set(key, { key, node: nodesByKey.get(key)!, branch: p.branch, level: p.level, x, y });
  for (const [col, entries] of columns) {
    entries.sort(byLabel);
    const top = mainTop + (mainHeight - colHeight(entries.length)) / 2;
    entries.forEach(([key, p], i) => put(key, p, colX(col + shiftCols), top + i * (MAP_NODE_H + MAP_GAP_Y)));
  }

  // Related band: one row group per level, wrapping at `relatedPerRow`, each row centred.
  const mainLaneBottom = mainTop + mainHeight + LANE_BOTTOM_PAD;
  let laneBottom = mainLaneBottom;
  let relatedLaneTop: number | null = null;
  if (related.length > 0) {
    relatedLaneTop = mainLaneBottom + LANE_GAP;
    let rowTop = relatedLaneTop + MAP_HEADER_H + 14;
    const levels = [...new Set(related.map(([, p]) => p.level))].sort((a, b) => a - b);
    for (const level of levels) {
      const entries = related.filter(([, p]) => p.level === level).sort(byLabel);
      for (let start = 0; start < entries.length; start += relatedPerRow) {
        const row = entries.slice(start, start + relatedPerRow);
        const offset = (widthCols - row.length) / 2;
        row.forEach(([key, p], i) => put(key, p, colX(offset + i), rowTop));
        laneBottom = rowTop + MAP_NODE_H + LANE_BOTTOM_PAD;
        rowTop += MAP_NODE_H + RELATED_ROW_GAP;
      }
    }
  }

  const edges = new Map<string, PlacedEdge>();
  for (const { edge, fromKey, toKey, via } of candidates) {
    const from = placed.get(fromKey);
    const to = placed.get(toKey);
    if (!from || !to || to.level <= from.level) continue;
    if (to.branch !== (from.branch === "focus" ? edge.flow : from.branch)) continue;
    // A joined edge starts at the record in front of the skipped ones, so it needs an id of its own.
    const id = via.length === 0 ? edge.id : `${fromKey}>${edge.id}`;
    edges.set(id, {
      id, phrase: edge.phrase, fromKey, toKey, branch: to.branch, via: via.map(labelFor), ...edgeGeometry(from, to),
    });
  }

  const lanes: MapLane[] = [];
  const mainLane = (flow: MapBranch, firstCol: number, cols: number) =>
    lanes.push({
      flow,
      x: colX(firstCol + shiftCols) - MAP_LANE_PAD,
      y: MAP_PAD,
      width: cols * MAP_NODE_W + (cols - 1) * MAP_GAP_X + 2 * MAP_LANE_PAD,
      height: mainLaneBottom - MAP_PAD,
    });
  if (maxUp > 0) mainLane("upstream", 0, maxUp);
  mainLane("focus", maxUp, 1);
  if (maxDown > 0) mainLane("downstream", maxUp + 1, maxDown);
  if (relatedLaneTop !== null) {
    lanes.push({
      flow: "related",
      x: colX(0) - MAP_LANE_PAD,
      y: relatedLaneTop,
      width: widthCols * MAP_NODE_W + (widthCols - 1) * MAP_GAP_X + 2 * MAP_LANE_PAD,
      height: laneBottom - relatedLaneTop,
    });
  }

  return {
    nodes: [...placed.values()],
    edges: [...edges.values()],
    width: colX(widthCols) - MAP_GAP_X + MAP_PAD,
    height: laneBottom + MAP_PAD,
    lanes,
    capped: total > shown.length ? { shown: shown.length, total } : null,
    unread: [...unread],
  };
}

/** Curve and label position between two placed records: sideways within the main band, downwards otherwise. */
function edgeGeometry(from: PlacedNode, to: PlacedNode): Pick<PlacedEdge, "path" | "labelX" | "labelY"> {
  const inMain = from.branch !== "related" && to.branch !== "related";
  if (inMain) {
    const toLeft = to.x < from.x;
    const x1 = toLeft ? from.x : from.x + MAP_NODE_W;
    const x2 = toLeft ? to.x + MAP_NODE_W : to.x;
    const y1 = from.y + MAP_NODE_H / 2;
    const y2 = to.y + MAP_NODE_H / 2;
    const xm = (x1 + x2) / 2;
    return { path: `M ${x1} ${y1} C ${xm} ${y1}, ${xm} ${y2}, ${x2} ${y2}`, labelX: xm, labelY: (y1 + y2) / 2 };
  }
  const x1 = from.x + MAP_NODE_W / 2;
  const x2 = to.x + MAP_NODE_W / 2;
  const y1 = from.y + MAP_NODE_H;
  const y2 = to.y;
  const ym = (y1 + y2) / 2;
  return { path: `M ${x1} ${y1} C ${x1} ${ym}, ${x2} ${ym}, ${x2} ${y2}`, labelX: (x1 + x2) / 2, labelY: ym };
}

const LABEL_CHARS = 23;
const LABEL_LINES = 2;

/** Splits `text` into at most `lines` lines of `width` characters, ending the last with an ellipsis if cut. */
export function wrapLabel(text: string, width = LABEL_CHARS, lines = LABEL_LINES): string[] {
  const words = text.split(/\s+/).filter(Boolean).flatMap((w) => {
    const parts: string[] = [];
    for (let i = 0; i < w.length; i += width) parts.push(w.slice(i, i + width));
    return parts;
  });
  const out: string[] = [];
  let current = "";
  for (const word of words) {
    if (current && `${current} ${word}`.length > width) {
      out.push(current);
      current = word;
    } else {
      current = current ? `${current} ${word}` : word;
    }
  }
  if (current) out.push(current);
  if (out.length <= lines) return out;
  const kept = out.slice(0, lines);
  const last = kept[lines - 1];
  kept[lines - 1] = `${last.length >= width ? last.slice(0, width - 1) : last}…`;
  return kept;
}
