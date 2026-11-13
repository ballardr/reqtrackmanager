/**
 * Module: modules/architecture/diagramResolver
 *
 * The browser's copy of the rule that turns the model's connections into the lines a diagram draws, so the editor can
 * redraw lines at once while a layout is being edited (a box added, a view switch flipped) without a round trip. It is a
 * line-for-line port of `backend/app/modules/architecture/diagram_resolver.py`; the server's copy stays the authority for
 * the first load, the SVG and documents.
 *
 * Responsibilities:
 * - Apply, in this order: (1) hide the elements and connections of switched-off view switches; (2) join across hidden
 *   elements (a hidden transit element is bridged); (3) roll every end up to its nearest placed ancestor; (4) merge
 *   parallel lines when connection detail is off.
 * - Report which connections each line stands for, which hidden elements a bridged line passes through, and which
 *   connections are wholly inside a placed element.
 * - Join a scoped diagram's boundary boxes: a connection that realises an outer connection is drawn to that connection's
 *   box (`ResolverBoundary`), and `outerSide` says which end of a connection lies inside a scope, which is what makes it
 *   an outer connection.
 *
 * Design decisions:
 * - **Pure, and kept equal to the server's by shared cases.** `diagramResolverCases.json` holds scenarios whose expected
 *   results the server's resolver produced; `DiagramResolver.stories.tsx` runs this port over them, and a backend test
 *   fails when the file is out of date with the server. A change to the rule is made in both places.
 * - **Ordering matches the server's:** lines sort by their ends and first connection as plain text, compared by code
 *   unit like the server's string compare, never by locale.
 * - **Nothing here decides visibility.** The model the inputs come from is already limited to what the viewer may read.
 *
 * Dependencies: none.
 */

/** The longest chain of hidden elements a bridged line passes through, and the deepest ancestor walk. */
export const MAX_HOPS = 12;

const WALK_CAP = 13;

/** A connection as the resolver sees it. */
export interface ResolverConnection {
  id: string;
  sourceId: string;
  targetId: string;
  /** True for a one-way connection (source to target); false is two-way. */
  directional: boolean;
}

/**
 * A boundary box of a scoped diagram, as the resolver sees it. A realising connection meets the box at its end that is
 * `elementId` (the outer connection's scope-side element, when that is not itself placed) or that lies inside `outsideId`
 * (the element outside the scope); that end is drawn at the box.
 */
export interface ResolverBoundary {
  /** The box's own id; lines to it use this as their end. */
  id: string;
  elementId: string;
  outsideId: string;
  /** The connections that realise the outer connection. */
  connectionIds: readonly string[];
}

/** One line to draw between two placed elements. */
export interface ResolvedLine {
  sourceId: string;
  targetId: string;
  twoWay: boolean;
  connectionIds: string[];
  rolledUp: boolean;
  bridged: boolean;
  /** Every connection behind the line is rolled up or bridged (drawn dashed). */
  indirect: boolean;
  hops: string[];
}

/** What `resolveLines` decides. */
export interface Resolution {
  /** The placed elements that are switched off. */
  hiddenPlaced: Set<string>;
  lines: ResolvedLine[];
  /** `{placed element id: connection ids wholly inside it}`. */
  internal: Map<string, string[]>;
}

/** A line before roll-up and merging. */
interface Candidate {
  a: string;
  b: string;
  connectionIds: string[];
  oneWay: boolean;
  bridged: boolean;
  hops: string[];
}

type Arc = [string, ResolverConnection];
type Rolled = [string, string, Candidate, boolean];

