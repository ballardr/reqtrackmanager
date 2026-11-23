import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { ProjectRole } from "../api/types";

/**
 * The current user's effective roles on a specific project, so pages can hide actions (approve or reject a
 * change request, archive a requirement) the viewer holds no permission for; the backend enforces permissions
 * regardless. Reads `GET /projects/{id}/my-roles`, which resolves only this project, so no per-project role
 * resolution runs for every accessible project.
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
