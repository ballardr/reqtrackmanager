/**
 * Module: hooks/useProjectHasStages
 *
 * Whether a project uses its stages beyond the single default one every project starts with, so the Delivery status
 * navigation entry is hidden when that page would be empty. Asks `GET /projects/{id}/stage-usage` (one small read) on
 * every route change, so a second stage, a schedule or component phases appear on the next navigation.
 *
 * Design decisions: unknown counts as "not in use", so the entry never appears and disappears; a failed read also
 * hides it (the page stays reachable by its address and shows its own state).
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
