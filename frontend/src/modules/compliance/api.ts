/**
 * Module: modules/compliance/api
 *
 * Thin request functions for the Compliance Module's org-router endpoints
 * (`backend/app/modules/compliance/router.py`, mounted at
 * `/api/v1/orgs/{organization_id}/modules/compliance`) that Phase 12's
 * org-level management UI calls: standards CRUD, standard-version
 * CRUD/publish/retire (incl. cloning), the requirement tree, required
 * actions, the two extensible vocabularies (action types, mapping
 * relationship types), cross-standard requirement mappings, and the
 * version-diff endpoint (Phase 11, §27).
 *
 * This codebase has no general "one API file per feature" convention —
 * every other page calls `api.get/post/...` directly inline
 * (`frontend/src/api/client.ts`). A dedicated file is used here purely
 * because of this module's sheer endpoint count (40+) — every function below
 * is a direct, uninteresting pass-through to `api.*`, kept together so
 * `ComplianceAdminPanel.tsx` and its children read as UI logic, not fetch
 * plumbing. Deliberately NOT a generic per-module convention this repo now
 * expects elsewhere — see docs/compliance-module-plan.md's Phase 12 notes.
 *
 * Endpoints intentionally NOT covered here (out of Phase 12's own scope,
 * confirmed against docs/compliance-module-plan.md's Phase 12 spec and the
 * requirements doc's §2-§6/§19 vs. §7-§10/§12/§17/§21-23 split): standard
 * reviews (§17, Phase 13/14 territory), project-compliance
 * assignment/archive (§7, explicitly Phase 13), and everything on
 * `project_router.py` (assessment, evidence, approval, migration — Phase
 * 13).
 */
import { api } from "../../api/client";
import type {
  ComplianceActionType,
  ComplianceMappingRelationshipType,
  ComplianceRequiredAction,
  ComplianceRequirement,
  ComplianceRequirementMapping,
  ComplianceRequirementNode,
  ComplianceStandard,
  ComplianceStandardVersion,
  StandardVersionDiff,
} from "./types";

function base(orgId: string): string {
  return `/api/v1/orgs/${orgId}/modules/compliance`;
}

// --- Standards ---------------------------------------------------------------

export function listStandards(orgId: string, includeArchived = false): Promise<ComplianceStandard[]> {
  return api.get(`${base(orgId)}/standards?include_archived=${includeArchived}`);
}

export function createStandard(
  orgId: string,
  payload: { reference: string; name: string; description?: string; issuing_organisation?: string | null; owner_id?: string | null }
): Promise<ComplianceStandard> {
  return api.post(`${base(orgId)}/standards`, payload);
}

export function updateStandard(
  orgId: string,
  standardId: string,
  payload: { name: string; description?: string; issuing_organisation?: string | null; owner_id: string }
): Promise<ComplianceStandard> {
  return api.patch(`${base(orgId)}/standards/${standardId}`, payload);
}

export function archiveStandard(orgId: string, standardId: string): Promise<ComplianceStandard> {
  return api.post(`${base(orgId)}/standards/${standardId}/archive`);
}

export function unarchiveStandard(orgId: string, standardId: string): Promise<ComplianceStandard> {
  return api.post(`${base(orgId)}/standards/${standardId}/unarchive`);
}

// --- Standard versions ---------------------------------------------------------

export function listStandardVersions(orgId: string, standardId: string): Promise<ComplianceStandardVersion[]> {
  return api.get(`${base(orgId)}/standards/${standardId}/versions`);
}

export function createStandardVersion(
  orgId: string,
  standardId: string,
  payload: { version_label: string; effective_date?: string | null; change_note?: string; clone_from_version_id?: string | null }
): Promise<ComplianceStandardVersion> {
  return api.post(`${base(orgId)}/standards/${standardId}/versions`, payload);
}

export function publishStandardVersion(orgId: string, standardId: string, versionId: string): Promise<ComplianceStandardVersion> {
  return api.post(`${base(orgId)}/standards/${standardId}/versions/${versionId}/publish`);
}

export function retireStandardVersion(orgId: string, standardId: string, versionId: string): Promise<ComplianceStandardVersion> {
  return api.post(`${base(orgId)}/standards/${standardId}/versions/${versionId}/retire`);
}

