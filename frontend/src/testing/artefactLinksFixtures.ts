/**
 * Module: testing/artefactLinksFixtures
 *
 * Builders and a fake `ArtefactLinksApi` for the Links panel's stories, so each
 * story states only the links and options it is about and needs no network.
 */
import { fn } from "storybook/test";

import type {
  ArtefactLinkBrowseStep, ArtefactLinkCandidate, ArtefactLinksApi, ArtefactLinkTypeOption, LinkCandidateProject,
  LinkFlow, LinkGraph, LinkGraphEdge, LinkGraphNode,
} from "../api/artefactLinks";

export const LINKS_PROJECT_ID = "project-1";
export const LINKS_ARTEFACT_ID = "artefact-1";

export function buildGraphNode(overrides: Partial<LinkGraphNode> = {}): LinkGraphNode {
  return {
    type: "decision", id: "dec-1", type_label: "Decision", label: "DEC-001 Use Postgres", status: "draft",
    is_archived: false, depth: 1, project_id: LINKS_PROJECT_ID, project_name: "Alpha", ...overrides,
  };
}

export function buildGraphEdge(node: LinkGraphNode, overrides: Partial<LinkGraphEdge> = {}): LinkGraphEdge {
  return {
    id: `link-${node.id}`, from_type: "requirement", from_id: LINKS_ARTEFACT_ID, to_type: node.type, to_id: node.id,
    link_type_id: "lt-1", phrase: "Is implemented by", flow: "downstream", outgoing: false, cross_project: false,
    nesting_permitted: true, dedicated: false, ...overrides,
  };
}

export function buildGraph(
  rows: Array<[LinkGraphNode, Partial<LinkGraphEdge>?]> = [], overrides: Partial<LinkGraph> = {},
): LinkGraph {
  return {
    root: buildGraphNode({ type: "requirement", id: LINKS_ARTEFACT_ID, type_label: "Requirement", label: "REQ-001 Root", depth: 0 }),
    nodes: rows.map(([node]) => node),
    edges: rows.map(([node, edge]) => buildGraphEdge(node, edge)),
    truncated: false, hidden_count: 0, unavailable_count: 0, can_link: true, can_propose: true, ...overrides,
  };
}

export function buildOption(overrides: Partial<ArtefactLinkTypeOption> = {}): ArtefactLinkTypeOption {
  return {
    link_type_id: "lt-related", forward_name: "Related to", reverse_name: "Related to", flow: "none",
    nesting_scope: "ancestor_either_way", direction: "outgoing", phrase: "Related to",
    other_types: [{ type: "decision", label: "Decision" }, { type: "pain_point", label: "Pain Point" }],
    ...overrides,
  };
}

export function buildCandidate(overrides: Partial<ArtefactLinkCandidate> = {}): ArtefactLinkCandidate {
  return {
    type: "decision", id: "dec-2", type_label: "Decision", label: "DEC-002 Use Redis", status: "draft",
    project_id: LINKS_PROJECT_ID, ...overrides,
  };
}

/** One browse level of a record type's scoped finder, with the options the earlier choices leave. */
export function buildBrowseStep(overrides: Partial<ArtefactLinkBrowseStep> = {}): ArtefactLinkBrowseStep {
  return {
    key: "status", label: "Status", options: [{ id: "draft", label: "Draft" }, { id: "active", label: "Active" }],
    truncated: false, ...overrides,
  };
}

export function buildRelatedProject(overrides: Partial<LinkCandidateProject> = {}): LinkCandidateProject {
  return {
    id: "project-parent", name: "Programme", relation: "ancestor", distance: 1, label: "Parent: Programme",
    is_archived: false, ...overrides,
  };
}

/** A fake API whose calls are spies; `graph`, `options` and `candidates` default to small fixed answers
 * and `browse` to "no levels" (a record type with nothing to narrow by). */
export function buildLinksApi(overrides: Partial<ArtefactLinksApi> = {}): ArtefactLinksApi {
  return {
    graph: fn(async () => buildGraph()),
    options: fn(async () => [buildOption()]),
    candidates: fn(async () => ({ items: [buildCandidate()], truncated: false })),
    browse: fn(async () => null),
    projects: fn(async () => ({ items: [], truncated: false })),
    create: fn(async () => undefined),
    remove: fn(async () => undefined),
    ...overrides,
  };
}

/** A record in a {@link buildTraceApi} universe. */
export interface TraceRecord {
  id: string;
  label: string;
  type?: string;
  typeLabel?: string;
  status?: string | null;
  projectId?: string | null;
  projectName?: string | null;
  isArchived?: boolean;
}

/** A stored link in a {@link buildTraceApi} universe: `target` is `forward` of `source`, `source` is `reverse` of `target`. */
export interface TraceLink {
  source: string;
  target: string;
  forward: string;
  reverse: string;
  flow: LinkFlow;
}

/**
 * A fake API over a small fixed universe of records and links whose `graph` answers like the
 * server's: breadth-first out to `depth` hops, each edge oriented away from the record it was
 * reached from with its `flow` resolved from the stored link's. The rest of the API is the
 * usual spies. Only `graph` is exercised by the trace views.
 */
export function buildTraceApi(records: TraceRecord[], links: TraceLink[]): ArtefactLinksApi {
  const byId = new Map(records.map((r) => [r.id, r]));
  const nodeOf = (id: string, depth: number): LinkGraphNode => {
    const r = byId.get(id)!;
    return {
      type: r.type ?? "requirement", id, type_label: r.typeLabel ?? "Requirement", label: r.label,
      status: r.status ?? null, is_archived: r.isArchived ?? false, depth,
      project_id: r.projectId === undefined ? LINKS_PROJECT_ID : r.projectId,
      project_name: r.projectName === undefined ? "Alpha" : r.projectName,
    };
  };
  const flowOf = (flow: LinkFlow, outgoing: boolean): LinkGraphEdge["flow"] => {
    if (flow === "none") return "related";
    return (flow === "forward_is_upstream") === outgoing ? "upstream" : "downstream";
  };
  return buildLinksApi({
    graph: fn(async (_project: string, _type: string, id: string, depth = 1) => {
      const nodes = new Map<string, LinkGraphNode>([[id, nodeOf(id, 0)]]);
      const edges = new Map<string, LinkGraphEdge>();
      let frontier = [id];
      for (let level = 1; level <= depth && frontier.length > 0; level++) {
        const next: string[] = [];
        links.forEach((link, index) => {
          for (const [from, to, outgoing] of [[link.source, link.target, true], [link.target, link.source, false]] as const) {
            if (!frontier.includes(from)) continue;
            const edgeId = `trace-link-${index}`;
            if (edges.has(edgeId)) continue;
            if (!nodes.has(to)) {
              nodes.set(to, nodeOf(to, level));
              next.push(to);
            }
            const target = byId.get(to)!;
            edges.set(edgeId, {
              id: edgeId, from_type: byId.get(from)!.type ?? "requirement", from_id: from, to_type: target.type ?? "requirement",
              to_id: to, link_type_id: "lt-trace", phrase: outgoing ? link.forward : link.reverse,
              flow: flowOf(link.flow, outgoing), outgoing, cross_project: false, nesting_permitted: true, dedicated: false,
            });
          }
        });
        frontier = next;
      }
      const root = nodes.get(id)!;
      return {
        root, nodes: [...nodes.values()].filter((n) => n.id !== id), edges: [...edges.values()], truncated: false,
        hidden_count: 0, unavailable_count: 0, can_link: true, can_propose: true,
      };
    }),
  });
}
