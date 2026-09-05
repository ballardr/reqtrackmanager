import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { ModuleNavEntry } from "../api/types";

/**
 * Fetches the currently-enabled modules for `projectId`'s owning
 * organisation, with enough of each one's frontend manifest to render a nav
 * entry/route (`GET /projects/{id}/enabled-modules`, module system Phase
 * 3). Returns `[]` (not loading state) while `projectId` is `null` or the
 * fetch is in flight — both `Layout.tsx` (nav rendering) and `App.tsx`
 * (Tier A/B route splicing) call this independently, the same "each
 * concern fetches its own project-derived data" convention `BrandingContext`/
 * `TerminologyContext` already use rather than a shared provider, since
 * this is a small, cheap, already-cached-by-the-browser GET.
 */
export function useProjectEnabledModules(projectId: string | null): ModuleNavEntry[] {
  const [modules, setModules] = useState<ModuleNavEntry[]>([]);

  useEffect(() => {
    if (!projectId) {
      setModules([]);
      return;
    }
    let cancelled = false;
    api.get<ModuleNavEntry[]>(`/api/v1/projects/${projectId}/enabled-modules`).then((result) => {
      if (!cancelled) setModules(result);
    });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  return modules;
}
