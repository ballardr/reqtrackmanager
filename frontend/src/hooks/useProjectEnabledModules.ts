import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { ModuleNavEntry } from "../api/types";

export interface ProjectEnabledModulesResult {
  modules: ModuleNavEntry[];
  /** `true` once the fetch for the current `projectId` has settled (or
   * immediately, when `projectId` is `null` — there is nothing to wait
   * for). See this hook's own docstring for why `App.tsx` needs this,
   * not just `modules` itself. */
  loaded: boolean;
}

/**
 * Fetches the currently-enabled modules for `projectId`'s owning
 * organisation, with enough of each one's frontend manifest to render a nav
 * entry/route (`GET /projects/{id}/enabled-modules`, module system Phase
 * 3). Both `Layout.tsx` (nav rendering) and `App.tsx` (Tier A/B route
 * splicing) call this independently, the same "each concern fetches its
 * own project-derived data" convention `BrandingContext`/`TerminologyContext`
 * already use rather than a shared provider, since this is a small, cheap,
 * already-cached-by-the-browser GET.
 *
 * `loaded` was added by Phase 13 (Project Compliance View) after it
 * surfaced a real bug in `App.tsx`'s own route-splicing: `modules` starts
 * `[]` while the fetch is in flight, `buildModuleRoutes([], projectId)`
 * then contributes zero `<Route>`s, and — because Compliance is the first
 * *real* Tier A module ever mounted at a project-scoped path — a fresh
 * navigation straight to a module's own URL (e.g. clicking its nav-rail
 * link) landed on `<Routes>`'s wildcard fallback (`<Navigate to="/projects"
 * />`) before the fetch could resolve and contribute the matching route,
 * bouncing the user straight back to `/projects` every time. No earlier
 * phase caught this: Phase 3's own tests only proved the mechanism against
 * a fixture module with `enabledModules` pre-seeded synchronously
 * (`App.stories.tsx`'s `TierARoutingHarness`), and Phase 12's org-level
 * panel never used this routing mechanism at all (mounted directly on
 * `OrgAdminPage` instead — see that phase's own notes). `App.tsx` now reads
 * `loaded` to hold off the wildcard `Navigate` specifically while a
 * project-scoped path's module routes are still unknown, rather than
 * delaying every project page's render on this fetch — see that file's own
 * comment at the wildcard route.
 */
export function useProjectEnabledModules(projectId: string | null): ProjectEnabledModulesResult {
  const [modules, setModules] = useState<ModuleNavEntry[]>([]);
  const [loaded, setLoaded] = useState(projectId === null);

  useEffect(() => {
    if (!projectId) {
      setModules([]);
      setLoaded(true);
      return;
    }
    let cancelled = false;
    setLoaded(false);
    api.get<ModuleNavEntry[]>(`/api/v1/projects/${projectId}/enabled-modules`).then((result) => {
      if (!cancelled) {
        setModules(result);
        setLoaded(true);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  return { modules, loaded };
}
