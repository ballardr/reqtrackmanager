/**
 * Module: utils/listFilterParams
 *
 * The two filters every project record list shares, written as the query parameters the list's request and its
 * Export (`ListActions`) both take: the tag filter (`tag`, `tag_mode`) and the nested-project scope
 * (`project_scope`). A list builds the rest of its parameters itself and calls this for these.
 */
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
  for (const tag of tagFilter?.tags ?? []) params.append("tag", tag);
  if (tagFilter?.active) params.set("tag_mode", tagFilter.mode);
  if (projectScope?.widened) params.set("project_scope", projectScope.scope);
  return params;
}
