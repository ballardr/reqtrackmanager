/**
 * Module: modules/product_feedback/useExternalReferences
 *
 * Whether the External references sub-component (references to items in outside tools, and the list of systems they
 * point at) is on for the request's tier: a project's effective state, or the organisation's own for an inbox request.
 * The request forms and page show the feature only when this is true; the backend 404s its routes while it is off.
 */
import { useOrgSubComponentEnabled, useProjectSubComponentEnabled } from "../../hooks/useSubComponentEnabled";

/** The sub-component key the backend registers (`service.EXTERNAL_REFERENCES_SUBCOMPONENT_KEY`). */
export const EXTERNAL_REFERENCES_KEY = "external_references";

/**
 * @param projectId A project request's project; omit for an inbox request.
 * @param organizationId The organisation (an inbox request's tier).
 * @returns True once the sub-component is known to be on; false while loading or off.
 */
export function useExternalReferencesEnabled(projectId?: string, organizationId?: string): boolean {
  const project = useProjectSubComponentEnabled(projectId, "product_feedback", EXTERNAL_REFERENCES_KEY);
  const org = useOrgSubComponentEnabled(projectId ? undefined : organizationId, "product_feedback", EXTERNAL_REFERENCES_KEY);
  return (projectId ? project : org) === true;
}
