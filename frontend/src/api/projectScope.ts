/**
 * Module: api/projectScope
 *
 * The list scope filter: a project's list widened to the parent and/or child projects the viewer
 * can open (`?project_scope=` on every project list), the scope choices a project offers, and the
 * label a row from another project carries.
 */
import { api } from "./client";

export type ProjectScope = "this" | "parents" | "children" | "both";

export const PROJECT_SCOPES: ProjectScope[] = ["this", "parents", "children", "both"];

/** What `GET /projects/{id}/scope-options` returns: which related projects the viewer can open. */
export interface ProjectScopeOptions {
  has_parents: boolean;
  has_children: boolean;
  truncated: boolean;
}

/** The fields a list row carries when it comes from a project other than the one being viewed. */
export interface ProjectScopedRow {
  from_project_id?: string | null;
  from_project_name?: string | null;
  from_project_code?: string | null;
}

/** Injectable calls so stories stay off the network. */
export interface ProjectScopeApi {
  options: (projectId: string) => Promise<ProjectScopeOptions>;
}

export const projectScopeApi: ProjectScopeApi = {
  options: (projectId) => api.get<ProjectScopeOptions>(`/api/v1/projects/${projectId}/scope-options`),
};

/** The scopes worth offering for a project: only those that add a project the viewer can open. */
export function availableScopes(options: ProjectScopeOptions | null): ProjectScope[] {
  if (!options) return ["this"];
  const scopes: ProjectScope[] = ["this"];
  if (options.has_parents) scopes.push("parents");
  if (options.has_children) scopes.push("children");
  if (options.has_parents && options.has_children) scopes.push("both");
  return scopes;
}

/**
 * The scope to apply when `wanted` is the stored choice: itself when this project offers it, else
 * the widest part of it that it does offer ("both" in a project with only children shows
 * children), else just this project.
 */
export function effectiveScope(wanted: ProjectScope, available: ProjectScope[]): ProjectScope {
  if (available.includes(wanted)) return wanted;
  if (wanted === "both") return (["children", "parents"] as const).find((scope) => available.includes(scope)) ?? "this";
  return "this";
}

/** Reads a stored value back as a scope, ignoring anything a stale or hand-edited preference holds. */
export function parseProjectScope(value: unknown): ProjectScope | null {
  return typeof value === "string" && (PROJECT_SCOPES as string[]).includes(value) ? (value as ProjectScope) : null;
}

/** `project_scope=parents`, or an empty string for the plain single-project list. */
export function projectScopeQuery(scope: ProjectScope): string {
  return scope === "this" ? "" : `project_scope=${scope}`;
}

/** The project a row's own page lives in: the project it came from, else the one being viewed. */
export function rowProjectId(row: ProjectScopedRow, viewedProjectId: string): string {
  return row.from_project_id ?? viewedProjectId;
}

/** What a list's filters carry for the project scope: sent as `project_scope` when widened. */
export interface ScopeListFilters {
  project_scope?: ProjectScope;
}

/** Adds the `project_scope` parameter of `filters` to a list read (nothing for the single-project list). */
export function appendScopeParam(params: URLSearchParams, filters: ScopeListFilters): void {
  if (filters.project_scope && filters.project_scope !== "this") params.set("project_scope", filters.project_scope);
}
