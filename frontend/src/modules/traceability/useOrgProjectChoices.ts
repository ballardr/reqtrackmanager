/**
 * Module: modules/traceability/useOrgProjectChoices
 *
 * Loads the organisation's projects for the pickers of a governance profile (the projects it reaches and the projects it
 * exempts), as one list shared by every picker of a screen.
 *
 * Responsibilities: read `loadOrgProjects` once per organisation; report a failed read so a picker can say so instead of
 * offering an empty list; name a project the way every picker shows it.
 *
 * Dependencies: `api/lifecycles` (`loadOrgProjects`), `useLoadOnChange`.
 */
import { useCallback, useState } from "react";

import { loadOrgProjects } from "../../api/lifecycles";
import type { Project } from "../../api/types";
import { useLoadOnChange } from "../../hooks/useLoadOnChange";

/** A project as a picker offers it. */
export type ProjectChoice = Pick<Project, "id" | "name" | "code">;

/**
 * @param project The project.
 * @returns Its code and name, as every Governance picker and list shows it.
 */
export function projectChoiceLabel(project: Pick<Project, "name" | "code">): string {
  return `${project.code} ${project.name}`;
}

/**
 * @param orgId The organisation whose projects are listed.
 * @returns The projects (`null` while loading) and whether the read failed.
 */
export function useOrgProjectChoices(orgId: string): { projects: ProjectChoice[] | null; failed: boolean } {
  const [projects, setProjects] = useState<ProjectChoice[] | null>(null);
  const [failed, setFailed] = useState(false);
  const load = useCallback(async () => {
    try {
      setProjects(await loadOrgProjects(orgId));
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, [orgId]);
  useLoadOnChange(load, [orgId]);
  return { projects, failed };
}
