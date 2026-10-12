import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { OrgGroup, PrincipalType, ProjectGroup } from "../api/types";

/**
 * The groups a principal field can name, loaded once for a picker: the organisation's groups, and
 * (when a project is given) that project's groups. Skips the request for a kind the field does not
 * allow, so a user-only field makes no network calls. A load failure leaves the list empty rather
 * than blocking the field (users can still be picked).
 *
 * @param organizationId The organisation whose groups to list; omit for none.
 * @param projectId The project whose groups to list; omit for none.
 * @param kinds The principal kinds the field allows.
 */
export function usePrincipalDirectory(
  organizationId: string | undefined,
  projectId: string | undefined,
  kinds: readonly PrincipalType[],
): { orgGroups: OrgGroup[]; projectGroups: ProjectGroup[] } {
  const wantOrg = kinds.includes("org_group") && !!organizationId;
  const wantProject = kinds.includes("project_group") && !!projectId;
  const [orgGroups, setOrgGroups] = useState<OrgGroup[]>([]);
  const [projectGroups, setProjectGroups] = useState<ProjectGroup[]>([]);

  useEffect(() => {
    if (!wantOrg) return;
    let cancelled = false;
    api.get<OrgGroup[]>(`/api/v1/orgs/${organizationId}/groups`).then(
      (groups) => !cancelled && setOrgGroups(groups),
      () => !cancelled && setOrgGroups([]),
    );
    return () => {
      cancelled = true;
    };
  }, [wantOrg, organizationId]);

  useEffect(() => {
    if (!wantProject) return;
    let cancelled = false;
    api.get<ProjectGroup[]>(`/api/v1/projects/${projectId}/groups`).then(
      (groups) => !cancelled && setProjectGroups(groups),
      () => !cancelled && setProjectGroups([]),
    );
    return () => {
      cancelled = true;
    };
  }, [wantProject, projectId]);

  return { orgGroups: wantOrg ? orgGroups : [], projectGroups: wantProject ? projectGroups : [] };
}
