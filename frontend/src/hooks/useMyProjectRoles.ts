import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { ProjectListItem, ProjectRole } from "../api/types";

/**
 * The current user's effective roles on a specific project, so pages can
 * hide actions (approve/reject a change request, archive a requirement)
 * that the viewer holds no permission for — the backend always enforces
 * this regardless, but a control that 403s on click isn't a working
 * workflow. `ProjectListItemOut.my_roles` (already returned by the
 * projects list endpoint) is the cheapest source of this without a new
 * backend endpoint.
 */
export function useMyProjectRoles(projectId: string | undefined): ProjectRole[] {
  const [roles, setRoles] = useState<ProjectRole[]>([]);

  useEffect(() => {
    if (!projectId) return;
    let cancelled = false;
    api.get<ProjectListItem[]>("/api/v1/projects?archived=false").then((projects) => {
      if (cancelled) return;
      setRoles(projects.find((p) => p.id === projectId)?.my_roles ?? []);
    });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  return roles;
}
