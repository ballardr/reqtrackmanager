/**
 * Module: api/requirementTypes
 *
 * The requirement type list (Business, Stakeholder and Project Requirement by default) at both tiers, in the shapes
 * the shared `TypeVocabularyPanels` and the requirement type pickers take (`routers/requirement_types.py`).
 *
 * A type's `rank` (its priority) travels as the panels' extra text field; the adapters here turn the typed text into
 * the whole number the endpoints take, and a blank into null (organisation: unranked; project: follow the organisation).
 */
import type { EffectiveTypeRow, OrgTypeRow, OrgTypeVocabularyApi, ProjectTypeVocabularyApi } from "../components/TypeVocabularyPanels";
import { api } from "./client";
import { orgVocabularyApi, projectVocabularyApi } from "./typeVocabulary";

/** @param text The rank as typed. @returns The whole number, or null for a blank. */
function toRank(text: string | null | undefined): number | null {
  return text === undefined || text === null || text.trim() === "" ? null : Number(text);
}

const baseOrg = orgVocabularyApi((organizationId) => `/api/v1/orgs/${organizationId}/requirement-types`);
const baseProject = projectVocabularyApi((projectId) => `/api/v1/projects/${projectId}/requirement-types`);

const orgApi: OrgTypeVocabularyApi<OrgTypeRow> = {
  ...baseOrg,
  create: (organizationId, name, rank) =>
    api.post<OrgTypeRow>(`/api/v1/orgs/${organizationId}/requirement-types`, { name, rank: toRank(rank) }),
  update: (organizationId, typeId, { rank, ...values }) =>
    api.patch<OrgTypeRow>(`/api/v1/orgs/${organizationId}/requirement-types/${typeId}`, {
      ...values, ...(rank !== undefined ? { rank: toRank(rank) } : {}),
    }),
};

const projectApi: ProjectTypeVocabularyApi = {
  ...baseProject,
  createLocal: (projectId, name, displayOrder, rank) =>
    api.post<unknown>(`/api/v1/projects/${projectId}/requirement-types`, { name, display_order: displayOrder ?? null, rank: toRank(rank) }),
  override: (projectId, typeRefId, { rank, ...values }) =>
    api.put<unknown>(`/api/v1/projects/${projectId}/requirement-types/${typeRefId}`, {
      ...values, ...(rank !== undefined ? { rank: toRank(rank) } : {}),
    }),
};

export const requirementTypeApi = { project: projectApi, org: orgApi };

/**
 * @param projectId The project whose list to read.
 * @returns The project's effective requirement types in their configured order (disabled ones included, so a form can
 *   show a requirement's current type; a picker offers only the enabled ones).
 */
export function listRequirementTypes(projectId: string): Promise<EffectiveTypeRow[]> {
  return api.get<EffectiveTypeRow[]>(`/api/v1/projects/${projectId}/requirement-types`);
}
