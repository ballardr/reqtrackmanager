/**
 * Module: modules/decisions/api
 *
 * Thin wrapper functions over `api` (frontend/src/api/client.ts) for every
 * endpoint `backend/app/modules/decisions/{project_router,router}.py`
 * exposes — mirrors `modules/compliance/api.ts`'s own dedicated-per-module-
 * file precedent (that file's own docstring notes this isn't a repo-wide
 * requirement, just reasonable once a module's endpoint surface is large
 * enough that inline `api.get(...)` calls at every call site would repeat
 * the same path-building logic many times over; Decision Management's ~30
 * endpoints clear that bar the same way Compliance's did).
 */
import { api } from "../../api/client";
import type { FileAsset } from "../../api/types";
import type {
  Decision,
  DecisionComment,
  DecisionDecisionLinkKind,
  DecisionFieldValues,
  DecisionLink,
  DecisionRequirementLinkKind,
  DecisionStatus,
  DecisionTemplate,
  DecisionTemplateFieldValues,
  DecisionTypeDefinition,
} from "./types";

const projectBase = (projectId: string) => `/api/v1/projects/${projectId}/modules/decisions`;
const orgBase = (organizationId: string) => `/api/v1/orgs/${organizationId}/modules/decisions`;

// --- Decision Types (project-scoped) ------------------------------------------

export function listDecisionTypes(projectId: string) {
  return api.get<DecisionTypeDefinition[]>(`${projectBase(projectId)}/decision-types`);
}

export function createDecisionType(projectId: string, name: string) {
  return api.post<DecisionTypeDefinition>(`${projectBase(projectId)}/decision-types`, { name });
}

export function renameDecisionType(projectId: string, decisionTypeId: string, name: string) {
  return api.patch<DecisionTypeDefinition>(`${projectBase(projectId)}/decision-types/${decisionTypeId}`, { name });
}

export function moveDecisionType(projectId: string, decisionTypeId: string, direction: "up" | "down") {
  return api.post<DecisionTypeDefinition>(`${projectBase(projectId)}/decision-types/${decisionTypeId}/move`, { direction });
}

export function deleteDecisionType(projectId: string, decisionTypeId: string, reassignToId?: string) {
  return api.delete<void>(
    `${projectBase(projectId)}/decision-types/${decisionTypeId}${reassignToId ? `?reassign_to_id=${reassignToId}` : ""}`
  );
}

// --- Decisions: CRUD -----------------------------------------------------------

export interface DecisionListFilters {
  decision_type_id?: string;
  status?: DecisionStatus;
  owner_id?: string;
  decision_maker_id?: string;
  search?: string;
  include_archived?: boolean;
}

export function listDecisions(projectId: string, filters: DecisionListFilters = {}) {
  const params = new URLSearchParams();
  if (filters.decision_type_id) params.set("decision_type_id", filters.decision_type_id);
  if (filters.status) params.set("status", filters.status);
  if (filters.owner_id) params.set("owner_id", filters.owner_id);
  if (filters.decision_maker_id) params.set("decision_maker_id", filters.decision_maker_id);
  if (filters.search) params.set("search", filters.search);
  if (filters.include_archived) params.set("include_archived", "true");
  const query = params.toString();
  return api.get<Decision[]>(`${projectBase(projectId)}${query ? `?${query}` : ""}`);
}

export function createDecision(projectId: string, values: DecisionFieldValues) {
  return api.post<Decision>(projectBase(projectId), values);
}

export function getDecision(projectId: string, decisionId: string) {
  return api.get<Decision>(`${projectBase(projectId)}/${decisionId}`);
}

export function updateDecision(projectId: string, decisionId: string, values: DecisionFieldValues) {
  return api.put<Decision>(`${projectBase(projectId)}/${decisionId}`, values);
}

export function archiveDecision(projectId: string, decisionId: string) {
  return api.post<Decision>(`${projectBase(projectId)}/${decisionId}/archive`);
}

export function unarchiveDecision(projectId: string, decisionId: string) {
  return api.post<Decision>(`${projectBase(projectId)}/${decisionId}/unarchive`);
}

// --- Lifecycle transitions ------------------------------------------------------

