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

interface State {
  /** The `projectId` this `modules`/`loaded` pair was resolved for — lets a
   * render tell a genuinely-settled result apart from one left over from
   * a `projectId` that has since changed. */
  forId: string | null;
  modules: ModuleNavEntry[];
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
 *
 * Found during compliance-module-plan.md Phase 39: that fix only covered a
 * *fresh page load* landing directly on a project-scoped URL (`loaded`'s
 * `useState` initializer reads the right `projectId` from the very first
 * render). It missed the same race one step earlier — a client-side
 * navigation from a project-less page (e.g. `/org-overview`) straight into
 * a project's own module route, for the first time in that page's
 * lifetime. On that transition's first render, `projectId` has already
 * changed but the `useEffect` below (which resets `loaded`) hasn't run
 * yet — it fires *after* this render commits — so this hook still returned
 * the *previous* `projectId`'s state, typically `loaded: true, modules: []`
 * left over from the "no project" case. `App.tsx` then saw an "already
 * loaded, no modules" project and bounced straight to `/projects` before
 * the real fetch ever started. Fixed by keying the returned state to the
 * `projectId` it was actually resolved for and resetting synchronously
 * during render when `projectId` changes (React's own documented "adjusting
 * state when a prop changes" pattern) rather than waiting for the effect —
 * so the very first render after any `projectId` change already reports
 * `loaded: false` (or `true` immediately, for the "no project" case) with
 * no stale carry-over from whatever `projectId` was current before.
 */
export function useProjectEnabledModules(projectId: string | null): ProjectEnabledModulesResult {
  const [state, setState] = useState<State>({ forId: projectId, modules: [], loaded: projectId === null });

  if (state.forId !== projectId) {
    setState({ forId: projectId, modules: [], loaded: projectId === null });
  }

  useEffect(() => {
    if (!projectId) return;
    let cancelled = false;
    api.get<ModuleNavEntry[]>(`/api/v1/projects/${projectId}/enabled-modules`).then((result) => {
      if (!cancelled) setState({ forId: projectId, modules: result, loaded: true });
    });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  // By this point `state.forId === projectId` always holds: calling
  // `setState` during render (above) makes React immediately discard this
  // render and retry with the new state before ever reaching here — React's
  // own documented behaviour for this "adjusting state when a prop
  // changes" pattern.
  return { modules: state.modules, loaded: state.loaded };
}