/** Compares two texts by code unit, as the server's string compare does. */
function compareText(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

const unique = (items: string[]): string[] => [...new Set(items)];

/** The element and its ancestors, nearest first (cycle-safe). */
function chain(parents: ReadonlyMap<string, string | null>, elementId: string): string[] {
  const seen = new Set<string>();
  const order: string[] = [];
  let current: string | null | undefined = elementId;
  while (current != null && !seen.has(current) && seen.size < WALK_CAP) {
    seen.add(current);
    order.push(current);
    current = parents.get(current);
  }
  return order;
}

/**
 * The end of a connection that lies inside `scopeId`, when the other end lies outside it; otherwise null. A connection with
 * exactly one end in the scope's subtree (the scope itself or a descendant) is an *outer* connection of the scope.
 */
export function outerSide(
  scopeId: string, parents: ReadonlyMap<string, string | null>, sourceId: string, targetId: string,
): string | null {
  const sourceIn = chain(parents, sourceId).includes(scopeId);
  const targetIn = chain(parents, targetId).includes(scopeId);
  if (sourceIn === targetIn) return null;
  return sourceIn ? sourceId : targetId;
}

/**
 * The connections with the end that meets a boundary swapped for its box: one connection per box a realising connection
 * realises, the original dropped; a connection whose two ends would both meet the box, and every other connection, is
 * unchanged.
 */
function attachBoundaries(
  live: readonly ResolverConnection[], boundaries: readonly ResolverBoundary[], placed: ReadonlySet<string>,
  parents: ReadonlyMap<string, string | null>,
): ResolverConnection[] {
  const byConnection = new Map<string, ResolverBoundary[]>();
  for (const b of boundaries) {
    for (const id of b.connectionIds) byConnection.set(id, [...(byConnection.get(id) ?? []), b]);
  }
  const meets = (b: ResolverBoundary, end: string) =>
    (end === b.elementId && !placed.has(end)) || chain(parents, end).includes(b.outsideId);
  const out: ResolverConnection[] = [];
  for (const c of live) {
    const swaps = (byConnection.get(c.id) ?? [])
      .map((b) => ({ b, source: meets(b, c.sourceId), target: meets(b, c.targetId) }))
      .filter((s) => s.source !== s.target);
    if (swaps.length === 0) {
      out.push(c);
      continue;
    }
    for (const { b, source } of swaps) {
      out.push({ ...c, sourceId: source ? b.id : c.sourceId, targetId: source ? c.targetId : b.id });
    }
  }
  return out;
}

/**
 * Resolves the lines of a diagram.
 *
 * @param input.placed The elements placed on the diagram.
 * @param input.parents `{element id: parent id}` for every element that appears as a connection end or placement, and every
 *   ancestor of one (a root maps to null).
 * @param input.connections The connections to consider, in a stable order.
 * @param input.hiddenElements The elements switched off (their descendants are hidden with them).
 * @param input.hiddenConnections The connections switched off.
 * @param input.mergeParallel True when connection detail is off: every line between the same two placed elements becomes one.
 * @param input.boundaries The boundary boxes of a scoped diagram; a realising connection is drawn to its box.
 * @returns The lines, the hidden placed elements and the internal connections.
 */
export function resolveLines(input: {
  placed: Iterable<string>;
  parents: ReadonlyMap<string, string | null>;
  connections: readonly ResolverConnection[];
  hiddenElements?: Iterable<string>;
  hiddenConnections?: Iterable<string>;
  mergeParallel: boolean;
  boundaries?: readonly ResolverBoundary[];
}): Resolution {
  const { parents, connections, mergeParallel } = input;
  const switchedOff = new Set(input.hiddenElements ?? []);
  const hiddenCache = new Map<string, boolean>();
  const isHidden = (elementId: string): boolean => {
    let value = hiddenCache.get(elementId);
    if (value === undefined) {
      value = switchedOff.size > 0 && chain(parents, elementId).some((a) => switchedOff.has(a));
      hiddenCache.set(elementId, value);
    }
    return value;
  };

  const boundaries = input.boundaries ?? [];
  const placedSet = new Set([...input.placed, ...boundaries.map((b) => b.id)]);
  const anchors = new Map<string, string | null>();
  const anchor = (elementId: string): string | null => {
    let value = anchors.get(elementId);
    if (value === undefined) {
      value = chain(parents, elementId).find((a) => placedSet.has(a)) ?? null;
      anchors.set(elementId, value);
    }
    return value;
  };

  const switchedOffConnections = new Set(input.hiddenConnections ?? []);
  let live = connections.filter((c) => !switchedOffConnections.has(c.id));
  if (boundaries.length > 0) live = attachBoundaries(live, boundaries, placedSet, parents);
  const candidates: Candidate[] = [];
  const arcs = new Map<string, Arc[]>();
  const addArc = (from: string, to: string, c: ResolverConnection) => {
    const list = arcs.get(from);
    if (list) list.push([to, c]);
    else arcs.set(from, [[to, c]]);
  };
  for (const c of live) {
    if (!isHidden(c.sourceId) && !isHidden(c.targetId)) {
      candidates.push({ a: c.sourceId, b: c.targetId, connectionIds: [c.id], oneWay: c.directional, bridged: false, hops: [] });
      continue;
    }
    addArc(c.sourceId, c.targetId, c);
    if (!c.directional) addArc(c.targetId, c.sourceId, c);
  }
  if (arcs.size > 0) candidates.push(...bridge(arcs, isHidden, live));

  const internal = new Map<string, string[]>();
  const rolled: Rolled[] = [];
  for (const candidate of candidates) {
    const pa = anchor(candidate.a);
    const pb = anchor(candidate.b);
    if (pa === null || pb === null) continue;
    if (pa === pb) {
      internal.set(pa, [...(internal.get(pa) ?? []), ...candidate.connectionIds]);
      continue;
    }
    rolled.push([pa, pb, candidate, pa !== candidate.a || pb !== candidate.b]);
  }

  const lines = merge(rolled, mergeParallel).sort(
    (x, y) =>
      compareText(x.sourceId, y.sourceId) || compareText(x.targetId, y.targetId) || compareText(x.connectionIds[0], y.connectionIds[0]),
  );
  return {
    hiddenPlaced: new Set([...placedSet].filter(isHidden)),
    lines,
    internal: new Map([...internal].map(([k, v]) => [k, unique(v)])),
  };
}

/**
 * The lines that join a visible element to another through a chain of hidden ones.
 *
 * Starting from each visible element with an arc into a hidden one, a breadth-first walk through hidden elements (to
 * `MAX_HOPS`) keeps the shortest path to each visible element reached. A pair reached in both directions is one two-way
 * candidate, emitted once.
 */
function bridge(arcs: ReadonlyMap<string, Arc[]>, isHidden: (id: string) => boolean, live: readonly ResolverConnection[]): Candidate[] {
  const starts = unique(
    live.flatMap((c) => [c.sourceId, c.targetId]).filter((end) => !isHidden(end) && arcs.has(end)),
  ).sort(compareText);
  const found = new Map<string, Candidate>();
  const keyOf = (a: string, b: string) => `${a}|${b}`;
  for (const start of starts) {
    const queue: [string, string[], string[]][] = [];
    const reached = new Set<string>();
    for (const [next, c] of arcs.get(start) ?? []) {
      if (isHidden(next) && !reached.has(next)) {
        reached.add(next);
        queue.push([next, [next], [c.id]]);
      }
    }
    const done = new Set<string>();
    for (let at = 0; at < queue.length; at += 1) {
      const [node, hops, ids] = queue[at];
      for (const [next, c] of arcs.get(node) ?? []) {
        if (isHidden(next)) {
          if (!reached.has(next) && hops.length < MAX_HOPS) {
            reached.add(next);
            queue.push([next, [...hops, next], [...ids, c.id]]);
          }
        } else if (next !== start && !done.has(next)) {
          done.add(next);
          found.set(keyOf(start, next), { a: start, b: next, connectionIds: [...ids, c.id], oneWay: true, bridged: true, hops: [...hops] });
        }
      }
    }
  }
  const merged: Candidate[] = [];
  const seen = new Set<string>();
  const ordered = [...found.values()].sort((x, y) => compareText(x.a, y.a) || compareText(x.b, y.b));
  for (const candidate of ordered) {
    const key = keyOf(candidate.a, candidate.b);
    if (seen.has(key)) continue;
    seen.add(key);
    const reverse = found.get(keyOf(candidate.b, candidate.a));
    if (reverse) {
      seen.add(keyOf(candidate.b, candidate.a));
      candidate.oneWay = false;
      candidate.connectionIds = unique([...candidate.connectionIds, ...reverse.connectionIds]);
      candidate.hops = unique([...candidate.hops, ...reverse.hops]);
    }
    merged.push(candidate);
  }
  return merged;
}

/**
 * Groups rolled candidates into lines: all between one unordered pair when `mergeParallel`, otherwise only the indirect
 * ones (rolled up or bridged) while a direct connection keeps its own line.
 */
function merge(rolled: readonly Rolled[], mergeParallel: boolean): ResolvedLine[] {
  const groups = new Map<string, Rolled[]>();
  for (const member of rolled) {
    const [pa, pb, candidate, rolledUp] = member;
    const pair = [pa, pb].sort(compareText).join("|");
    const key = mergeParallel
      ? `pair:${pair}`
      : rolledUp || candidate.bridged
        ? `indirect:${pair}`
        : `direct:${candidate.connectionIds[0]}|${pa}|${pb}`;
    const list = groups.get(key);
    if (list) list.push(member);
    else groups.set(key, [member]);
  }
  const lines: ResolvedLine[] = [];
  for (const members of groups.values()) {
    const [firstA, firstB] = members[0];
    // The line is drawn from the first member's orientation; members drawn the other way make it two-way.
    const agree = members.every((m) => m[0] === firstA && m[1] === firstB);
    lines.push({
      sourceId: firstA,
      targetId: firstB,
      twoWay: members.some((m) => !m[2].oneWay) || !agree,
      connectionIds: unique(members.flatMap((m) => m[2].connectionIds)),
      rolledUp: members.some((m) => m[3]),
      bridged: members.some((m) => m[2].bridged),
      indirect: members.every((m) => m[3] || m[2].bridged),
      hops: unique(members.flatMap((m) => m[2].hops)),
    });
  }
  return lines;
}
