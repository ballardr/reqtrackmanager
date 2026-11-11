/**
 * Module: context/NavLabelContext
 *
 * Provider of navigation names (a project or organisation renaming "Decisions" to "ADRs"). Fetches the
 * names that apply to the current project and offers them, keyed by the route each navigation entry opens,
 * so the navigation rail, a list page's title and a record page's back link all read the one answer
 * (hooks in `NavLabelValue.ts`).
 *
 * Design decisions:
 * - Names are looked up by route path, not by key: the server returns each entry's resolved path with its
 *   name, and every page already knows its own list path, so no module or page needs to know a key.
 * - Only an entry that has an override is stored; a path with none keeps the built-in text its caller passes.
 * - Outside a project, or while loading or after a failed load, no override applies (the built-in names show).
 * - `refreshNavLabels` lets the administration panel make a saved change appear without a reload.
 *
 * External dependencies: `GET /api/v1/projects/{id}/nav-labels`.
 */
import { useEffect, useMemo, useState, type ReactNode } from "react";

import { api } from "../api/client";
import type { NavLabels } from "../api/types";
import { NavLabelValue, normaliseNavPath, onNavLabelsRefresh, type NamesByPath } from "./NavLabelValue";

/**
 * Provides the current project's navigation names to everything underneath.
 *
 * @param projectId The project in the URL, or null outside a project.
 * @param children The app shell.
 */
export function NavLabelProvider({ projectId, children }: { projectId: string | null; children: ReactNode }) {
  const [loaded, setLoaded] = useState<{ forId: string | null; names: NamesByPath }>({ forId: null, names: {} });
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    if (!projectId) return;
    return onNavLabelsRefresh((id) => { if (id === projectId) setRevision((n) => n + 1); });
  }, [projectId]);

  useEffect(() => {
    if (!projectId) return;
    let cancelled = false;
    api.get<NavLabels>(`/api/v1/projects/${projectId}/nav-labels`).then((body) => {
      if (cancelled) return;
      const names: NamesByPath = {};
      for (const item of body.items) {
        if (item.effective && item.path) names[normaliseNavPath(item.path)] = item.effective;
      }
      setLoaded({ forId: projectId, names });
    }).catch(() => {
      if (!cancelled) setLoaded({ forId: projectId, names: {} });
    });
    return () => { cancelled = true; };
  }, [projectId, revision]);

  const value = useMemo(() => (projectId && loaded.forId === projectId ? loaded.names : {}), [projectId, loaded]);
  return <NavLabelValue.Provider value={value}>{children}</NavLabelValue.Provider>;
}
