/**
 * Module: modules/stakeholders/useProjectStakeholderGroups
 *
 * The Stakeholder groups a project can see (its own plus its organisation's),
 * flat, for pickers outside the Stakeholder pages (the S1/S4 report filters).
 * Empty while loading or when the lookup fails, so a picker simply hides.
 */
import { useEffect, useState } from "react";

import { projectStakeholderGroupApi } from "./api";
import type { StakeholderGroup } from "./types";

/**
 * @param projectId The project, or `null` to skip loading (an organisation-wide run).
 * @returns The groups, in the API's order.
 */
export function useProjectStakeholderGroups(projectId: string | null): StakeholderGroup[] {
  const [state, setState] = useState<{ projectId: string; groups: StakeholderGroup[] } | null>(null);

  useEffect(() => {
    if (!projectId) return;
    let active = true;
    projectStakeholderGroupApi
      .list(projectId)
      .then((groups) => active && setState({ projectId, groups }))
      .catch(() => active && setState({ projectId, groups: [] }));
    return () => {
      active = false;
    };
  }, [projectId]);

  return state && state.projectId === projectId ? state.groups : [];
}