// --- Requirements ---------------------------------------------------------------

function requirementsBase(orgId: string, standardId: string, versionId: string): string {
  return `${base(orgId)}/standards/${standardId}/versions/${versionId}/requirements`;
}

export function listRequirements(orgId: string, standardId: string, versionId: string): Promise<ComplianceRequirement[]> {
  return api.get(requirementsBase(orgId, standardId, versionId));
}

export function createRequirement(
  orgId: string,
  standardId: string,
  versionId: string,
  payload: { parent_requirement_id?: string | null; reference?: string | null; name: string; description?: string; reasoning?: string }
): Promise<ComplianceRequirement> {
  return api.post(requirementsBase(orgId, standardId, versionId), payload);
}

export function updateRequirement(
  orgId: string,
  standardId: string,
  versionId: string,
  requirementId: string,
  payload: { reference?: string | null; name: string; description?: string; reasoning?: string }
): Promise<ComplianceRequirement> {
  return api.patch(`${requirementsBase(orgId, standardId, versionId)}/${requirementId}`, payload);
}

export function deleteRequirement(orgId: string, standardId: string, versionId: string, requirementId: string): Promise<void> {
  return api.delete(`${requirementsBase(orgId, standardId, versionId)}/${requirementId}`);
}

export function moveRequirement(
  orgId: string,
  standardId: string,
  versionId: string,
  requirementId: string,
  direction: "up" | "down"
): Promise<ComplianceRequirement> {
  return api.post(`${requirementsBase(orgId, standardId, versionId)}/${requirementId}/move`, { direction });
}

// --- Required actions -------------------------------------------------------------

function requiredActionsBase(orgId: string, standardId: string, versionId: string, requirementId: string): string {
  return `${requirementsBase(orgId, standardId, versionId)}/${requirementId}/required-actions`;
}

export function listRequiredActions(
  orgId: string, standardId: string, versionId: string, requirementId: string
): Promise<ComplianceRequiredAction[]> {
  return api.get(requiredActionsBase(orgId, standardId, versionId, requirementId));
}

export function createRequiredAction(
  orgId: string, standardId: string, versionId: string, requirementId: string,
  payload: { action_type_id: string; name: string; description?: string; is_mandatory?: boolean }
): Promise<ComplianceRequiredAction> {
  return api.post(requiredActionsBase(orgId, standardId, versionId, requirementId), payload);
}

export function updateRequiredAction(
  orgId: string, standardId: string, versionId: string, requirementId: string, actionId: string,
  payload: { action_type_id: string; name: string; description?: string; is_mandatory?: boolean }
): Promise<ComplianceRequiredAction> {
  return api.patch(`${requiredActionsBase(orgId, standardId, versionId, requirementId)}/${actionId}`, payload);
}

export function deleteRequiredAction(
  orgId: string, standardId: string, versionId: string, requirementId: string, actionId: string
): Promise<void> {
  return api.delete(`${requiredActionsBase(orgId, standardId, versionId, requirementId)}/${actionId}`);
}

export function moveRequiredAction(
  orgId: string, standardId: string, versionId: string, requirementId: string, actionId: string, direction: "up" | "down"
): Promise<ComplianceRequiredAction> {
  return api.post(`${requiredActionsBase(orgId, standardId, versionId, requirementId)}/${actionId}/move`, { direction });
}

// --- Action types (org-scoped vocabulary) ---------------------------------------

export function listActionTypes(orgId: string): Promise<ComplianceActionType[]> {
  return api.get(`${base(orgId)}/action-types`);
}

export function createActionType(orgId: string, name: string): Promise<ComplianceActionType> {
  return api.post(`${base(orgId)}/action-types`, { name });
}

export function renameActionType(orgId: string, id: string, name: string): Promise<ComplianceActionType> {
  return api.patch(`${base(orgId)}/action-types/${id}`, { name });
}

export function moveActionType(orgId: string, id: string, direction: "up" | "down"): Promise<ComplianceActionType> {
  return api.post(`${base(orgId)}/action-types/${id}/move`, { direction });
}

export function deleteActionType(orgId: string, id: string, reassignToId?: string): Promise<void> {
  const qs = reassignToId ? `?reassign_to_id=${reassignToId}` : "";
  return api.delete(`${base(orgId)}/action-types/${id}${qs}`);
}

