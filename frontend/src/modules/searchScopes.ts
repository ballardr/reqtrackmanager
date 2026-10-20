/**
 * Module: modules/searchScopes
 *
 * The scopes of the global search: the built-in "This project" and "All projects" plus whatever
 * installed modules register (`TierAModuleDefinition.searchScopes`). Core names no module's scope: it
 * asks each registered `match` which apply to the page the viewer is on and offers those.
 *
 * A scope is carried as a string, the same one the API takes: `project` (with the project id kept
 * beside it), `all`, or `<module key>:<scope key>:<ref id>`.
 *
 * The default scope is the narrowest that matches where the viewer is when they start typing, by
 * `narrowness` (built-ins: All projects 0, This project 100, a module's own default 200).
 */
import { installedModules } from "./registry";

export const ALL_SCOPE = "all";
export const PROJECT_SCOPE = "project";
const ALL_NARROWNESS = 0;
const PROJECT_NARROWNESS = 100;
const MODULE_DEFAULT_NARROWNESS = 200;

/** One scope the viewer could search in. */
export interface SearchScopeOption {
  /** The API scope string. */
  value: string;
  label: string;
  narrowness: number;
  /** For `project` only: the project it means. */
  projectId?: string;
}

/** Labels the built-in scopes use (injected so this file needs no string table). */
export interface BuiltInScopeLabels {
  project: string;
  all: string;
}

/** The project id in a `/projects/<id>/…` path, or `null`. */
export function projectIdFromPath(pathname: string): string | null {
  return /^\/projects\/([^/]+)/.exec(pathname)?.[1] ?? null;
}

/**
 * Every scope that matches where the viewer is: the built-ins that apply and each module scope whose `match`
 * accepts the path, narrowest first.
 *
 * @param pathname The current location's path.
 * @param labels Display names for the built-in scopes.
 */
export function scopesForPath(pathname: string, labels: BuiltInScopeLabels): SearchScopeOption[] {
  const options: SearchScopeOption[] = [{ value: ALL_SCOPE, label: labels.all, narrowness: ALL_NARROWNESS }];
  const projectId = projectIdFromPath(pathname);
  if (projectId) options.push({ value: PROJECT_SCOPE, label: labels.project, narrowness: PROJECT_NARROWNESS, projectId });
  for (const module of installedModules) {
    for (const scope of module.searchScopes ?? []) {
      const ref = scope.match(pathname);
      if (ref) {
        options.push({
          value: `${module.key}:${scope.key}:${ref}`, label: scope.label, narrowness: scope.narrowness ?? MODULE_DEFAULT_NARROWNESS,
        });
      }
    }
  }
  return options.sort((a, b) => b.narrowness - a.narrowness);
}

/** The scope the header box searches: the narrowest that matches the current page. */
export function defaultScopeFor(pathname: string, labels: BuiltInScopeLabels): SearchScopeOption {
  return scopesForPath(pathname, labels)[0];
}

/**
 * The display label of a scope string, or `null` when no registered scope has that key.
 *
 * @param value The API scope string.
 * @param labels Display names for the built-in scopes.
 */
export function scopeLabel(value: string, labels: BuiltInScopeLabels): string | null {
  if (value === ALL_SCOPE) return labels.all;
  if (value === PROJECT_SCOPE) return labels.project;
  const [moduleKey, scopeKey] = value.split(":");
  const found = installedModules.find((m) => m.key === moduleKey)?.searchScopes?.find((s) => s.key === scopeKey);
  return found?.label ?? null;
}
