/**
 * Module: hooks/useProjectHasStages
 *
 * Whether a project uses its stages beyond the single default one every project starts with, for the navigation: a project
 * that has not gone further has nothing to show on the Delivery status page, so its navigation entry is hidden. Asks the
 * server (`GET /projects/{id}/stage-usage`, one small read) and asks again on every route change, so using stages in project
 * administration (a second stage, a schedule, component phases) is reflected on the next navigation, without a reload.
 *
 * Design decisions: unknown counts as "not in use", so the entry appears once known rather than appearing and disappearing;
 * a failed read also hides it (the page remains reachable by its address and shows its own state).
 */
import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";

import { api } from "../api/client";

/**
 * @param projectId The project whose stages are counted, or null when no project is open.
 * @returns True once the server reports the project uses its stages.
 */
export function useProjectHasStages(projectId: string | null): boolean {
  const { pathname } = useLocation();
  const [result, setResult] = useState<{ forId: string; has: boolean } | null>(null);

  useEffect(() => {
    if (!projectId) return;
    let cancelled = false;
    api.get<{ in_use: boolean }>(`/api/v1/projects/${projectId}/stage-usage`)
      .then((usage) => { if (!cancelled) setResult({ forId: projectId, has: usage.in_use === true }); })
      .catch(() => { if (!cancelled) setResult({ forId: projectId, has: false }); });
    return () => { cancelled = true; };
  }, [projectId, pathname]);

  return projectId !== null && result?.forId === projectId && result.has;
}
