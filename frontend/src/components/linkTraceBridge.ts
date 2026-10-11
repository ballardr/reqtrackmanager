/**
 * Module: components/linkTraceBridge
 *
 * The tree's side of "Hide inactive records": the hops leaving a record with the hidden
 * (superseded, archived, retired…) ones skipped and what they link to joined to the record
 * in front, so tracing DEC-002 past a superseded DEC-001 shows DEC-001's own sources
 * directly under DEC-002, marked "via DEC-001".
 *
 * Responsibilities: read a hidden record's own links (one read each, in parallel) and
 * continue through them in the same direction, ending at a record that stays visible.
 *
 * Design decisions:
 * - A hidden record is only ever read when the filter is on and it lies on the way, so
 *   switching it off costs nothing. A chain of hidden records is followed up to
 *   `MAX_BRIDGE_DEPTH`, which only guards against a pathological cycle (the path is also
 *   checked); a failed read fails the branch rather than silently dropping records.
 * - The direction is kept: a hop continues only through edges of the same `flow`.
 */
import type { ArtefactLinksApi, LinkGraph, LinkGraphFlow, LinkGraphNode } from "../api/artefactLinks";
import { isArtefactInactive } from "../modules/artefactPaths";
import { hopsFrom, nodeKey, type TraceHop } from "./linkTrace";

const MAX_BRIDGE_DEPTH = 12;

/** The "is this record skipped" test for the trace views: never skips anything when `hide` is off. */
export function inactiveFilter(hide: boolean): (node: LinkGraphNode) => boolean {
  return (node) => hide && isArtefactInactive(node.type, node.status, node.is_archived);
}

/**
 * @param api The (injectable) links API, used to read hidden records' links.
 * @param projectId The page's project.
 * @param graph A one-hop read around the starting record.
 * @param type The starting record's artefact type.
 * @param id The starting record's id.
 * @param flow The branch's direction.
 * @param isHidden Whether a record is skipped (always false when the filter is off).
 * @param path Keys of the records from the root down to and including the starting one, never repeated.
 * @returns The visible hops, hidden records joined through (with `via`), sorted by relationship then label.
 */
export async function bridgedHops(
  api: ArtefactLinksApi,
  projectId: string,
  graph: LinkGraph,
  type: string,
  id: string,
  flow: LinkGraphFlow,
  isHidden: (node: LinkGraphNode) => boolean,
  path: string[],
  depth = 0,
): Promise<TraceHop[]> {
  const hops = hopsFrom(graph, type, id, flow).filter((h) => !path.includes(nodeKey(h.node.type, h.node.id)));
  const direct = hops.filter((h) => !isHidden(h.node));
  const skipped = depth >= MAX_BRIDGE_DEPTH ? [] : hops.filter((h) => isHidden(h.node));
  const joined = await Promise.all(
    skipped.map(async (hop) => {
      const next = await api.graph(projectId, hop.node.type, hop.node.id);
      const inner = await bridgedHops(
        api, projectId, next, hop.node.type, hop.node.id, flow, isHidden, [...path, nodeKey(hop.node.type, hop.node.id)], depth + 1,
      );
      return inner.map((i) => ({ ...i, via: [hop.node.label, ...i.via] }));
    }),
  );
  const seen = new Set(direct.map((h) => nodeKey(h.node.type, h.node.id)));
  const out = [...direct];
  for (const hop of joined.flat()) {
    const key = nodeKey(hop.node.type, hop.node.id);
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(hop);
  }
  return out.sort(
    (a, b) => (a.edge.phrase ?? "").localeCompare(b.edge.phrase ?? "") || a.node.label.localeCompare(b.node.label),
  );
}
