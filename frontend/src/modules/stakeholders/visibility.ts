/**
 * Module: modules/stakeholders/visibility
 *
 * The one client-side rule for showing an org Persona/Stakeholder in a project
 * again after it was hidden (Phase 3b), shared by both project list pages.
 * Visibility is override-only (`hidden_override`/`hidden_source`), so "show"
 * is two steps at most: drop the project's own hide, then, if a parent project
 * still hides the record, override that with an explicit "shown".
 */

/** What the visibility override endpoints return, and what the rule reads. */
export interface VisibilityRecord {
  id: string;
  project_hidden: boolean | null;
  hidden_source: string | null;
}

/** The two override calls both project APIs (`projectPersonaApi`, `projectStakeholderApi`) expose. */
export interface VisibilityApi<R extends VisibilityRecord> {
  setVisibility(projectId: string, recordId: string, hidden: boolean): Promise<R>;
  clearVisibility(projectId: string, recordId: string): Promise<R>;
}

/**
 * Makes a hidden record visible in `projectId`.
 *
 * @throws Whatever the API throws (the caller toasts it).
 */
export async function showRecordInProject<R extends VisibilityRecord>(
  api: VisibilityApi<R>, projectId: string, record: R,
): Promise<void> {
  let updated = record;
  if (record.hidden_source === "project") updated = await api.clearVisibility(projectId, record.id);
  if (updated.project_hidden) await api.setVisibility(projectId, record.id, false);
}
