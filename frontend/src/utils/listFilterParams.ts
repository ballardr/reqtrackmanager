/**
 * Module: utils/listFilterParams
 *
 * The two filters every project record list shares, written as the query parameters the list's request and its
 * Export (`ListActions`) both take: the tag, component and external reference filter (`tag`, `tag_mode`, `component_id`,
 * `category_id`, `external_system`, `external_key`) and the nested-project scope
 * (`project_scope`). A list builds the rest of its parameters itself and calls this for these; `filterString` writes
 * a simple list's whole filter set (an organisation panel's).
 */
import { appendReferenceParams } from "../api/externalReferences";
import { appendPlacementParams } from "../api/placements";
import type { SortState } from "../components/sortState";
import { addSortParams } from "../hooks/useListSort";
import type { ProjectScopeState } from "../hooks/useProjectScope";
import type { TagFilterState } from "../hooks/useTagFilter";

/**
 * Adds the tag filter and the project scope to `params`.
 *
 * @param params The list's parameters so far (changed and returned).
 * @param tagFilter The list's tag filter state (omit for a list without tags).
 * @param projectScope The list's nested-project scope state (omit for a list without related projects).
 * @returns `params`.
 */
export function addSharedListFilters(params: URLSearchParams, tagFilter?: TagFilterState, projectScope?: ProjectScopeState): URLSearchParams {
  appendPlacementParams(params, { component_ids: tagFilter?.components, category_ids: tagFilter?.categories });
  appendReferenceParams(params, { external_systems: tagFilter?.referenceSystems, external_key: tagFilter?.referenceKey });
  for (const tag of tagFilter?.tags ?? []) params.append("tag", tag);
  if (tagFilter && tagFilter.tags.length > 0) params.set("tag_mode", tagFilter.mode);
  if (projectScope?.widened) params.set("project_scope", projectScope.scope);
  return params;
}

/**
 * `filterString`'s result with the list's sort added, for a list whose Export takes the same order the screen shows.
 *
 * @param filters Filter name to its current value (see `filterString`).
 * @param sort The sort in force (`useListSort`).
 * @returns The query string without a leading `?`.
 */
export function filterStringWithSort(filters: Record<string, string | boolean | undefined>, sort: SortState): string {
  return addSortParams(new URLSearchParams(filterString(filters)), sort).toString();
}

/**
 * A list's own filters as the query string its Export takes: each named filter that has a value, nothing for an
 * empty one, and `true` for a ticked checkbox (the server reads `include_archived=true`).
 *
 * @param filters Filter name to its current value (`""`, `false` and `undefined` are left out).
 * @returns The query string without a leading `?`.
 */
export function filterString(filters: Record<string, string | boolean | undefined>): string {
  const params = new URLSearchParams();
  for (const [name, value] of Object.entries(filters)) {
    if (value === true) params.set(name, "true");
    else if (typeof value === "string" && value !== "") params.set(name, value);
  }
  return params.toString();
}
