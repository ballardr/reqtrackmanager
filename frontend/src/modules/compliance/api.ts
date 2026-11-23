/**
 * Module: modules/compliance/api
 *
 * Thin request functions for the Compliance module. Org-router endpoints (`backend/app/modules/compliance/router.py`, mounted at
 * `/api/v1/orgs/{organization_id}/modules/compliance`): standards, versions (publish, retire, clone), the requirement tree,
 * required actions, the two extensible vocabularies (action types, mapping relationship types), requirement mappings, the
 * version diff (§27), standard export and import, and assigning a standard to a project (a Compliance Manager decision, so it
 * stays on the org router though the calling UI is project-scoped). Project-router endpoints (`project_router.py`, mounted at
 * `/api/v1/projects/{project_id}/modules/compliance`): assignments, per-requirement applicability, assessment and approval,
 * required-action assessments, evidence and its files, and scheduled reviews. The global endpoints (`getNavVisibility`,
 * `getStandardById`) carry no org or project id.
 * Every function is a pass-through to `api.*`, in one file because of the endpoint count (70+), so the pages read as UI logic.
 * Blob downloads (`exportStandard`, the report downloads) use `api.getForBlob` for `downloadBlob`; the report downloads take
 * `ComplianceReportFilters` so an export from a filtered panel contains only what the panel shows; `importStandard` uses
 * `api.postFile`. The project-scoped version migration (§27, `migrate-version`) has no wrapper.
 */
import { api, ApiError } from "../../api/client";
import type { ProjectScope } from "../../api/projectScope";
import type { ReportFileKind } from "../../api/reports";
import type { Organization, PrincipalRef } from "../../api/types";
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

// --- global (no org/project id in the path) endpoints -----------------
//
// Mounted through `ModuleDefinition.get_global_router` (`backend/app/modules/compliance/global_router.py`) at `/api/v1/compliance`.
// `nav-visibility` aggregates across every organisation the caller belongs to and `getStandardById` resolves a standard's
// owning organisation from its own id, so neither has an org or project id to key a path.

/** `status_organization_ids`: the organisations where the caller may read the organisation-wide status views. */
export interface ComplianceNavVisibility {
  visible: boolean;
  status_organization_ids: string[];
}

