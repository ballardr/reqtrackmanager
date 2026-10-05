import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { ProjectRole } from "../api/types";

/**
 * The current user's effective roles on a specific project, so pages can
 * hide actions (approve/reject a change request, archive a requirement)
 * that the viewer holds no permission for — the backend always enforces
 * this regardless, but a control that 403s on click isn't a working
 * workflow. Reads `GET /projects/{id}/my-roles`, which resolves just this
 * project — it previously pulled the whole project list (resolving roles
 * for every accessible project, the hottest backend call in the e2e suite)
 * and returned no roles at all on an archived project.
 */
export function useMyProjectRoles(projectId: string | undefined): ProjectRole[] {
  const [roles, setRoles] = useState<ProjectRole[]>([]);

  useEffect(() => {
    if (!projectId) return;
    let cancelled = false;
    api.get<{ roles: ProjectRole[] }>(`/api/v1/projects/${projectId}/my-roles`)
      .then((result) => {
        if (!cancelled) setRoles(result.roles);
      })
      .catch(() => {
        // No access (or a transient failure) means no role-gated controls,
        // the same "show nothing" result as before; the backend still
        // enforces every action regardless.
        if (!cancelled) setRoles([]);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  return roles;
}