export function proposeDecision(projectId: string, decisionId: string) {
  return api.post<Decision>(`${projectBase(projectId)}/${decisionId}/propose`);
}

export function submitDecisionForReview(projectId: string, decisionId: string) {
  return api.post<Decision>(`${projectBase(projectId)}/${decisionId}/submit-for-review`);
}

export function approveDecision(projectId: string, decisionId: string, comment?: string) {
  return api.post<Decision>(`${projectBase(projectId)}/${decisionId}/approve`, { comment: comment || null });
}

export function rejectDecision(projectId: string, decisionId: string, comment: string) {
  return api.post<Decision>(`${projectBase(projectId)}/${decisionId}/reject`, { comment });
}

// --- Relationships ---------------------------------------------------------------

export function listDecisionRelationships(projectId: string, decisionId: string) {
  return api.get<DecisionLink[]>(`${projectBase(projectId)}/${decisionId}/relationships`);
}

export function createSupersession(projectId: string, newDecisionId: string, oldDecisionId: string) {
  return api.post<DecisionLink>(`${projectBase(projectId)}/${newDecisionId}/supersessions`, {
    old_decision_id: oldDecisionId,
  });
}

export function createDecisionRequirementLink(
  projectId: string, decisionId: string, requirementId: string, kind: DecisionRequirementLinkKind
) {
  return api.post<DecisionLink>(`${projectBase(projectId)}/${decisionId}/requirement-links`, {
    requirement_id: requirementId, kind,
  });
}

export function createDecisionDecisionLink(
  projectId: string, decisionId: string, targetDecisionId: string, kind: DecisionDecisionLinkKind
) {
  return api.post<DecisionLink>(`${projectBase(projectId)}/${decisionId}/decision-links`, {
    target_decision_id: targetDecisionId, kind,
  });
}

// --- Comments ----------------------------------------------------------------

export function listDecisionComments(projectId: string, decisionId: string) {
  return api.get<DecisionComment[]>(`${projectBase(projectId)}/${decisionId}/comments`);
}

export function addDecisionComment(projectId: string, decisionId: string, body: string) {
  return api.post<DecisionComment>(`${projectBase(projectId)}/${decisionId}/comments`, { body });
}

export function editDecisionComment(projectId: string, decisionId: string, commentId: string, body: string) {
  return api.patch<DecisionComment>(`${projectBase(projectId)}/${decisionId}/comments/${commentId}`, { body });
}

export function uploadDecisionCommentAttachment(projectId: string, decisionId: string, commentId: string, file: File) {
  return api.postFile<FileAsset>(`${projectBase(projectId)}/${decisionId}/comments/${commentId}/files`, file);
}

export function removeDecisionCommentAttachment(projectId: string, decisionId: string, commentId: string, fileId: string) {
  return api.delete<void>(`${projectBase(projectId)}/${decisionId}/comments/${commentId}/files/${fileId}`);
}

// --- Direct file attachments -----------------------------------------------------

export function listDecisionFiles(projectId: string, decisionId: string) {
  return api.get<FileAsset[]>(`${projectBase(projectId)}/${decisionId}/files`);
}

export function uploadDecisionFile(projectId: string, decisionId: string, file: File) {
  return api.postFile<FileAsset>(`${projectBase(projectId)}/${decisionId}/files`, file);
}

export function unlinkDecisionFile(projectId: string, decisionId: string, fileId: string) {
  return api.delete<void>(`${projectBase(projectId)}/${decisionId}/files/${fileId}`);
}

// --- Decision Templates (org-scoped) ----------------------------------------------

export function listDecisionTemplates(organizationId: string) {
  return api.get<DecisionTemplate[]>(`${orgBase(organizationId)}/templates`);
}

export function createDecisionTemplate(organizationId: string, values: DecisionTemplateFieldValues) {
  return api.post<DecisionTemplate>(`${orgBase(organizationId)}/templates`, values);
}

export function updateDecisionTemplate(organizationId: string, templateId: string, values: DecisionTemplateFieldValues) {
  return api.patch<DecisionTemplate>(`${orgBase(organizationId)}/templates/${templateId}`, values);
}

export function deleteDecisionTemplate(organizationId: string, templateId: string) {
  return api.delete<void>(`${orgBase(organizationId)}/templates/${templateId}`);
}
