/**
 * Module: hooks/useProjectScope
 *
 * The state behind a list's project scope filter: which related projects the list covers. A list
 * page keeps this beside its other filters, renders `ProjectScopeFilter` with it and adds `query`
 * to its list read, so the server (not the browser) widens the list.
 *
 * The choice is remembered per viewer and per project (one `project_scopes` map in
 * `ui_preferences`, so the bag stays one key however many projects are visited), starting from the
 * viewer's default (`default_project_scope`, set on the Preferences page). A stored choice the
 * project cannot offer degrades to what it can (`effectiveScope`); a project with no parent or child
 * the viewer can open always shows "this project".
 */
import { useContext, useEffect, useState } from "react";

import {
  availableScopes,
  effectiveScope,
  parseProjectScope,
  projectScopeApi,
  projectScopeQuery,
  type ProjectScope,
  type ProjectScopeApi,
  type ProjectScopeOptions,
} from "../api/projectScope";
import { AuthContext } from "../context/AuthContextValue";

/** The `ui_preferences` key holding the viewer's default list scope. */
export const DEFAULT_PROJECT_SCOPE_PREFERENCE = "default_project_scope";

/** The `ui_preferences` key holding the viewer's per-project choices, `{ [projectId]: scope }`. */
export const PROJECT_SCOPES_PREFERENCE = "project_scopes";

/** Reads the stored per-project map, dropping anything that is not a known scope. */
function storedScopes(value: unknown): Record<string, ProjectScope> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return {};
  const result: Record<string, ProjectScope> = {};
  for (const [id, scope] of Object.entries(value)) {
    const parsed = parseProjectScope(scope);
    if (parsed) result[id] = parsed;
  }
  return result;
}

export interface ProjectScopeState {
  /** The scope in effect (always one of `available`). */
  scope: ProjectScope;
  setScope: (scope: ProjectScope) => void;
  /** The scopes this project offers; just `this` when it has no openable relatives. */
  available: ProjectScope[];
  /** `project_scope=parents`, or an empty string for the single-project list. */
  query: string;
  /** Whether the list is widened beyond this project. */
  widened: boolean;
}

/**
 * Holds a list's project scope.
 *
 * @param projectId The project being viewed.
 * @param scopeApi Injectable calls (stories pass a fake).
 */
export function useProjectScope(projectId: string | undefined, scopeApi: ProjectScopeApi = projectScopeApi): ProjectScopeState {
  // Read the context directly (not `useAuth`) so a list still renders, on "this project", where no auth
  // provider exists (a page rendered on its own).
  const auth = useContext(AuthContext);
  const user = auth?.user ?? null;
  const [options, setOptions] = useState<{ projectId: string; value: ProjectScopeOptions } | null>(null);

  useEffect(() => {
    if (!projectId) return;
    let active = true;
    scopeApi.options(projectId)
      .then((value) => active && setOptions({ projectId, value }))
      .catch(() => active && setOptions(null));
    return () => {
      active = false;
    };
  }, [projectId, scopeApi]);

  const available = availableScopes(options && options.projectId === projectId ? options.value : null);
  const preferences = user?.ui_preferences ?? {};
  const chosen = storedScopes(preferences[PROJECT_SCOPES_PREFERENCE]);
  const stored =
    (projectId ? chosen[projectId] : null) ?? parseProjectScope(preferences[DEFAULT_PROJECT_SCOPE_PREFERENCE]) ?? "this";
  const scope = effectiveScope(stored, available);

  function setScope(next: ProjectScope) {
    if (projectId) auth?.setUiPreference(PROJECT_SCOPES_PREFERENCE, { ...chosen, [projectId]: next });
  }

  return { scope, setScope, available, query: projectScopeQuery(scope), widened: scope !== "this" };
}