export function getNavVisibility(): Promise<ComplianceNavVisibility> {
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

/** A row of an organisation-wide list, tagged with the organisation it was read from. */
export type InOrganization<T> = T & { organization_id: string; organization_name: string };

/**
 * Reads one organisation-wide list from each of several organisations in parallel and joins the rows, each tagged
 * with its organisation, so a status tab can show every organisation at once.
 *
 * @param orgs The organisations to read.
 * @param load Reads one organisation's rows (`(orgId) => api call`).
 * @returns The rows of every organisation, in the order of `orgs`.
 * @throws The first failure of any organisation's request, so a missing organisation is never silently left out.
 */
export async function collectAcrossOrgs<T>(
  orgs: readonly Organization[],
  load: (orgId: string) => Promise<T[]>
): Promise<InOrganization<T>[]> {
  const perOrg = await Promise.all(
    orgs.map(async (org) =>
      (await load(org.id)).map((row): InOrganization<T> => ({ ...row, organization_id: org.id, organization_name: org.name }))
    )
  );
  return perOrg.flat();
}

/** The active organisations the caller belongs to. */
export async function listMyActiveOrganizations(): Promise<Organization[]> {
  return (await api.get<Organization[]>("/api/v1/orgs?mine=true")).filter((o) => o.is_active);
}

/**
 * Lists standards across every organisation the caller belongs to, fanning `listStandards` out in parallel because every
 * compliance route needs `organization_id` in the path. An organisation whose call returns 404 (module disabled there) is
 * dropped silently, as every compliance endpoint treats not-entitled and not-present alike; any other failure is logged
 * and dropped so one organisation's error does not fail the caller.
 * Shared by `StandardListPage.tsx` and `StandardWorkspacePage.tsx`'s `EntitySwitcher` loader.
 */
export async function listStandardsAcrossMyOrgs(
  includeArchived = false
): Promise<{ orgs: Organization[]; rows: StandardAcrossOrgsRow[] }> {
  const orgs = await listMyActiveOrganizations();

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
    /** A user or organisation group; defaults to the caller. */
    owner?: PrincipalRef | null;
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
  payload: { name: string; description?: string; issuing_organisation?: string | null; owner: PrincipalRef }
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

// --- standard workspace Overview stats --------------------------------

/** This standard's slice of `listOrgProjectComplianceStatus`: the same `ProjectComplianceStatus` rows narrowed server-side to
 * one standard, backing the Overview's "Projects" and "Compliant" tiles and their drill-down list (`StandardProjectsPanel.tsx`). */
export function getStandardProjectSummary(orgId: string, standardId: string): Promise<ProjectComplianceStatus[]> {
  return api.get(`${base(orgId)}/standards/${standardId}/project-summary`);
}

// --- standard-level import/export -----------------------------------

export function exportStandard(orgId: string, standardId: string): Promise<Blob> {
  return api.getForBlob(`${base(orgId)}/standards/${standardId}/export`);
}

// --- scoped compliance report export -----------------------------------

/** The Standard, Standard version and Sub-section (and Project, at organisation scope) filters a report export narrows to: the
 * dimensions `OrgComplianceStandardsPanel.tsx`, `OrgComplianceOutstandingPanel.tsx` and `OutstandingPanel.tsx` hold as filter
 * state, passed as query parameters so Export means what the panel currently shows. */
export interface ComplianceReportFilters {
  projectId?: string;
  standardId?: string;
  standardVersionId?: string;
  requirementId?: string;
}

/** A compliance report's file format. */
export type ComplianceReportKind = ReportFileKind;

/** Every format both compliance reports (project and organisation) are offered in. */
export const COMPLIANCE_REPORT_KINDS: readonly ComplianceReportKind[] = ["pdf", "docx", "odt", "html", "csv", "xlsx", "ods"];

function reportQueryString(kind: ComplianceReportKind, filters: ComplianceReportFilters): string {
  const params = new URLSearchParams();
  params.set("format", kind);
  if (filters.projectId) params.set("project_id", filters.projectId);
  if (filters.standardId) params.set("standard_id", filters.standardId);
  if (filters.standardVersionId) params.set("standard_version_id", filters.standardVersionId);
  if (filters.requirementId) params.set("requirement_id", filters.requirementId);
  return `?${params.toString()}`;
}

/** `GET .../orgs/{id}/modules/compliance/reports?format={pdf,docx,odt,html,csv,xlsx,ods}`, scoped by `filters`: the report
 * `OrgComplianceWidgets.tsx` downloads unscoped, filtered for the Export triggers of `OrgComplianceStandardsPanel.tsx` and
 * `OrgComplianceOutstandingPanel.tsx`. One endpoint takes `format` as a query parameter. */
export function downloadOrgComplianceReport(orgId: string, kind: ComplianceReportKind, filters: ComplianceReportFilters = {}): Promise<Blob> {
  return api.getForBlob(`${base(orgId)}/reports${reportQueryString(kind, filters)}`);
}

/** `GET .../projects/{id}/modules/compliance/reports?format={pdf,docx,odt,html,csv,xlsx,ods}`, scoped by `filters`: the
 * filtered counterpart of `ProjectCompliancePage.tsx`'s whole-project report download, used by `OutstandingPanel.tsx`'s Export. */
export function downloadProjectComplianceReport(
  projectId: string, kind: ComplianceReportKind, filters: Omit<ComplianceReportFilters, "projectId"> = {}
): Promise<Blob> {
  return api.getForBlob(`${projectBase(projectId)}/reports${reportQueryString(kind, filters)}`);
}

/** `resolution` is only needed on a retry after a 409 (reference collision)
 * — see `StandardImportModal.tsx`'s own docstring. */
export function importStandard(orgId: string, file: File, resolution?: "skip" | "import_as_copy"): Promise<StandardImportResult> {
  return api.postFile(`${base(orgId)}/standards/import`, file, resolution ? { resolution } : undefined);
}

// --- applicability defaults + exceptions (Compliance-Manager-only, ---
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

// --- standard-scoped RBAC (standards_manager/standards_contributor) --

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

// Group-based grants (`GroupModuleRole`).
export function assignStandardGroupRole(
  orgId: string, standardId: string, orgGroupId: string, roleKey: ComplianceStandardRoleKey
): Promise<void> {
  return api.post(`${base(orgId)}/standards/${standardId}/group-roles`, { org_group_id: orgGroupId, role_key: roleKey });
}

export function revokeStandardGroupRole(
  orgId: string, standardId: string, orgGroupId: string, roleKey: ComplianceStandardRoleKey
): Promise<void> {
  return api.delete(`${base(orgId)}/standards/${standardId}/group-roles/${orgGroupId}/${roleKey}`);
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

// --- version summary (editable at any lifecycle stage) + ---------------
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

// --- Version diff (§27) ------------------------------------------------

export function getStandardVersionDiff(
  orgId: string, standardId: string, versionId: string, otherVersionId: string
): Promise<StandardVersionDiff> {
  return api.get(`${base(orgId)}/standards/${standardId}/versions/${versionId}/diff/${otherVersionId}`);
}

// --- Org Compliance View + Dashboard (§22, §23) -------------------------
//
// Org-wide aggregations across every project in the organisation, all `_require_manage`-gated on the backend (§26), manage- and
// not view-gated despite §22's looser "Compliance Managers and authorised users" text.

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

// --- Project-level outstanding required actions (new alongside the
// org-wide aggregation above; consistent with the existing non-compliant-
// requirements/pending-approvals per-project listing family) ---------------------

export function listOutstandingRequiredActions(projectId: string): Promise<OutstandingRequiredAction[]> {
  return api.get(`${projectBase(projectId)}/outstanding-required-actions`);
}

// --- Client-side tree assembly ----------------------------------------------------

/**
 * Builds a parent/child tree from the backend's flat, depth-first `GET .../requirements` list (`parent_requirement_id` on each
 * row), since no nested-tree endpoint exists (`router.py::_flatten_requirements_dfs`). Each parent group already arrives
 * `sort_order`-ordered from the backend's depth-first emission, so it only re-nests the list and does no re-sort.
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
 * Resolves the top-level ancestor (the requirement whose `parent_requirement_id` is `null`) of `requirementId` within
 * `requirementsById`: the "sub-section" filter concept, e.g. "Clause 4" of ISO 27001. The data model has no "section" field, so
 * a requirement's section is its outermost ancestor. Used by `OrgComplianceOutstandingPanel` and `OutstandingPanel`.
 *
 * Returns `null` when `requirementId` is not in `requirementsById` (that requirement's version tree has not been fetched) or
 * when a `parent_requirement_id` chain is broken; it never throws, so such a row is left out of every sub-section bucket.
 */
export function findTopLevelAncestor(
  requirementsById: Map<string, ComplianceRequirement>,
  requirementId: string
): ComplianceRequirement | null {
  let current = requirementsById.get(requirementId);
  if (!current) return null;
  const seen = new Set<string>();
  while (current.parent_requirement_id) {
    if (seen.has(current.id)) return null;
    seen.add(current.id);
    const parent = requirementsById.get(current.parent_requirement_id);
    if (!parent) break;
    current = parent;
  }
  return current;
}

/**
 * Resolves the `standard_id` that owns a `standard_version_id`. Every org-router requirement-tree endpoint is nested under
 * `/standards/{standard_id}/versions/{version_id}/...` with no endpoint to get a version by id alone, while `ProjectCompliance`
 * stores only `standard_version_id`. An active assignment has it in `ProjectComplianceStatusOut.standard_id`
 * (`getProjectComplianceStatus`); this fallback serves an archived assignment, which `GET .../status` excludes, by a client-side
 * join over the organisation's (typically small) standard and version catalogue.
 */
export async function resolveStandardIdForVersion(orgId: string, standardVersionId: string): Promise<string | null> {
  const standards = await listStandards(orgId, true);
  for (const standard of standards) {
    const versions = await listStandardVersions(orgId, standard.id);
    if (versions.some((v) => v.id === standardVersionId)) return standard.id;
  }
  return null;
}

// --- Assignment ---------------------------------------------------
//
// Two endpoints with one payload shape and different callers: the project-scoped one (below) is the primary path, usable by a
// plain Project Manager with no `compliance_officer` grant; this org-scoped one (Compliance-Manager-only) is the administrative
// path, for assigning on a project's behalf or in bulk.

export function createProjectCompliance(
  orgId: string, projectId: string,
  payload: { standard_id: string; standard_version_id: string; target_compliance_date?: string | null }
): Promise<ProjectCompliance> {
  return api.post(`${base(orgId)}/projects/${projectId}/project-compliance`, payload);
}

/** The primary assignment path: project-scoped and `_require_officer`-gated (`compliance_officer` grant or
 * `ProjectRole.PROJECT_MANAGER`), used by `ProjectCompliancePage.tsx`'s "Assign standard" flow. */
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

// --- Project compliance assignments (project router, read + status) ---

export function listProjectCompliance(projectId: string): Promise<ProjectCompliance[]> {
  return api.get(`${projectBase(projectId)}/project-compliance`);
}

/** The standards assigned to a project; `projectScope` adds those of its related projects. */
export function getProjectComplianceStatus(projectId: string, projectScope: ProjectScope = "this"): Promise<ProjectComplianceStatus[]> {
  const query = projectScope === "this" ? "" : `?project_scope=${projectScope}`;
  return api.get(`${projectBase(projectId)}/status${query}`);
}

export function listNonCompliantRequirements(projectId: string): Promise<NonCompliantRequirement[]> {
  return api.get(`${projectBase(projectId)}/non-compliant-requirements`);
}

export function listPendingApprovals(projectId: string): Promise<PendingApproval[]> {
  return api.get(`${projectBase(projectId)}/pending-approvals`);
}

// --- Per-requirement assessment (§8-§10, §12, §16) ---------------------

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

// --- Required action assessments (§6/§25) ------------------------------

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
  payload: { assignee?: PrincipalRef | null; due_date?: string | null; notes?: string }
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

// --- Evidence (§13-§15) -------------------------------------------------

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

export function getEvidence(projectId: string, evidenceId: string): Promise<ComplianceEvidence> {
  return api.get(`${projectBase(projectId)}/evidence/${evidenceId}`);
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

// --- Scheduled reviews, project-level (§17, §18, §28) -----------------

export function createProjectReview(
  projectId: string, projectComplianceId: string,
  payload: { frequency_label: string; recurrence_days?: number | null; next_due_date: string; owner?: PrincipalRef | null; notes?: string }
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
  payload: { frequency_label: string; recurrence_days?: number | null; next_due_date: string; owner?: PrincipalRef | null; notes?: string }
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
