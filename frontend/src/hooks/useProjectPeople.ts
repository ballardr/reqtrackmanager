/**
 * Module: hooks/useProjectPeople
 *
 * The project and its organisation's members, which a create form's owner and reviewer pickers need. A dialog opened
 * from another page (the Links panel's "Create new") has no page that loaded them, so it asks here. A failed member
 * list resolves to an empty one: the pickers then search the directory by name, as they do for a large organisation.
 */
import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { OrgUser, Project } from "../api/types";

/**
 * @param projectId The project whose organisation's members are wanted.
 * @returns `project` and `orgUsers`, both `null` until loaded; `project` stays `null` when it cannot be read.
 */
export function useProjectPeople(projectId: string): { project: Project | null; orgUsers: OrgUser[] | null } {
  const [state, setState] = useState<{ project: Project | null; orgUsers: OrgUser[] | null }>({ project: null, orgUsers: null });
  useEffect(() => {
    let live = true;
    (async () => {
      try {
        const project = await api.get<Project>(`/api/v1/projects/${projectId}`);
        const orgUsers = await api.get<OrgUser[]>(`/api/v1/orgs/${project.organization_id}/users`).catch(() => [] as OrgUser[]);
        if (live) setState({ project, orgUsers });
      } catch {
        if (live) setState({ project: null, orgUsers: [] });
      }
    })();
    return () => { live = false; };
  }, [projectId]);
  return state;
}
