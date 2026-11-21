/**
 * Module: api/structure
 *
 * Calls for editing a project's component and category tree (the Structure page, the first-component form of the
 * requirement create dialog): create, rename, reorder, move and delete, the prefix suggestion and the counts the
 * tree shows. {@link StructureApi} is injectable so stories stay off the network.
 *
 * The suggestion is the server's (`services.taxonomy.suggest_prefix`): the browser never works a prefix out itself,
 * so the screen, the API and MCP cannot disagree.
 */
import { api } from "./client";
import { recordPlacementsApi, type PlacementTree } from "./placements";
import type { Category, Component } from "./types";

/** What a component holds. */
export interface ComponentCounts {
  categories: number;
  /** Active requirements whose own component it is. */
  requirements: number;
}

/** The counts the tree shows beside each row. */
export interface StructureCounts {
  components: Record<string, ComponentCounts>;
  /** Active requirements whose own category it is, by category id. */
  categories: Record<string, number>;
}

/** The two levels of the tree. */
export type StructureKind = "component" | "category";

/** The name and prefix a node is saved with. */
export interface NodeValues {
  name: string;
  prefix: string;
}

/** What the prefix suggestion is asked about. */
export interface SuggestionRequest {
  kind: StructureKind;
  name: string;
  /** The component a new category goes under (a category only). */
  componentId?: string;
  /** The node being renamed, whose own prefix is not a collision. */
  ignore?: string;
}

/** The calls the Structure page makes; injectable for stories. */
export interface StructureApi {
  /** The components and categories in display order. */
  tree(projectId: string): Promise<PlacementTree>;
  counts(projectId: string): Promise<StructureCounts>;
  /** The server's suggested prefix; an empty string when the name has no letter or digit. */
  suggestPrefix(projectId: string, request: SuggestionRequest): Promise<string>;
  createComponent(projectId: string, values: NodeValues): Promise<Component>;
  createCategory(projectId: string, componentId: string, values: NodeValues): Promise<Category>;
  update(projectId: string, kind: StructureKind, id: string, values: NodeValues): Promise<void>;
  /** Moves a node one place up or down among its siblings. */
  move(projectId: string, kind: StructureKind, id: string, direction: "up" | "down"): Promise<void>;
  /** Moves a category under another component, last among its categories. */
  moveCategoryTo(projectId: string, categoryId: string, componentId: string): Promise<void>;
  /** Deletes a node; a category still in use answers 409 unless `reassignTo` names its replacement. */
  remove(projectId: string, kind: StructureKind, id: string, reassignTo?: string): Promise<void>;
}

const base = (projectId: string) => `/api/v1/projects/${projectId}`;
const segment = (kind: StructureKind) => (kind === "component" ? "components" : "categories");

/** The live implementation of {@link StructureApi}. */
export const structureApi: StructureApi = {
  tree: (projectId) => recordPlacementsApi.tree(projectId),
  counts: (projectId) => api.get<StructureCounts>(`${base(projectId)}/structure-counts`),
  suggestPrefix: async (projectId, { kind, name, componentId, ignore }) => {
    const query = new URLSearchParams({ name });
    if (componentId) query.set("component_id", componentId);
    if (ignore) query.set("ignore", ignore);
    const result = await api.get<{ prefix: string }>(`${base(projectId)}/${segment(kind)}/suggest-prefix?${query}`);
    return result.prefix;
  },
  createComponent: (projectId, values) => api.post<Component>(`${base(projectId)}/components`, values),
  createCategory: (projectId, componentId, values) =>
    api.post<Category>(`${base(projectId)}/categories`, { ...values, component_id: componentId }),
  update: async (projectId, kind, id, values) => {
    await api.patch(`${base(projectId)}/${segment(kind)}/${id}`, values);
  },
  move: async (projectId, kind, id, direction) => {
    await api.post(`${base(projectId)}/${segment(kind)}/${id}/move`, { direction });
  },
  moveCategoryTo: async (projectId, categoryId, componentId) => {
    await api.post(`${base(projectId)}/categories/${categoryId}/move-to`, { component_id: componentId });
  },
  remove: async (projectId, kind, id, reassignTo) => {
    await api.delete(`${base(projectId)}/${segment(kind)}/${id}${reassignTo ? `?reassign_to=${reassignTo}` : ""}`);
  },
};
