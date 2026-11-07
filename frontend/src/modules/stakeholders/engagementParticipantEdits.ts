/**
 * Module: modules/stakeholders/engagementParticipantEdits
 *
 * Loads and saves an Engagement's participants for the edit form, which shows them with the same
 * field the create form uses. `loadParticipantEntries` reads the Stakeholders and (with the
 * Research extras on) the anonymous participants; `applyParticipantChanges` compares the form's
 * result with what was loaded and issues only the calls that differ (add or remove a Stakeholder;
 * add, remove or change the Persona of an anonymous participant).
 *
 * These are the same endpoints the detail page's Participants list uses, so audit events, the
 * Research extras gate and permissions are unchanged. A Stakeholder the form cannot display (hidden
 * from the project) stays in `stakeholderIds`, so it is neither shown nor removed by an edit.
 */
import { projectEngagementApi, projectResearchApi } from "./api";
import type { ParticipantEntries } from "./types";

/**
 * Reads the participants of an Engagement.
 *
 * @param projectId The project of the Engagement.
 * @param engagementId The Engagement.
 * @param researchExtras Whether anonymous participants are available (otherwise they are not read).
 * @returns The Stakeholder ids and anonymous participants recorded.
 * @throws When the Stakeholder participants cannot be read (the caller then edits without them).
 */
export async function loadParticipantEntries(projectId: string, engagementId: string, researchExtras: boolean): Promise<ParticipantEntries> {
  const [stakeholders, anonymous] = await Promise.all([
    projectEngagementApi.listParticipants(projectId, engagementId),
    researchExtras ? projectResearchApi.listAnonymousParticipants(projectId, engagementId) : Promise.resolve([]),
  ]);
  return {
    stakeholderIds: stakeholders.map((p) => p.stakeholder_id),
    anonymous: anonymous.map((p) => ({ id: p.id, label: p.label, persona_id: p.persona_id, persona_name: p.persona_name })),
  };
}

/**
 * Brings the recorded participants in line with the edited list, one call per difference.
 *
 * @param projectId The project of the Engagement.
 * @param engagementId The Engagement.
 * @param before What was recorded when the form opened (or was last reloaded).
 * @param after What the form now holds.
 * @throws The first failing call's error; the calls before it have already been applied.
 */
export async function applyParticipantChanges(
  projectId: string, engagementId: string, before: ParticipantEntries, after: ParticipantEntries,
): Promise<void> {
  const keptStakeholders = new Set(after.stakeholderIds);
  const hadStakeholders = new Set(before.stakeholderIds);
  for (const id of before.stakeholderIds) {
    if (!keptStakeholders.has(id)) await projectEngagementApi.removeParticipant(projectId, engagementId, id);
  }
  for (const id of after.stakeholderIds) {
    if (!hadStakeholders.has(id)) await projectEngagementApi.addParticipant(projectId, engagementId, id);
  }

  const kept = new Map(after.anonymous.filter((p) => p.id).map((p) => [p.id as string, p]));
  for (const old of before.anonymous) {
    const now = old.id ? kept.get(old.id) : undefined;
    if (!old.id || !now) {
      if (old.id) await projectResearchApi.deleteAnonymousParticipant(projectId, engagementId, old.id);
    } else if ((now.persona_id ?? null) !== (old.persona_id ?? null)) {
      await projectResearchApi.updateAnonymousParticipant(projectId, engagementId, old.id, { persona_id: now.persona_id });
    }
  }
  for (const added of after.anonymous.filter((p) => !p.id)) {
    await projectResearchApi.addAnonymousParticipant(projectId, engagementId, { label: added.label, persona_id: added.persona_id });
  }
}
