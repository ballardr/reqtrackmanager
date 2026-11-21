/**
 * Module: api/requirementAliases
 *
 * Types and calls for requirement aliases: a requirement placed in further components and categories, each with a
 * code of its own (`/projects/{id}/requirements/{id}/aliases`), and the setting that allows new ones
 * (`/projects/{id}/requirement-aliases`, `/orgs/{id}/requirement-aliases`).
 *
 * {@link RequirementAliasesApi} is injectable so stories stay off the network.
 */
import { api } from "./client";
import type { PlacementPair } from "./placements";
import type { Requirement } from "./types";

/** Whether new aliases may be added. */
export type AliasMode = "allowed" | "disabled";

/** The tier a project's effective value came from. */
export type AliasModeSource = "project" | "parent_project" | "organization";

/** A project's effective setting, its own value and how many aliases it holds. */
export interface AliasSettings {
  mode: AliasMode;
  source: AliasModeSource;
  /** The project's own value; `null` follows the nearest parent project that sets one, else the organisation. */
  own_mode: AliasMode | null;
  organization_mode: AliasMode;
  has_parent: boolean;
  alias_count: number;
}

/** Something not carried over to an independent copy, and why. */
export interface SkippedItem {
  kind: "link" | "comment" | "attachment";
  label: string;
  reason: string;
}

/** What making one alias independent did. */
export interface IndependentResult {
  requirement_id: string;
  unique_code: string;
  original_id: string;
  links_copied: number;
  comments_copied: number;
  attachments_copied: number;
  tags_copied: number;
  related_link_made: boolean;
  skipped: SkippedItem[];
}

/** The outcome of making several aliases independent: each made, each refused. */
export interface BulkIndependentResult {
  made: IndependentResult[];
  failed: Array<{ alias_id: string; unique_code: string; reason: string }>;
}

/** The calls the alias surfaces make; injectable for stories. */
export interface RequirementAliasesApi {
  settings(projectId: string): Promise<AliasSettings>;
  /** Sets the project's own value (`null` follows the parent project, else the organisation). */
  setProjectMode(projectId: string, mode: AliasMode | null): Promise<AliasSettings>;
  organizationMode(organizationId: string): Promise<AliasMode>;
  setOrganizationMode(organizationId: string, mode: AliasMode): Promise<AliasMode>;
  /** Makes the requirement sit in exactly its own place plus these. */
  setPlaces(projectId: string, requirementId: string, places: PlacementPair[]): Promise<Requirement>;
  retire(projectId: string, requirementId: string, aliasId: string): Promise<Requirement>;
  promote(projectId: string, requirementId: string, aliasId: string): Promise<Requirement>;
  makeIndependent(projectId: string, requirementId: string, aliasId: string, relatedLinkTypeId?: string): Promise<IndependentResult>;
  /** Makes the next batch of the project's aliases independent (up to 100); the caller repeats until none remain. */
  makeAllIndependent(projectId: string, relatedLinkTypeId?: string): Promise<BulkIndependentResult>;
}

function requirementBase(projectId: string, requirementId: string): string {
  return `/api/v1/projects/${projectId}/requirements/${requirementId}/aliases`;
}

/** The live implementation of {@link RequirementAliasesApi}. */
export const requirementAliasesApi: RequirementAliasesApi = {
  settings: (projectId) => api.get<AliasSettings>(`/api/v1/projects/${projectId}/requirement-aliases`),
  setProjectMode: (projectId, mode) => api.put<AliasSettings>(`/api/v1/projects/${projectId}/requirement-aliases`, { mode }),
  organizationMode: async (organizationId) =>
    (await api.get<{ mode: AliasMode }>(`/api/v1/orgs/${organizationId}/requirement-aliases`)).mode,
  setOrganizationMode: async (organizationId, mode) =>
    (await api.put<{ mode: AliasMode }>(`/api/v1/orgs/${organizationId}/requirement-aliases`, { mode })).mode,
  setPlaces: (projectId, requirementId, places) =>
    api.put<Requirement>(requirementBase(projectId, requirementId), {
      places: places.map((p) => ({ component_id: p.component_id, category_id: p.category_id })),
    }),
  retire: (projectId, requirementId, aliasId) => api.delete<Requirement>(`${requirementBase(projectId, requirementId)}/${aliasId}`),
  promote: (projectId, requirementId, aliasId) => api.post<Requirement>(`${requirementBase(projectId, requirementId)}/${aliasId}/promote`, {}),
  makeIndependent: (projectId, requirementId, aliasId, relatedLinkTypeId) =>
    api.post<IndependentResult>(`${requirementBase(projectId, requirementId)}/${aliasId}/make-independent`, {
      related_link_type_id: relatedLinkTypeId ?? null,
    }),
  makeAllIndependent: (projectId, relatedLinkTypeId) =>
    api.post<BulkIndependentResult>(`/api/v1/projects/${projectId}/requirement-aliases/make-independent`, {
      all_aliases: true, related_link_type_id: relatedLinkTypeId ?? null,
    }),
};
