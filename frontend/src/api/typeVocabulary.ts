/**
 * Module: api/typeVocabulary
 *
 * Builders for the two tiers of a typed vocabulary's endpoints (`services.vocabulary_endpoints` on the server), in the
 * shapes the shared `TypeVocabularyPanels` take: external systems, a module's request channels, and any later list that
 * uses the same endpoints. A vocabulary supplies where its endpoints are; the calls are the same for every list.
 */
import type { HiddenDefinition } from "../components/RestoreOrgDefaultsButton";
import type { EffectiveTypeRow, OrgTypeRow } from "../components/TypeVocabularyPanels";
import { api } from "./client";

/** Values a project may override on one entry (a null `url_template` follows the organisation's). */
export interface ProjectTypeOverride {
  name?: string | null;
  display_order?: number | null;
  is_enabled?: boolean | null;
  definition?: string | null;
  url_template?: string | null;
}

/**
 * @param url The list's address for one project (`/api/v1/projects/{id}/external-systems`).
 * @returns The project-tier calls: the effective list, add an entry of the project's own, override one, delete or hide
 *   one (an organisation default is hidden), list the hidden ones and restore them.
 */
export function projectVocabularyApi(url: (projectId: string) => string) {
  return {
    list: (projectId: string) => api.get<EffectiveTypeRow[]>(url(projectId)),
    createLocal: (projectId: string, name: string, displayOrder?: number, urlTemplate?: string) =>
      api.post<unknown>(url(projectId), { name, display_order: displayOrder ?? null, ...(urlTemplate ? { url_template: urlTemplate } : {}) }),
    override: (projectId: string, typeRefId: string, values: ProjectTypeOverride) =>
      api.put<unknown>(`${url(projectId)}/${typeRefId}`, values),
    delete: (projectId: string, typeRefId: string) => api.delete<void>(`${url(projectId)}/${typeRefId}`),
    listHidden: (projectId: string) => api.get<HiddenDefinition[]>(`${url(projectId)}/hidden`),
    restore: (projectId: string, orgTypeIds?: string[]) =>
      api.post<unknown>(`${url(projectId)}/restore`, { org_type_ids: orgTypeIds ?? null }),
  };
}

/**
 * @param url The list's address for one organisation (`/api/v1/orgs/{id}/external-systems`).
 * @returns The organisation-tier calls: list, add, move up or down, change (name, active flag, link pattern) and delete.
 */
export function orgVocabularyApi(url: (organizationId: string) => string) {
  return {
    list: (organizationId: string) => api.get<OrgTypeRow[]>(url(organizationId)),
    create: (organizationId: string, name: string, urlTemplate?: string) =>
      api.post<OrgTypeRow>(url(organizationId), { name, ...(urlTemplate ? { url_template: urlTemplate } : {}) }),
    move: (organizationId: string, typeId: string, direction: "up" | "down") =>
      api.post<OrgTypeRow>(`${url(organizationId)}/${typeId}/move`, { direction }),
    update: (organizationId: string, typeId: string, values: { name?: string; is_active?: boolean; url_template?: string | null }) =>
      api.patch<OrgTypeRow>(`${url(organizationId)}/${typeId}`, values),
    delete: (organizationId: string, typeId: string) => api.delete<void>(`${url(organizationId)}/${typeId}`),
  };
}