// --- Mapping relationship types (org-scoped vocabulary) -------------------------

export function listMappingRelationshipTypes(orgId: string): Promise<ComplianceMappingRelationshipType[]> {
  return api.get(`${base(orgId)}/mapping-relationship-types`);
}

export function createMappingRelationshipType(
  orgId: string, name: string, impliesEquivalence: boolean
): Promise<ComplianceMappingRelationshipType> {
  return api.post(`${base(orgId)}/mapping-relationship-types`, { name, implies_equivalence: impliesEquivalence });
}

export function updateMappingRelationshipType(
  orgId: string, id: string, name: string, impliesEquivalence: boolean
): Promise<ComplianceMappingRelationshipType> {
  return api.patch(`${base(orgId)}/mapping-relationship-types/${id}`, { name, implies_equivalence: impliesEquivalence });
}

export function moveMappingRelationshipType(orgId: string, id: string, direction: "up" | "down"): Promise<ComplianceMappingRelationshipType> {
  return api.post(`${base(orgId)}/mapping-relationship-types/${id}/move`, { direction });
}

export function deleteMappingRelationshipType(orgId: string, id: string, reassignToId?: string): Promise<void> {
  const qs = reassignToId ? `?reassign_to_id=${reassignToId}` : "";
  return api.delete(`${base(orgId)}/mapping-relationship-types/${id}${qs}`);
}

// --- Requirement mappings (§19) --------------------------------------------------

export function listMappingsForRequirement(
  orgId: string, standardId: string, versionId: string, requirementId: string, includeArchived = false
): Promise<ComplianceRequirementMapping[]> {
  return api.get(
    `${requirementsBase(orgId, standardId, versionId)}/${requirementId}/mappings?include_archived=${includeArchived}`
  );
}

export function createRequirementMapping(
  orgId: string,
  payload: { from_requirement_id: string; to_requirement_id: string; relationship_type_id: string; notes?: string }
): Promise<ComplianceRequirementMapping> {
  return api.post(`${base(orgId)}/requirement-mappings`, payload);
}

export function archiveRequirementMapping(orgId: string, mappingId: string): Promise<ComplianceRequirementMapping> {
  return api.post(`${base(orgId)}/requirement-mappings/${mappingId}/archive`);
}

export function unarchiveRequirementMapping(orgId: string, mappingId: string): Promise<ComplianceRequirementMapping> {
  return api.post(`${base(orgId)}/requirement-mappings/${mappingId}/unarchive`);
}

// --- Version diff (Phase 11, §27) ------------------------------------------------

export function getStandardVersionDiff(
  orgId: string, standardId: string, versionId: string, otherVersionId: string
): Promise<StandardVersionDiff> {
  return api.get(`${base(orgId)}/standards/${standardId}/versions/${versionId}/diff/${otherVersionId}`);
}

// --- Client-side tree assembly ----------------------------------------------------

/**
 * Builds a parent/child tree from the backend's flat, depth-first-ordered
 * `GET .../requirements` list (`parent_requirement_id` populated on each
 * row) — there is no nested-tree endpoint (confirmed against
 * `router.py::_flatten_requirements_dfs`; see this module's own research
 * notes in docs/compliance-module-plan.md's Phase 12 notes). Mirrors that
 * backend algorithm: group by `parent_requirement_id`, each group already
 * arrives `sort_order`-ordered courtesy of the backend's own DFS emission,
 * so no client-side re-sort is needed — this just re-nests the already-
 * correctly-ordered flat list.
 */
export function buildRequirementTree(flat: ComplianceRequirement[]): ComplianceRequirementNode[] {
  const byParent = new Map<string | null, ComplianceRequirement[]>();
  for (const req of flat) {
    const key = req.parent_requirement_id;
    const list = byParent.get(key) ?? [];
    list.push(req);
    byParent.set(key, list);
  }
  function build(parentId: string | null, depth: number): ComplianceRequirementNode[] {
    return (byParent.get(parentId) ?? []).map((req) => ({
      ...req,
      depth,
      children: build(req.id, depth + 1),
    }));
  }
  return build(null, 0);
}
