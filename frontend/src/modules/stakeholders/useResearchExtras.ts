/**
 * Module: modules/stakeholders/useResearchExtras
 *
 * Whether the Stakeholders & Personas module's "Research extras" sub-component
 * (session prompts, anonymous participants, findings) is on for a project. The
 * engagement log works without it, so the detail page shows those blocks only
 * when this resolves true; the backend 404s their routes while it is off. Read
 * through the generic sub-component hook, so no module-specific endpoint is needed.
 */
import { useProjectSubComponentEnabled } from "../../hooks/useSubComponentEnabled";

/** The sub-component key the backend registers (`engagements.RESEARCH_SUBCOMPONENT`). */
export const RESEARCH_EXTRAS_KEY = "research_extras";

/** `null` while loading, then whether the research extras are effectively enabled (false if the lookup fails). */
export function useResearchExtras(projectId: string | undefined): boolean | null {
  return useProjectSubComponentEnabled(projectId, "stakeholders", RESEARCH_EXTRAS_KEY);
}
