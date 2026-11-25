import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { ModuleNavEntry } from "../api/types";

export interface ProjectEnabledModulesResult {
  modules: ModuleNavEntry[];
  /** `true` once the fetch for the current `projectId` has settled, or immediately when `projectId` is `null`. */
  loaded: boolean;
}

interface State {
  /** The `projectId` this `modules`/`loaded` pair was resolved for — lets a
   * render tell a genuinely-settled result apart from one left over from
   * a `projectId` that has since changed. */
  forId: string | null;
  modules: ModuleNavEntry[];
  loaded: boolean;
}

/** Subscribers of `refreshProjectEnabledModules`, one per mounted `useProjectEnabledModules`. */
const refreshListeners = new Set<(projectId: string) => void>();

/**
 * Tells every mounted `useProjectEnabledModules` for `projectId` to re-fetch. Call it after anything
 * that changes which modules or sub-components are on for the project (the Modules tab toggles), so
 * the nav rail and module routes follow without a reload.
 *
 * Args:
 *   projectId: The project whose module state changed.
 */
export function refreshProjectEnabledModules(projectId: string): void {
  refreshListeners.forEach((listener) => listener(projectId));
}

/**
 * Fetches the currently-enabled modules for `projectId`'s owning organisation, with enough of each one's frontend
 * manifest to render a nav entry or route (`GET /projects/{id}/enabled-modules`). `Layout.tsx` (nav) and `App.tsx`
 * (Tier A/B route splicing) each call it independently, as `BrandingContext` and `TerminologyContext` do for their data.
 *
 * `loaded` lets `App.tsx` hold the wildcard `Navigate` while a project-scoped path's module routes are unknown:
 * `modules` is `[]` while the fetch is in flight, so a navigation straight to a module URL would otherwise match the
 * wildcard fallback and bounce to `/projects`. The returned state is keyed to the `projectId` it was resolved for
 * and reset synchronously during render when `projectId` changes ("adjusting state when a prop changes"), so the first
 * render after a change never reports the previous project's `loaded: true, modules: []`.
 *
 * `ready` delays the fetch until authentication has settled: passive effects run child before parent, so on a fresh
 * boot this hook's effect would otherwise fire before `AuthProvider` loads the stored token, send no `Authorization`
 * header, get a 401 and never retry (`projectId` does not change again), hiding every Tier A module for the session.
 * `Layout.tsx` mounts only after the `loading` check passes and needs no such gate.
 */
export function useProjectEnabledModules(projectId: string | null, ready: boolean = true): ProjectEnabledModulesResult {
  const [state, setState] = useState<State>({ forId: projectId, modules: [], loaded: projectId === null });

  if (state.forId !== projectId) {
    setState({ forId: projectId, modules: [], loaded: projectId === null });
  }

  // Bumped by `refreshProjectEnabledModules`; re-runs the fetch below without resetting `loaded`, so a
  // refresh never flashes the route-splicing spinner.
  const [refreshTick, setRefreshTick] = useState(0);
  useEffect(() => {
    const listener = (changedId: string) => {
      if (changedId === projectId) setRefreshTick((tick) => tick + 1);
    };
    refreshListeners.add(listener);
    return () => {
      refreshListeners.delete(listener);
    };
  }, [projectId]);

  useEffect(() => {
    if (!projectId || !ready) return;
    let cancelled = false;
    api.get<ModuleNavEntry[]>(`/api/v1/projects/${projectId}/enabled-modules`).then(
      (result) => {
        if (!cancelled) setState({ forId: projectId, modules: result, loaded: true });
      },
      () => {
        // A failed fetch still resolves `loaded`, because `App.tsx`'s wildcard route waits on it and would otherwise
        // show a spinner indefinitely; `prev.modules` survives so a transient error does not empty a nav rail
        // that was already showing the right entries.
        if (!cancelled) {
          setState((prev) => ({ forId: projectId, modules: prev.forId === projectId ? prev.modules : [], loaded: true }));
        }
      }
    );
    return () => {
      cancelled = true;
    };
  }, [projectId, ready, refreshTick]);

  // `state.forId === projectId` holds here: `setState` during render (above) makes React discard
  // this render and retry with the new state.
  return { modules: state.modules, loaded: state.loaded };
}
