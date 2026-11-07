/**
 * Module: api/placements
 *
 * Types and calls for placements: where a record of any type sits in the project's component/category tree
 * (`/projects/{id}/artefacts/{type}/{id}/placements`), and the list-filter parameters (`component_id`,
 * `category_id`) every record list sends.
 *
 * {@link RecordPlacementsApi} is injectable so stories stay off the network; it also reads the project's tree,
 * which the picker offers.
 */
import { api } from "./client";
import type { Category, Component } from "./types";

/** One place a record sits: a component and, optionally, a category under it. */
export interface PlacementPair {
  component_id: string;
  category_id: string | null;
}

/** A placement with the names to show. */
export interface Placement extends PlacementPair {
  component_name: string;
  category_name: string | null;
}

/** One record's placements and what its picker needs. */
export interface RecordPlacements {
  placements: Placement[];
  can_edit: boolean;
  /** The record keeps its own component and category (a requirement), so its page shows them itself. */
  managed_on_record: boolean;
}

/** The project's components and categories, in display order. */
export interface PlacementTree {
  components: Component[];
  categories: Category[];
}

/** The placements of one record; injectable for stories. */
export interface RecordPlacementsApi {
  get(projectId: string, type: string, id: string): Promise<RecordPlacements>;
  /** Makes the record sit in exactly these places. */
  set(projectId: string, type: string, id: string, places: PlacementPair[]): Promise<RecordPlacements>;
  /** The project's tree (a create form has no record yet). */
  tree(projectId: string): Promise<PlacementTree>;
  /** The places of a page of records of one type (`{record id: places}`; a record placed nowhere is absent). */
  page(projectId: string, type: string, ids: string[]): Promise<Record<string, Placement[]>>;
}

function recordBase(projectId: string, type: string, id: string): string {
  return `/api/v1/projects/${projectId}/artefacts/${encodeURIComponent(type)}/${id}/placements`;
}

/** The live implementation of {@link RecordPlacementsApi}. */
export const recordPlacementsApi: RecordPlacementsApi = {
  get: (projectId, type, id) => api.get<RecordPlacements>(recordBase(projectId, type, id)),
  set: (projectId, type, id, places) =>
    api.put<RecordPlacements>(recordBase(projectId, type, id), {
      placements: places.map((p) => ({ component_id: p.component_id, category_id: p.category_id })),
    }),
  page: async (projectId, type, ids) => {
    if (ids.length === 0) return {};
    const query = new URLSearchParams();
    for (const id of ids) query.append("id", id);
    const result = await api.get<{ placements: Record<string, Placement[]> }>(
      `/api/v1/projects/${projectId}/placements/${encodeURIComponent(type)}?${query}`,
    );
    return result.placements;
  },
  tree: async (projectId) => {
    const [components, categories] = await Promise.all([
      api.get<Component[]>(`/api/v1/projects/${projectId}/components`),
      api.get<Category[]>(`/api/v1/projects/${projectId}/categories`),
    ]);
    const byOrder = <T extends { sort_order: number; name: string }>(a: T, b: T) => a.sort_order - b.sort_order || a.name.localeCompare(b.name);
    return { components: [...components].sort(byOrder), categories: [...categories].sort(byOrder) };
  },
};

/** `Component` or `Component / Category`, the way one place reads everywhere. */
export function placementLabel(place: { component_name: string; category_name: string | null }): string {
  return place.category_name ? `${place.component_name} / ${place.category_name}` : place.component_name;
}

/** A record's places as one cell of text (`Hardware / Cooling, Software`), empty when it is placed nowhere. */
export function placementsText(places: Array<{ component_name: string; category_name: string | null }> | undefined): string {
  return (places ?? []).map(placementLabel).join(", ");
}

/** Whether two places are the same (a component alone differs from the same component with a category). */
export function samePlace(a: PlacementPair, b: PlacementPair): boolean {
  return a.component_id === b.component_id && (a.category_id ?? null) === (b.category_id ?? null);
}

/** What a list's filters carry for placements: the components and categories a record must sit in (any of them). */
export interface PlacementListFilters {
  component_ids?: string[];
  category_ids?: string[];
}

/** Adds the `component_id` and `category_id` parameters of `filters` to a list read. */
export function appendPlacementParams(params: URLSearchParams, filters: PlacementListFilters): void {
  for (const id of filters.component_ids ?? []) params.append("component_id", id);
  for (const id of filters.category_ids ?? []) params.append("category_id", id);
}
