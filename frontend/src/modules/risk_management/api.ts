/**
 * Module: modules/risk_management/api
 *
 * Thin wrappers over `api` (frontend/src/api/client.ts) for the endpoints of
 * `backend/app/modules/risk_management/{project_router,router}.py`: risk CRUD,
 * lifecycle transition, versions, archive, treatment verdicts, reviews, comments
 * and files, plus the two-tier Risk type vocabulary. Relationships are made with
 * the generic artefact-link endpoints (`ArtefactLinksPanel`), not here. `projectId`
 * / `organizationId` parameters match the endpoint's scope.
 */
import { api } from "../../api/client";
import { appendTagParams, type TagListFilters } from "../../api/tags";
import { appendScopeParam, type ScopeListFilters } from "../../api/projectScope";
import type { FileAsset } from "../../api/types";
import type { HiddenDefinition } from "../../components/RestoreOrgDefaultsButton";
import type { EffectiveTypeRow, OrgTypeRow } from "../../components/TypeVocabularyPanels";
import type {
  Risk,
  RiskComment,
  RiskFieldValues,
  RiskReview,
  RiskReviewValues,
  RiskStatus,
  RiskTreatment,
  RiskTreatmentList,
  RiskUpdateValues,
  RiskVersion,
  TreatmentAssessmentStatus,
} from "./types";

const projectBase = (projectId: string) => `/api/v1/projects/${projectId}/modules/risk_management`;
const orgBase = (organizationId: string) => `/api/v1/orgs/${organizationId}/modules/risk_management`;
const riskUrl = (projectId: string, riskId: string) => `${projectBase(projectId)}/risks/${riskId}`;

/** Optional filters of the register list. */
export interface RiskListFilters extends TagListFilters, ScopeListFilters {
  include_archived?: boolean;
  effectively_treated?: boolean;
  review_overdue?: boolean;
}

