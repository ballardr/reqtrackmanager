/**
 * Module: modules/product_feedback/usePainPointsAvailable
 *
 * Whether Pain Points (Context & Strategy's `pain_point` sub-component) are on for a project, so the request list's
 * Pain Points column and filter and the "No Pain Point" prompt are shown only where a Pain Point can exist. The two
 * are named by key, not imported: this module never depends on the other module's code. Switching the module off
 * hides the sub-component too, so one answer covers both.
 */
import { useProjectSubComponentEnabled } from "../../hooks/useSubComponentEnabled";

/**
 * @param projectId The project, or undefined for an organisation inbox (which has no Pain Point links).
 * @returns True once Pain Points are known to be on; false while loading, off, or without a project.
 */
export function usePainPointsAvailable(projectId?: string): boolean {
  return useProjectSubComponentEnabled(projectId, "context_strategy", "pain_point") === true;
}
