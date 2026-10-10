/**
 * Module: testing/artefactLinksFixtures
 *
 * Builders and a fake `ArtefactLinksApi` for the Links panel's stories, so each
 * story states only the links and options it is about and needs no network.
 */
import { fn } from "storybook/test";

import type {
  ArtefactLinkCandidate, ArtefactLinksApi, ArtefactLinkTypeOption, LinkCandidateProject, LinkGraph, LinkGraphEdge,
  LinkGraphNode,
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
    truncated: false, hidden_count: 0, unavailable_count: 0, can_manage: true, ...overrides,
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

export function buildRelatedProject(overrides: Partial<LinkCandidateProject> = {}): LinkCandidateProject {
  return {
    id: "project-parent", name: "Programme", relation: "ancestor", distance: 1, label: "Parent: Programme",
    is_archived: false, ...overrides,
  };
}

/** A fake API whose calls are spies; `graph`, `options` and `candidates` default to small fixed answers. */
export function buildLinksApi(overrides: Partial<ArtefactLinksApi> = {}): ArtefactLinksApi {
  return {
    graph: fn(async () => buildGraph()),
    options: fn(async () => [buildOption()]),
    candidates: fn(async () => ({ items: [buildCandidate()], truncated: false })),
    projects: fn(async () => ({ items: [], truncated: false })),
    create: fn(async () => undefined),
    remove: fn(async () => undefined),
    ...overrides,
  };
}