export const riskApi = {
  list(projectId: string, filters: RiskListFilters = {}) {
    const params = new URLSearchParams();
    if (filters.include_archived) params.set("include_archived", "true");
    if (filters.effectively_treated !== undefined) params.set("effectively_treated", String(filters.effectively_treated));
    if (filters.review_overdue !== undefined) params.set("review_overdue", String(filters.review_overdue));
    appendTagParams(params, filters);
    appendScopeParam(params, filters);
    const query = params.toString();
    return api.get<Risk[]>(`${projectBase(projectId)}/risks${query ? `?${query}` : ""}`);
  },
  create: (projectId: string, values: RiskFieldValues) => api.post<Risk>(`${projectBase(projectId)}/risks`, values),
  get: (projectId: string, riskId: string) => api.get<Risk>(riskUrl(projectId, riskId)),
  update: (projectId: string, riskId: string, values: RiskUpdateValues) => api.put<Risk>(riskUrl(projectId, riskId), values),
  listVersions: (projectId: string, riskId: string) => api.get<RiskVersion[]>(`${riskUrl(projectId, riskId)}/versions`),
  transition: (projectId: string, riskId: string, status: RiskStatus, comment: string) =>
    api.post<Risk>(`${riskUrl(projectId, riskId)}/transition`, { status, comment }),
  archive: (projectId: string, riskId: string) => api.post<Risk>(`${riskUrl(projectId, riskId)}/archive`),
  unarchive: (projectId: string, riskId: string) => api.post<Risk>(`${riskUrl(projectId, riskId)}/unarchive`),

  listTreatments: (projectId: string, riskId: string) => api.get<RiskTreatmentList>(`${riskUrl(projectId, riskId)}/treatments`),
  assessTreatment: (projectId: string, riskId: string, linkId: string, status: TreatmentAssessmentStatus, rationale: string) =>
    api.put<RiskTreatment>(`${riskUrl(projectId, riskId)}/treatments/${linkId}`, { status, rationale }),

  listReviews: (projectId: string, riskId: string) => api.get<RiskReview[]>(`${riskUrl(projectId, riskId)}/reviews`),
  recordReview: (projectId: string, riskId: string, values: RiskReviewValues) =>
    api.post<RiskReview>(`${riskUrl(projectId, riskId)}/reviews`, values),

  // Shape expected by the shared `RecordDiscussion` (`id` is the project id).
  listComments: (projectId: string, riskId: string) => api.get<RiskComment[]>(`${riskUrl(projectId, riskId)}/comments`),
  addComment: (projectId: string, riskId: string, body: string) =>
    api.post<RiskComment>(`${riskUrl(projectId, riskId)}/comments`, { body }),
  editComment: (projectId: string, riskId: string, commentId: string, body: string) =>
    api.patch<RiskComment>(`${riskUrl(projectId, riskId)}/comments/${commentId}`, { body }),
  uploadCommentAttachment: (projectId: string, riskId: string, commentId: string, file: File) =>
    api.postFile<FileAsset>(`${riskUrl(projectId, riskId)}/comments/${commentId}/files`, file),
  removeCommentAttachment: (projectId: string, riskId: string, commentId: string, fileId: string) =>
    api.delete<void>(`${riskUrl(projectId, riskId)}/comments/${commentId}/files/${fileId}`),
  listFiles: (projectId: string, riskId: string) => api.get<FileAsset[]>(`${riskUrl(projectId, riskId)}/files`),
  uploadFile: (projectId: string, riskId: string, file: File) =>
    api.postFile<FileAsset>(`${riskUrl(projectId, riskId)}/files`, file),
  unlinkFile: (projectId: string, riskId: string, fileId: string) =>
    api.delete<void>(`${riskUrl(projectId, riskId)}/files/${fileId}`),

  // Project tier of the type vocabulary (shape expected by `ProjectTypeVocabularyPanel`).
  listTypes: (projectId: string) => api.get<EffectiveTypeRow[]>(`${projectBase(projectId)}/risk-types`),
  createLocalType: (projectId: string, name: string, displayOrder?: number) =>
    api.post<unknown>(`${projectBase(projectId)}/risk-types`, { name, display_order: displayOrder ?? null }),
  overrideType: (
    projectId: string, typeRefId: string,
    values: { name?: string | null; display_order?: number | null; is_enabled?: boolean | null },
  ) => api.put<unknown>(`${projectBase(projectId)}/risk-types/${typeRefId}`, values),
  deleteType: (projectId: string, typeRefId: string) =>
    api.delete<void>(`${projectBase(projectId)}/risk-types/${typeRefId}`),
  listHiddenTypes: (projectId: string) => api.get<HiddenDefinition[]>(`${projectBase(projectId)}/risk-types/hidden`),
  restoreTypes: (projectId: string, orgTypeIds?: string[]) =>
    api.post<unknown>(`${projectBase(projectId)}/risk-types/restore`, { org_type_ids: orgTypeIds ?? null }),
};

/** Org tier of the type vocabulary (shape expected by `OrgTypeVocabularyPanel`); `id` parameters are an `organization_id`. */
export const orgRiskTypeApi = {
  list: (organizationId: string) => api.get<OrgTypeRow[]>(`${orgBase(organizationId)}/risk-types`),
  create: (organizationId: string, name: string) => api.post<OrgTypeRow>(`${orgBase(organizationId)}/risk-types`, { name }),
  move: (organizationId: string, typeId: string, direction: "up" | "down") =>
    api.post<OrgTypeRow>(`${orgBase(organizationId)}/risk-types/${typeId}/move`, { direction }),
  update: (organizationId: string, typeId: string, values: { name?: string; is_active?: boolean }) =>
    api.patch<OrgTypeRow>(`${orgBase(organizationId)}/risk-types/${typeId}`, values),
  delete: (organizationId: string, typeId: string) => api.delete<void>(`${orgBase(organizationId)}/risk-types/${typeId}`),
};
