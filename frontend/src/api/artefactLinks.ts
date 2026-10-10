/**
 * Module: api/artefactLinks
 *
 * Types and calls for the generic artefact link endpoints
 * (`/projects/{id}/artefacts/{type}/{id}/...`) behind the shared Links panel:
 * the link graph around one artefact, the link types usable from it, the
 * records a link could point at, the projects a link may reach (itself, its
 * ancestors and descendants), and creating or removing a link.
 *
 * Every function takes the page artefact's project; the server authorises each
 * end in its own project, so nothing here decides what a user may see.
 */
import { api } from "./client";

export type LinkFlow = "none" | "forward_is_upstream" | "forward_is_downstream";
export type LinkGraphFlow = "upstream" | "downstream" | "related";
export type LinkOrientation = "outgoing" | "incoming";

export interface LinkGraphNode {
  type: string;
  id: string;
  type_label: string;
  label: string;
  status: string | null;
  is_archived: boolean;
  depth: number;
  project_id: string | null;
  project_name: string | null;
}

export interface LinkGraphEdge {
  id: string;
  from_type: string;
  from_id: string;
  to_type: string;
  to_id: string;
  link_type_id: string | null;
  phrase: string | null;
  flow: LinkGraphFlow;
  outgoing: boolean;
  cross_project: boolean;
  nesting_permitted: boolean;
  dedicated: boolean;
}

export interface LinkGraph {
  root: LinkGraphNode;
  nodes: LinkGraphNode[];
  edges: LinkGraphEdge[];
  truncated: boolean;
  hidden_count: number;
  unavailable_count: number;
  can_manage: boolean;
}

export interface ArtefactTypeRef {
  type: string;
  label: string;
}

export interface ArtefactLinkTypeOption {
  link_type_id: string;
  forward_name: string;
  reverse_name: string;
  flow: LinkFlow;
  nesting_scope: string;
  direction: LinkOrientation;
  phrase: string;
  other_types: ArtefactTypeRef[];
}

export interface ArtefactLinkCandidate {
  type: string;
  id: string;
  type_label: string;
  label: string;
  status: string | null;
  project_id: string | null;
}

export interface ArtefactLinkCandidates {
  items: ArtefactLinkCandidate[];
  truncated: boolean;
}

export interface LinkCandidateProject {
  id: string;
  name: string;
  relation: "same" | "ancestor" | "descendant";
  distance: number;
  label: string;
  is_archived: boolean;
}

export interface LinkCandidateProjects {
  items: LinkCandidateProject[];
  truncated: boolean;
}

export interface NewArtefactLink {
  link_type_id: string;
  direction: LinkOrientation;
  other_type: string;
  other_id: string;
  other_project_id?: string;
}

/** The calls the Links panel makes; injectable so stories need no network. */
export interface ArtefactLinksApi {
  graph(projectId: string, type: string, id: string): Promise<LinkGraph>;
  options(
    projectId: string, type: string, id: string, params?: { otherType?: string; otherProjectId?: string },
  ): Promise<ArtefactLinkTypeOption[]>;
  candidates(
    projectId: string, type: string, id: string,
    params: { otherType: string; otherProjectId?: string; query?: string },
  ): Promise<ArtefactLinkCandidates>;
  projects(projectId: string): Promise<LinkCandidateProjects>;
  create(projectId: string, type: string, id: string, link: NewArtefactLink): Promise<void>;
  remove(projectId: string, type: string, id: string, linkId: string): Promise<void>;
}

function base(projectId: string, type: string, id: string): string {
  return `/api/v1/projects/${projectId}/artefacts/${encodeURIComponent(type)}/${id}`;
}

function query(params: Record<string, string | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) if (value) search.set(key, value);
  const text = search.toString();
  return text ? `?${text}` : "";
}

/** The live implementation of {@link ArtefactLinksApi}. */
export const artefactLinksApi: ArtefactLinksApi = {
  graph: (projectId, type, id) =>
    api.get<LinkGraph>(`${base(projectId, type, id)}/link-graph?depth=1&direction=both`),
  options: (projectId, type, id, params = {}) =>
    api.get<ArtefactLinkTypeOption[]>(
      `${base(projectId, type, id)}/link-types${query({ other_type: params.otherType, other_project_id: params.otherProjectId })}`,
    ),
  candidates: (projectId, type, id, params) =>
    api.get<ArtefactLinkCandidates>(
      `${base(projectId, type, id)}/link-candidates${query({
        other_type: params.otherType, other_project_id: params.otherProjectId, q: params.query,
      })}`,
    ),
  projects: (projectId) => api.get<LinkCandidateProjects>(`/api/v1/projects/${projectId}/link-candidate-projects`),
  create: async (projectId, type, id, link) => {
    await api.post(`${base(projectId, type, id)}/links`, link);
  },
  remove: async (projectId, type, id, linkId) => {
    await api.delete(`${base(projectId, type, id)}/links/${linkId}`);
  },
};
