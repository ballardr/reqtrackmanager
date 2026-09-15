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
 *
 * `ready` (found 2026-09-15, documenting the Modules section) covers a
 * third, structural race one step earlier still: `App.tsx`'s `ProtectedRoutes`
 * must call this hook unconditionally, before its own `if (loading) return
 * <Spinner />` early return (Rules of Hooks) — but React fires a commit's
 * passive effects child-before-parent, so on a fresh app boot this hook's
 * effect (a descendant of `AuthProvider`) can fire, and dispatch its fetch,
 * *before* `AuthProvider`'s own effect has called `loadStoredToken()`. That
 * first request went out with no `Authorization` header at all, 401ed, and —
 * because `projectId` never changes again for the rest of that project visit
 * — this hook never got a second chance to fetch, permanently hiding every
 * Tier A module's nav entry/route for that project for the rest of the
 * session (worse than the plain failed-fetch case above, which at least
 * resolves; this one resolves to a *wrong*, stuck-empty result). `App.tsx`
 * passes `!loading` here so the effect simply doesn't fire at all until
 * `AuthProvider` has already set a real token — `Layout.tsx`'s own call site
 * needs no such gate, since `Layout` only ever mounts after `ProtectedRoutes`'s
 * `loading` check has already passed.
 */
export function useProjectEnabledModules(projectId: string | null, ready: boolean = true): ProjectEnabledModulesResult {
  const [state, setState] = useState<State>({ forId: projectId, modules: [], loaded: projectId === null });

  if (state.forId !== projectId) {
    setState({ forId: projectId, modules: [], loaded: projectId === null });
  }

  useEffect(() => {
    if (!projectId || !ready) return;
    let cancelled = false;
    api.get<ModuleNavEntry[]>(`/api/v1/projects/${projectId}/enabled-modules`).then(
      (result) => {
        if (!cancelled) setState({ forId: projectId, modules: result, loaded: true });
      },
      () => {
        // A failed fetch (e.g. a transient 401) must still resolve `loaded`
        // to `true` — leaving it `false` forever was a real bug: `App.tsx`'s
        // wildcard route (see its own comment at that route) holds a
        // project-scoped navigation on a spinner until `loaded` flips,
        // specifically so it doesn't need to know this list yet. A rejected
        // promise here never flipped it, so one transient failure produced
        // a permanently stuck spinner on every module route for that
        // project, with no retry. Falling back to `modules: []` is the same
        // safe default this hook already returns while a fetch is in
        // flight — worst case a module's nav entry/route is briefly
        // unavailable, never a hang.
        if (!cancelled) setState({ forId: projectId, modules: [], loaded: true });
      }
    );
    return () => {
      cancelled = true;
    };
  }, [projectId, ready]);

  // By this point `state.forId === projectId` always holds: calling
  // `setState` during render (above) makes React immediately discard this
  // render and retry with the new state before ever reaching here — React's
  // own documented behaviour for this "adjusting state when a prop
  // changes" pattern.
  return { modules: state.modules, loaded: state.loaded };
}
