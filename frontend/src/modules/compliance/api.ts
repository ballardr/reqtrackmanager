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
 * version-diff endpoint (Phase 11, §27) — plus, since Phase 13, the
 * project-router endpoints (`project_router.py`, mounted at
 * `/api/v1/projects/{project_id}/modules/compliance`) the Project
 * Compliance View needs: assignment viewing, per-requirement applicability/
 * assessment/approval, required-action assessments, evidence CRUD/
 * linkage/files, and scheduled reviews. Standard-to-project *assignment
 * itself* (`POST .../projects/{project_id}/project-compliance`) stays on
 * the org router per `router.py`'s own "assigning is a Compliance Manager
 * decision" design (Phase 7 notes) even though the calling UI is
 * project-scoped — see the "Assignment (org router)" section below.
 *
 * This codebase has no general "one API file per feature" convention —
 * every other page calls `api.get/post/...` directly inline
 * (`frontend/src/api/client.ts`). A dedicated file is used here purely
 * because of this module's sheer endpoint count (70+) — every function below
 * is a direct, uninteresting pass-through to `api.*`, kept together so
 * `ComplianceAdminPanel.tsx`/`ProjectCompliancePage.tsx` and their children
 * read as UI logic, not fetch plumbing. Deliberately NOT a generic
 * per-module convention this repo now expects elsewhere — see
 * docs/compliance-module-plan.md's Phase 12 notes.
 *
 * Phase 18 ("Compliance Standards" as a first-class, cross-org, project-like
 * nav entity) adds the two global (no org/project id in the path) endpoints
 * at the top of this file — `getNavVisibility`/`getStandardById` — plus
 * `getStandardHistory` (an org-router addition, `router.py`'s new
 * `GET .../standards/{id}/history`, mirroring `getRequirementHistory`'s
 * existing shape) for the new `/standards/:standardId` workspace's
 * "History" section.
 *
 * Phase 21 (standard-level import/export) adds `exportStandard`/
 * `importStandard` — `exportStandard` returns a `Blob` (`api.getForBlob`,
 * the same shape `OrgComplianceDashboard.tsx`'s report downloads already
 * use) rather than parsed JSON, since the caller only ever hands it
 * straight to `downloadBlob`; `importStandard` uploads via `api.postFile`,
 * the same helper `ProjectListPage.tsx`'s own project-bundle import uses.
 *
 * Endpoints intentionally NOT covered here (out of this phase's own scope):
 * the project-scoped version-migration action (§27, `migrate-version`) —
 * deliberately not built into this phase's UI either, a flagged scope trim
 * recorded in docs/compliance-module-plan.md's Phase 13 notes, mirroring how
 * Phase 12 flagged owner reassignment rather than silently omitting it.
 */
import { api, ApiError } from "../../api/client";
import type { Organization } from "../../api/types";
import type {
  ComplianceActionType,
  ComplianceAuditEvent,
  ComplianceEvidence,
  ComplianceEvidenceRevalidation,
  ComplianceMappingRelationshipType,
  ComplianceOrgSettings,
  ComplianceRecentActivity,
  ComplianceRequiredAction,
  ComplianceRequiredActionAssessment,
  ComplianceRequirement,
  ComplianceRequirementMapping,
  ComplianceRequirementNode,
  ComplianceReview,
  ComplianceStandard,
  ComplianceStandardApplicabilityDefault,
  ComplianceStandardDefaultExclusion,
  ComplianceStandardMembers,
  ComplianceStandardRoleKey,
  ComplianceStandardVersion,
  NonCompliantRequirement,
  OrgExpiringEvidence,
  OrgNonCompliantRequirement,
  OrgPendingApproval,
  OrgReviewDue,
  OutstandingRequiredAction,
  PendingApproval,
  ProjectCompliance,
  ProjectComplianceRequirement,
  ProjectComplianceStatus,
  StandardImportResult,
  StandardVersionDiff,
} from "./types";

function base(orgId: string): string {
  return `/api/v1/orgs/${orgId}/modules/compliance`;
}

function projectBase(projectId: string): string {
  return `/api/v1/projects/${projectId}/modules/compliance`;
}

// --- Phase 18: global (no org/project id in the path) endpoints -----------------
//
// Mounted via `ModuleDefinition.get_global_router` (`backend/app/modules/
// compliance/global_router.py`) at the bare `/api/v1/compliance` prefix —
// neither endpoint has a single org/project id of its own to key a path
// off (`nav-visibility` aggregates across every org the caller belongs to;
// `getStandardById` resolves a standard's owning org from its own id,
// mirroring how a project's own id already resolves to its org).

export function getNavVisibility(): Promise<{ visible: boolean }> {
  return api.get(`/api/v1/compliance/nav-visibility`);
}

export function getStandardById(standardId: string): Promise<ComplianceStandard> {
  return api.get(`/api/v1/compliance/standards/${standardId}`);
}

// --- Standards ---------------------------------------------------------------

export function listStandards(orgId: string, includeArchived = false): Promise<ComplianceStandard[]> {
  return api.get(`${base(orgId)}/standards?include_archived=${includeArchived}`);
}

export interface StandardAcrossOrgsRow extends ComplianceStandard {
  organization_name: string;
}

/**
 * No cross-org backend listing endpoint exists for standards — every
 * compliance route requires `organization_id` in the path (Phase 6's own
 * design) — so this fans `listStandards` out across every org the caller
 * belongs to in parallel. An org whose call 404s (module disabled there)
 * is dropped silently, matching the 404-not-403 "not entitled/disabled
 * looks the same as not present" posture every other compliance endpoint
 * already gives; a non-404 failure is also dropped (logged, not surfaced)
 * rather than failing the whole caller over one org's own hiccup.
 *
 * Shared by `StandardListPage.tsx` (the cross-org standards directory) and
 * `StandardWorkspacePage.tsx`'s `EntitySwitcher` loader (Phase 28), which
 * both need this exact fan-out rather than duplicating it.
 */
export async function listStandardsAcrossMyOrgs(
  includeArchived = false
): Promise<{ orgs: Organization[]; rows: StandardAcrossOrgsRow[] }> {
  const orgs = (await api.get<Organization[]>("/api/v1/orgs?mine=true")).filter((o) => o.is_active);

  const perOrg = await Promise.allSettled(
    orgs.map(async (org) => {
      const standards = await listStandards(org.id, includeArchived);
      return standards.map((s): StandardAcrossOrgsRow => ({ ...s, organization_name: org.name }));
    })
  );
  const rows: StandardAcrossOrgsRow[] = [];
  for (const result of perOrg) {
    if (result.status === "fulfilled") rows.push(...result.value);
    else if (!(result.reason instanceof ApiError) || result.reason.status !== 404) {
      console.error("Could not load compliance standards for one organisation:", result.reason);
    }
  }
  return { orgs, rows };
}

export function createStandard(
  orgId: string,
  payload: {
    reference: string;
    name: string;
    description?: string;
    issuing_organisation?: string | null;
    owner_id?: string | null;
    initial_version_label: string;
    initial_version_effective_date?: string | null;
    initial_version_change_note?: string;
  }
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

export function getStandardHistory(orgId: string, standardId: string): Promise<ComplianceAuditEvent[]> {
  return api.get(`${base(orgId)}/standards/${standardId}/history`);
}

// --- Phase 23: standard workspace Overview stats --------------------------------

/** This standard's own slice of `listOrgProjectComplianceStatus` — the
 * exact same `ProjectComplianceStatus` rows, narrowed server-side to this
 * one standard, backing the Overview's "Projects"/"Compliant" stat tiles
 * and their filtered drill-down list (`StandardProjectsPanel.tsx`). */
export function getStandardProjectSummary(orgId: string, standardId: string): Promise<ProjectComplianceStatus[]> {
  return api.get(`${base(orgId)}/standards/${standardId}/project-summary`);
}

// --- Phase 21: standard-level import/export -----------------------------------

export function exportStandard(orgId: string, standardId: string): Promise<Blob> {
  return api.getForBlob(`${base(orgId)}/standards/${standardId}/export`);
}

/** `resolution` is only needed on a retry after a 409 (reference collision)
 * — see `StandardImportModal.tsx`'s own docstring. */
export function importStandard(orgId: string, file: File, resolution?: "skip" | "import_as_copy"): Promise<StandardImportResult> {
  return api.postFile(`${base(orgId)}/standards/import`, file, resolution ? { resolution } : undefined);
}

// --- Phase 20: applicability defaults + exceptions (Compliance-Manager-only, ---
// org-scoped — the standard's own governance, distinct from Project-Manager
// self-service assignment below, which lives on the project router).

export function updateStandardApplicabilityDefault(
  orgId: string, standardId: string, applicabilityDefault: ComplianceStandardApplicabilityDefault
): Promise<ComplianceStandard> {
  return api.patch(`${base(orgId)}/standards/${standardId}/applicability-default`, {
    applicability_default: applicabilityDefault,
  });
}

export function listStandardDefaultExclusions(orgId: string, standardId: string): Promise<ComplianceStandardDefaultExclusion[]> {
  return api.get(`${base(orgId)}/standards/${standardId}/exclusions`);
}

export function excludeProjectFromStandardDefault(
  orgId: string, standardId: string, payload: { project_id: string; reason: string }
): Promise<ComplianceStandardDefaultExclusion> {
  return api.post(`${base(orgId)}/standards/${standardId}/exclusions`, payload);
}

export function removeStandardDefaultExclusion(orgId: string, standardId: string, projectId: string): Promise<void> {
  return api.delete(`${base(orgId)}/standards/${standardId}/exclusions/${projectId}`);
}

// --- Phase 22: standard-scoped RBAC (standards_manager/standards_contributor) --

export function getComplianceOrgSettings(orgId: string): Promise<ComplianceOrgSettings> {
  return api.get(`${base(orgId)}/settings`);
}

export function updateComplianceOrgSettings(
  orgId: string, payload: { default_standards_manager_group_id: string | null }
): Promise<ComplianceOrgSettings> {
  return api.put(`${base(orgId)}/settings`, payload);
}

export function listStandardMembers(orgId: string, standardId: string): Promise<ComplianceStandardMembers> {
  return api.get(`${base(orgId)}/standards/${standardId}/members`);
}

export function assignStandardMemberRole(
  orgId: string, standardId: string, userId: string, roleKey: ComplianceStandardRoleKey
): Promise<void> {
  return api.post(`${base(orgId)}/standards/${standardId}/members/${userId}/roles`, { role_key: roleKey });
}

export function revokeStandardMemberRole(
  orgId: string, standardId: string, userId: string, roleKey: ComplianceStandardRoleKey
): Promise<void> {
  return api.delete(`${base(orgId)}/standards/${standardId}/members/${userId}/roles/${roleKey}`);
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

// --- Phase 24: version summary (editable at any lifecycle stage) + ---------------
// post-publish requirement clarification.

export function updateStandardVersion(
  orgId: string, standardId: string, versionId: string, summary: string
): Promise<ComplianceStandardVersion> {
  return api.patch(`${base(orgId)}/standards/${standardId}/versions/${versionId}`, { summary });
}

export function clarifyRequirement(
  orgId: string,
  standardId: string,
  versionId: string,
  requirementId: string,
  payload: { reference?: string | null; name: string; description?: string; reasoning?: string; clarification_note: string }
): Promise<ComplianceRequirement> {
  return api.patch(`${requirementsBase(orgId, standardId, versionId)}/${requirementId}/clarify`, payload);
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

// --- Phase 14: Org Compliance View + Dashboard (§22, §23) -------------------------
//
// Org-wide aggregations across every project in the organisation, all
// `_require_manage`-gated on the backend (§26 — see docs/compliance-module-
// plan.md's Phase 14 notes for why this is manage-, not view-, gated despite
// §22's own looser-sounding "Compliance Managers and authorised users"
// text).

export function listOrgProjectComplianceStatus(orgId: string, includeArchived = false): Promise<ProjectComplianceStatus[]> {
  return api.get(`${base(orgId)}/project-compliance?include_archived=${includeArchived}`);
}

export function listOrgNonCompliantRequirements(orgId: string): Promise<OrgNonCompliantRequirement[]> {
  return api.get(`${base(orgId)}/non-compliant-requirements`);
}

export function listOrgPendingApprovals(orgId: string): Promise<OrgPendingApproval[]> {
  return api.get(`${base(orgId)}/pending-approvals`);
}

export function listOrgOutstandingRequiredActions(orgId: string): Promise<OutstandingRequiredAction[]> {
  return api.get(`${base(orgId)}/outstanding-required-actions`);
}

export function listOrgExpiringEvidence(orgId: string): Promise<OrgExpiringEvidence[]> {
  return api.get(`${base(orgId)}/expiring-evidence`);
}

export function listOrgReviewsDue(orgId: string, includeUpcoming = false): Promise<OrgReviewDue[]> {
  return api.get(`${base(orgId)}/reviews-due?include_upcoming=${includeUpcoming}`);
}

export function listOrgRecentActivity(orgId: string, limit = 20): Promise<ComplianceRecentActivity[]> {
  return api.get(`${base(orgId)}/recent-activity?limit=${limit}`);
}

// --- Phase 14: Project-level outstanding required actions (new alongside the
// org-wide aggregation above; consistent with the existing non-compliant-
// requirements/pending-approvals per-project listing family) ---------------------

export function listOutstandingRequiredActions(projectId: string): Promise<OutstandingRequiredAction[]> {
  return api.get(`${projectBase(projectId)}/outstanding-required-actions`);
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

/**
 * Resolves the `standard_id` that owns a given `standard_version_id` —
 * needed because every org-router requirement-tree endpoint is nested
 * under `/standards/{standard_id}/versions/{version_id}/...` (no
 * standalone "get version by id alone" endpoint exists, confirmed against
 * `router.py`), while `ProjectCompliance` only stores `standard_version_id`.
 * For an *active* assignment the caller already has this for free via
 * `ProjectComplianceStatusOut.standard_id` (`getProjectComplianceStatus`);
 * this fallback is for an *archived* one, which `GET .../status` excludes
 * by design (see that endpoint's own docstring) — a client-side join over
 * this organisation's (typically small) standard/version catalogue rather
 * than a new backend endpoint for what should be a rare path (viewing an
 * archived assignment's own requirement tree).
 */
export async function resolveStandardIdForVersion(orgId: string, standardVersionId: string): Promise<string | null> {
  const standards = await listStandards(orgId, true);
  for (const standard of standards) {
    const versions = await listStandardVersions(orgId, standard.id);
    if (versions.some((v) => v.id === standardVersionId)) return standard.id;
  }
  return null;
}

// --- Phase 13/20: Assignment ---------------------------------------------------
//
// Two endpoints, same payload shape, different callers/routers — Phase 20
// makes the project-scoped one (below) the *default, primary* path, usable
// by a plain Project Manager with no `compliance_officer` grant; this org-
// scoped one (Phase 7's original design, Compliance-Manager-only) remains
// the secondary/administrative path, for a Compliance Manager assigning on
// a project's behalf or in bulk.

export function createProjectCompliance(
  orgId: string, projectId: string,
  payload: { standard_id: string; standard_version_id: string; target_compliance_date?: string | null }
): Promise<ProjectCompliance> {
  return api.post(`${base(orgId)}/projects/${projectId}/project-compliance`, payload);
}

/** Phase 20's default, primary assignment path — project-scoped,
 * `_require_officer`-gated (`compliance_officer` grant OR
 * `ProjectRole.PROJECT_MANAGER`) — used by `ProjectCompliancePage.tsx`'s
 * own "Assign standard" flow. */
export function createProjectComplianceAsProjectManager(
  projectId: string,
  payload: { standard_id: string; standard_version_id: string; target_compliance_date?: string | null }
): Promise<ProjectCompliance> {
  return api.post(`${projectBase(projectId)}/project-compliance`, payload);
}

export function archiveProjectCompliance(orgId: string, projectId: string, projectComplianceId: string): Promise<ProjectCompliance> {
  return api.post(`${base(orgId)}/projects/${projectId}/project-compliance/${projectComplianceId}/archive`);
}

export function unarchiveProjectCompliance(orgId: string, projectId: string, projectComplianceId: string): Promise<ProjectCompliance> {
  return api.post(`${base(orgId)}/projects/${projectId}/project-compliance/${projectComplianceId}/unarchive`);
}

// --- Phase 13: Project compliance assignments (project router, read + status) ---

export function listProjectCompliance(projectId: string): Promise<ProjectCompliance[]> {
  return api.get(`${projectBase(projectId)}/project-compliance`);
}

export function getProjectComplianceStatus(projectId: string): Promise<ProjectComplianceStatus[]> {
  return api.get(`${projectBase(projectId)}/status`);
}

export function listNonCompliantRequirements(projectId: string): Promise<NonCompliantRequirement[]> {
  return api.get(`${projectBase(projectId)}/non-compliant-requirements`);
}

export function listPendingApprovals(projectId: string): Promise<PendingApproval[]> {
  return api.get(`${projectBase(projectId)}/pending-approvals`);
}

// --- Phase 13: Per-requirement assessment (§8-§10, §12, §16) ---------------------

function pcrBase(projectId: string, projectComplianceId: string): string {
  return `${projectBase(projectId)}/project-compliance/${projectComplianceId}/requirements`;
}

export function listProjectComplianceRequirements(
  projectId: string, projectComplianceId: string
): Promise<ProjectComplianceRequirement[]> {
  return api.get(pcrBase(projectId, projectComplianceId));
}

export function updateRequirementApplicability(
  projectId: string, projectComplianceId: string, pcrId: string,
  payload: { applicability: "applicable" | "not_applicable"; justification?: string }
): Promise<ProjectComplianceRequirement> {
  return api.patch(`${pcrBase(projectId, projectComplianceId)}/${pcrId}/applicability`, payload);
}

export function updateRequirementAssessment(
  projectId: string, projectComplianceId: string, pcrId: string,
  payload: { compliance_status: string; justification?: string; notes?: string }
): Promise<ProjectComplianceRequirement> {
  return api.patch(`${pcrBase(projectId, projectComplianceId)}/${pcrId}/assessment`, payload);
}

export function submitRequirementForApproval(
  projectId: string, projectComplianceId: string, pcrId: string
): Promise<ProjectComplianceRequirement> {
  return api.post(`${pcrBase(projectId, projectComplianceId)}/${pcrId}/submit-for-approval`);
}

export function approveRequirement(
  projectId: string, projectComplianceId: string, pcrId: string, decisionNote = ""
): Promise<ProjectComplianceRequirement> {
  return api.post(`${pcrBase(projectId, projectComplianceId)}/${pcrId}/approve`, { decision_note: decisionNote });
}

export function rejectRequirement(
  projectId: string, projectComplianceId: string, pcrId: string, decisionNote: string
): Promise<ProjectComplianceRequirement> {
  return api.post(`${pcrBase(projectId, projectComplianceId)}/${pcrId}/reject`, { decision_note: decisionNote });
}

export function getRequirementHistory(
  projectId: string, projectComplianceId: string, pcrId: string
): Promise<ComplianceAuditEvent[]> {
  return api.get(`${pcrBase(projectId, projectComplianceId)}/${pcrId}/history`);
}

export function listRequirementEvidence(
  projectId: string, projectComplianceId: string, pcrId: string
): Promise<ComplianceEvidence[]> {
  return api.get(`${pcrBase(projectId, projectComplianceId)}/${pcrId}/evidence`);
}

// --- Phase 13: Required action assessments (§6/§25) ------------------------------

function assessmentsBase(projectId: string, projectComplianceId: string, pcrId: string): string {
  return `${pcrBase(projectId, projectComplianceId)}/${pcrId}/required-action-assessments`;
}

export function listRequiredActionAssessments(
  projectId: string, projectComplianceId: string, pcrId: string
): Promise<ComplianceRequiredActionAssessment[]> {
  return api.get(assessmentsBase(projectId, projectComplianceId, pcrId));
}

export function updateRequiredActionAssessment(
  projectId: string, projectComplianceId: string, pcrId: string, assessmentId: string,
  payload: { assignee_id?: string | null; due_date?: string | null; notes?: string }
): Promise<ComplianceRequiredActionAssessment> {
  return api.patch(`${assessmentsBase(projectId, projectComplianceId, pcrId)}/${assessmentId}`, payload);
}

export function completeRequiredActionAssessment(
  projectId: string, projectComplianceId: string, pcrId: string, assessmentId: string
): Promise<ComplianceRequiredActionAssessment> {
  return api.post(`${assessmentsBase(projectId, projectComplianceId, pcrId)}/${assessmentId}/complete`);
}

export function uncompleteRequiredActionAssessment(
  projectId: string, projectComplianceId: string, pcrId: string, assessmentId: string
): Promise<ComplianceRequiredActionAssessment> {
  return api.post(`${assessmentsBase(projectId, projectComplianceId, pcrId)}/${assessmentId}/uncomplete`);
}

export function listRequiredActionAssessmentEvidence(
  projectId: string, projectComplianceId: string, pcrId: string, assessmentId: string
): Promise<ComplianceEvidence[]> {
  return api.get(`${assessmentsBase(projectId, projectComplianceId, pcrId)}/${assessmentId}/evidence`);
}

// --- Phase 13: Evidence (§13-§15) -------------------------------------------------

export function createEvidence(
  projectId: string,
  payload: {
    title: string; description?: string; issuing_organisation?: string | null; issued_date?: string | null;
    expiry_date?: string | null; notes?: string; project_compliance_requirement_ids?: string[];
    required_action_assessment_ids?: string[];
  }
): Promise<ComplianceEvidence> {
  return api.post(`${projectBase(projectId)}/evidence`, payload);
}

export function listEvidence(projectId: string): Promise<ComplianceEvidence[]> {
  return api.get(`${projectBase(projectId)}/evidence`);
}

export function getExpiringEvidence(projectId: string): Promise<ComplianceEvidence[]> {
  return api.get(`${projectBase(projectId)}/expiring-evidence`);
}

export function updateEvidence(
  projectId: string, evidenceId: string,
  payload: { title: string; description?: string; issuing_organisation?: string | null; issued_date?: string | null; notes?: string }
): Promise<ComplianceEvidence> {
  return api.patch(`${projectBase(projectId)}/evidence/${evidenceId}`, payload);
}

export function archiveEvidence(projectId: string, evidenceId: string): Promise<ComplianceEvidence> {
  return api.post(`${projectBase(projectId)}/evidence/${evidenceId}/archive`);
}

export function unarchiveEvidence(projectId: string, evidenceId: string): Promise<ComplianceEvidence> {
  return api.post(`${projectBase(projectId)}/evidence/${evidenceId}/unarchive`);
}

export function revalidateEvidence(
  projectId: string, evidenceId: string, payload: { new_expiry_date?: string | null; justification?: string }
): Promise<ComplianceEvidence> {
  return api.post(`${projectBase(projectId)}/evidence/${evidenceId}/revalidate`, payload);
}

export function listEvidenceRevalidations(projectId: string, evidenceId: string): Promise<ComplianceEvidenceRevalidation[]> {
  return api.get(`${projectBase(projectId)}/evidence/${evidenceId}/revalidations`);
}

export function linkEvidenceToRequirement(projectId: string, evidenceId: string, pcrId: string): Promise<ComplianceEvidence> {
  return api.post(`${projectBase(projectId)}/evidence/${evidenceId}/requirement-links`, { project_compliance_requirement_id: pcrId });
}

export function unlinkEvidenceFromRequirement(projectId: string, evidenceId: string, pcrId: string): Promise<void> {
  return api.delete(`${projectBase(projectId)}/evidence/${evidenceId}/requirement-links/${pcrId}`);
}

export function linkEvidenceToActionAssessment(projectId: string, evidenceId: string, assessmentId: string): Promise<ComplianceEvidence> {
  return api.post(`${projectBase(projectId)}/evidence/${evidenceId}/action-links`, { required_action_assessment_id: assessmentId });
}

export function unlinkEvidenceFromActionAssessment(projectId: string, evidenceId: string, assessmentId: string): Promise<void> {
  return api.delete(`${projectBase(projectId)}/evidence/${evidenceId}/action-links/${assessmentId}`);
}

export function uploadEvidenceAttachment(projectId: string, evidenceId: string, file: File): Promise<import("../../api/types").FileAsset> {
  return api.postFile(`${projectBase(projectId)}/evidence/${evidenceId}/files`, file);
}

export function linkEvidenceOrgResource(projectId: string, evidenceId: string, fileId: string): Promise<import("../../api/types").FileAsset> {
  return api.post(`${projectBase(projectId)}/evidence/${evidenceId}/files/link`, { file_id: fileId });
}

export function listEvidenceFiles(projectId: string, evidenceId: string): Promise<import("../../api/types").FileAsset[]> {
  return api.get(`${projectBase(projectId)}/evidence/${evidenceId}/files`);
}

export function unlinkEvidenceFile(projectId: string, evidenceId: string, fileId: string): Promise<void> {
  return api.delete(`${projectBase(projectId)}/evidence/${evidenceId}/files/${fileId}`);
}

// --- Phase 13: Scheduled reviews, project-level (§17, §18, §28) -----------------

export function createProjectReview(
  projectId: string, projectComplianceId: string,
  payload: { frequency_label: string; recurrence_days?: number | null; next_due_date: string; owner_id?: string | null; notes?: string }
): Promise<ComplianceReview> {
  return api.post(`${projectBase(projectId)}/project-compliance/${projectComplianceId}/reviews`, payload);
}

export function listProjectReviews(projectId: string, projectComplianceId: string): Promise<ComplianceReview[]> {
  return api.get(`${projectBase(projectId)}/project-compliance/${projectComplianceId}/reviews`);
}

export function listReviewsDue(projectId: string): Promise<ComplianceReview[]> {
  return api.get(`${projectBase(projectId)}/reviews-due`);
}

export function updateProjectReview(
  projectId: string, reviewId: string,
  payload: { frequency_label: string; recurrence_days?: number | null; next_due_date: string; owner_id?: string | null; notes?: string }
): Promise<ComplianceReview> {
  return api.patch(`${projectBase(projectId)}/reviews/${reviewId}`, payload);
}

export function deleteProjectReview(projectId: string, reviewId: string): Promise<void> {
  return api.delete(`${projectBase(projectId)}/reviews/${reviewId}`);
}

export function completeProjectReview(
  projectId: string, reviewId: string, payload: { outcome: string; notes?: string }
): Promise<ComplianceReview> {
  return api.post(`${projectBase(projectId)}/reviews/${reviewId}/complete`, payload);
}

export function linkReviewEvidence(projectId: string, reviewId: string, evidenceId: string): Promise<ComplianceReview> {
  return api.post(`${projectBase(projectId)}/reviews/${reviewId}/evidence-links`, { evidence_id: evidenceId });
}

export function unlinkReviewEvidence(projectId: string, reviewId: string, evidenceId: string): Promise<void> {
  return api.delete(`${projectBase(projectId)}/reviews/${reviewId}/evidence-links/${evidenceId}`);
}
