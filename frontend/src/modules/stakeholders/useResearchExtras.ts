/**
 * Module: modules/stakeholders/useResearchExtras
 *
 * Whether the Stakeholders & Personas module's "Research extras" sub-component
 * (session prompts, anonymous participants, findings) is on for a project. The
 * engagement log works without it, so the detail page shows those blocks only
 * when this resolves true; the backend 404s their routes while it is off. Read
 * from the generic project sub-component listing, so no module-specific
 * endpoint is needed.
 */
import { useEffect, useState } from "react";

import { api } from "../../api/client";
import type { ProjectModuleSubComponent } from "../../api/types";

/** The sub-component key the backend registers (`engagements.RESEARCH_SUBCOMPONENT`). */
export const RESEARCH_EXTRAS_KEY = "research_extras";

/** `null` while loading, then whether the research extras are effectively enabled (false if the lookup fails). */
export function useResearchExtras(projectId: string | undefined): boolean | null {
  const [state, setState] = useState<{ projectId: string; enabled: boolean } | null>(null);

  useEffect(() => {
    if (!projectId) return;
    let active = true;
    api
      .get<ProjectModuleSubComponent[]>(`/api/v1/projects/${projectId}/modules/stakeholders/subcomponents`)
      .then((subs) => {
        if (active) setState({ projectId, enabled: subs.some((s) => s.subcomponent_key === RESEARCH_EXTRAS_KEY && s.effective_enabled) });
      })
      .catch(() => {
        if (active) setState({ projectId, enabled: false });
      });
    return () => {
      active = false;
    };
  }, [projectId]);

  return state && state.projectId === projectId ? state.enabled : null;
}
