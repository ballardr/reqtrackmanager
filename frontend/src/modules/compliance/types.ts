/**
 * Module: modules/compliance/types
 *
 * TypeScript mirrors of the Compliance module's org-router Pydantic schemas (backend/app/modules/compliance/schemas.py): standards,
 * versions, the requirement tree, required actions, the two extensible vocabularies (action types, mapping relationship types),
 * requirement mappings and the version-diff response (§27), plus every enum the module's UI renders with its `*_LABEL` map.
 * They live in this module, not in `frontend/src/api/types.ts`: Compliance is an installed module whose own enums and labels are
 * its display concern (mirroring the backend's `modules.compliance.labels`), while core enums keep their label maps in
 * `api/types.ts` (CLAUDE.md, style guide Principle 12).
 * Every `id` and `*_id` field is a `string` (a UUID serialised as JSON).
 */

import type { BadgeTone, OrgUser, Principal } from "../../api/types";
import type { ProjectScopedRow } from "../../api/projectScope";

/** Shared "id -> display name" lookup for the Project Compliance View's assignee, actor and owner fields, over the `orgUsers` list
 * fetched once at `ProjectCompliancePage` (as `RequirementDetailPage.tsx`'s `userDisplayName`). */
export function userDisplayName(orgUsers: OrgUser[], userId: string | null | undefined): string {
  if (!userId) return "Unassigned";
  return orgUsers.find((u) => u.user_id === userId)?.display_name ?? userId;
}

// Compliance module —
// `ComplianceStandardVersion.status`'s lifecycle (backend
// `app.modules.compliance.enums.ComplianceStandardVersionStatus`).
export type ComplianceStandardVersionStatus = "draft" | "published" | "retired";
export const COMPLIANCE_STANDARD_VERSION_STATUS_LABEL: Record<ComplianceStandardVersionStatus, string> = {
  draft: "Draft",
  published: "Published",
  retired: "Retired",
};
// The project-assessment-facing
// enums (backend `app.modules.compliance.enums`).
export type ComplianceStatus =
  | "not_started" | "in_progress" | "compliant" | "non_compliant" | "blocked" | "pending_review" | "rejected";
export const COMPLIANCE_STATUS_LABEL: Record<ComplianceStatus, string> = {
  not_started: "Not started",
  in_progress: "In progress",
  compliant: "Compliant",
  non_compliant: "Non-compliant",
  blocked: "Blocked",
  pending_review: "Pending review",
  rejected: "Rejected",
};
/** A required-action assessment's status as the Links panel shows it (`open` until completed). */
export const COMPLIANCE_ACTION_ASSESSMENT_STATUS_LABEL: Record<string, string> = { open: "Open", completed: "Completed" };
export type ComplianceApplicability = "applicable" | "not_applicable";
export const COMPLIANCE_APPLICABILITY_LABEL: Record<ComplianceApplicability, string> = {
  applicable: "Applicable",
  not_applicable: "Not applicable",
};
// §9 requires explicit, inherited and overridden applicability to be visually distinct, not only labelled differently;
// `ApplicabilityTree.tsx`'s badge pairs this label with a colour and icon per source.
export type ComplianceApplicabilitySource = "explicit" | "inherited" | "overridden";
export const COMPLIANCE_APPLICABILITY_SOURCE_LABEL: Record<ComplianceApplicabilitySource, string> = {
  explicit: "Explicit",
  inherited: "Inherited",
  overridden: "Overridden",
};
export type ComplianceApprovalState =
  | "not_assessed" | "assessed" | "pending_approval" | "approved" | "rejected" | "requires_reassessment";
export const COMPLIANCE_APPROVAL_STATE_LABEL: Record<ComplianceApprovalState, string> = {
  not_assessed: "Not assessed",
  assessed: "Assessed",
  pending_approval: "Pending approval",
  approved: "Approved",
  rejected: "Rejected",
  requires_reassessment: "Requires re-assessment",
};
export type ComplianceEvidenceValidityState = "no_expiry" | "valid" | "expiring_soon" | "expired";
export const COMPLIANCE_EVIDENCE_VALIDITY_STATE_LABEL: Record<ComplianceEvidenceValidityState, string> = {
  no_expiry: "No expiry",
  valid: "Valid",
  expiring_soon: "Expiring soon",
  expired: "Expired",
};
export const COMPLIANCE_EVIDENCE_VALIDITY_STATE_TONE: Record<ComplianceEvidenceValidityState, BadgeTone> = {
  no_expiry: "muted",
  valid: "accent",
  expiring_soon: "warning",
  expired: "danger",
};
export type ComplianceReviewStatus = "scheduled" | "completed";
export const COMPLIANCE_REVIEW_STATUS_LABEL: Record<ComplianceReviewStatus, string> = {
  scheduled: "Scheduled",
  completed: "Completed",
};
export type ComplianceReviewOutcome = "satisfactory" | "action_required" | "unsatisfactory";
export const COMPLIANCE_REVIEW_OUTCOME_LABEL: Record<ComplianceReviewOutcome, string> = {
  satisfactory: "Satisfactory",
  action_required: "Action required",
  unsatisfactory: "Unsatisfactory",
};
export type ComplianceReviewScheduleState = "upcoming" | "due" | "overdue";
export const COMPLIANCE_REVIEW_SCHEDULE_STATE_LABEL: Record<ComplianceReviewScheduleState, string> = {
  upcoming: "Upcoming",
  due: "Due",
  overdue: "Overdue",
};
// §20's overall compliance state (`ProjectComplianceStatusOut.overall_compliance_state`).
export type ComplianceOverallState = "compliant" | "non_compliant" | "in_progress" | "not_applicable";
export const COMPLIANCE_OVERALL_STATE_LABEL: Record<ComplianceOverallState, string> = {
  compliant: "Compliant",
  non_compliant: "Non-compliant",
  in_progress: "In progress",
  not_applicable: "Not applicable",
};

/** Three-state "Non-compliant" risk label shared by `ProjectCompliancePage`'s list column and `ProjectComplianceDetail`'s badge.
 * It never reads "nobody has assessed this yet" as "assessed and found compliant": a status with `not_yet_assessed` true is
 * "Unknown", not "No", although `has_non_compliant` is also false then. */
export type ComplianceRiskLabel = "Yes" | "Unknown" | "No";
export function complianceRiskLabel(status: { has_non_compliant: boolean; not_yet_assessed: boolean }): ComplianceRiskLabel {
  if (status.has_non_compliant) return "Yes";
  if (status.not_yet_assessed) return "Unknown";
  return "No";
}

// `ComplianceStandard.applicability_default` (backend `app.modules.compliance.enums.ComplianceStandardApplicabilityDefault`).
// It lives in this module's file, like every Compliance enum, not in `frontend/src/api/types.ts`.
export type ComplianceStandardApplicabilityDefault = "opt_in" | "applies_to_all_projects";
export const COMPLIANCE_STANDARD_APPLICABILITY_DEFAULT_LABEL: Record<ComplianceStandardApplicabilityDefault, string> = {
  opt_in: "Opt-in (assigned per project)",
  applies_to_all_projects: "Applies to all projects by default",
};

export interface ComplianceStandard {
  id: string;
  organization_id: string;
  reference: string;
  name: string;
  description: string;
  issuing_organisation: string | null;
  /** The accountable user or organisation group (never empty). */
  owner: Principal;
  creator_id: string;
  is_archived: boolean;
  archived_at: string | null;
  archived_by: string | null;
  applicability_default: ComplianceStandardApplicabilityDefault;
  created_at: string;
  updated_at: string;
}

// Outcome of `POST .../standards/import`
// (backend `StandardImportResult`). `standard` is `null` only when
// `skipped` is true (the caller chose "skip" on a reference collision).
export interface StandardImportResult {
  standard: ComplianceStandard | null;
  skipped: boolean;
  warnings: string[];
}

// A project excepted out of a standard's
// `applies_to_all_projects` default (backend
// `ComplianceStandardDefaultExclusionOut`).
export interface ComplianceStandardDefaultExclusion {
  id: string;
  standard_id: string;
  project_id: string;
  excluded_by: string;
  excluded_at: string;
  reason: string;
  created_at: string;
  updated_at: string;
}

// Standard-scoped RBAC (backend
// `ComplianceOrgSettingsOut`/`ComplianceStandardMembersOut`/
// `ComplianceStandardMemberOut`).
export type ComplianceStandardRoleKey = "standards_manager" | "standards_contributor";

export const COMPLIANCE_STANDARD_ROLE_LABEL: Record<ComplianceStandardRoleKey, string> = {
  standards_manager: "Standards Manager",
  standards_contributor: "Standards Contributor",
};

export interface ComplianceOrgSettings {
  default_standards_manager_group_id: string | null;
}

export interface ComplianceStandardMember {
  user_id: string;
  display_name: string;
  email: string;
  role_keys: ComplianceStandardRoleKey[];
}

// A group-based grant on a standard (`GroupModuleRole`, the generic group-grant mechanism), the group sibling of
// `ComplianceStandardMember`. `member_count` is resolved live by the backend, not stored.
export interface ComplianceStandardGroupMember {
  org_group_id: string;
  group_name: string;
  role_keys: ComplianceStandardRoleKey[];
  member_count: number;
}

export interface ComplianceStandardMembers {
  members: ComplianceStandardMember[];
  group_members: ComplianceStandardGroupMember[];
  manager_floor_covered_by_fallback: boolean;
}

export interface ComplianceStandardVersion {
  id: string;
  standard_id: string;
  version_number: number;
  version_label: string;
  status: ComplianceStandardVersionStatus;
  effective_date: string | null;
  change_note: string;
  /** The version's own current standing, distinct from
   * `change_note` (what changed *relative to the previous version*).
   * Editable at any lifecycle stage — see `VersionWorkspace.tsx`. */
  summary: string;
  created_by: string;
  published_at: string | null;
  published_by: string | null;
  retired_at: string | null;
  retired_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface ComplianceRequirement {
  id: string;
  standard_version_id: string;
  parent_requirement_id: string | null;
  reference: string | null;
  name: string;
  description: string;
  reasoning: string;
  sort_order: number;
  created_by: string;
  /** Post-publish clarification tracking (see
   * `RequirementTree.tsx`'s "Clarify" action). `clarification_count` is 0
   * and the rest `null`/`""` for a requirement never clarified. */
  clarification_count: number;
  last_clarified_at: string | null;
  last_clarified_by: string | null;
  last_clarification_note: string;
  created_at: string;
  updated_at: string;
}

export interface ComplianceRequiredAction {
  id: string;
  requirement_id: string;
  action_type_id: string;
  name: string;
  description: string;
  is_mandatory: boolean;
  sort_order: number;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface ComplianceActionType {
  id: string;
  organization_id: string;
  name: string;
  sort_order: number;
}

export interface ComplianceMappingRelationshipType {
  id: string;
  organization_id: string;
  name: string;
  sort_order: number;
  implies_equivalence: boolean;
}

export interface ComplianceRequirementMapping {
  id: string;
  organization_id: string;
  from_requirement_id: string;
  to_requirement_id: string;
  relationship_type_id: string;
  notes: string;
  created_by: string;
  is_archived: boolean;
  archived_at: string | null;
  archived_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface ComplianceRequirementSummary {
  id: string;
  standard_version_id: string;
  reference: string | null;
  name: string;
}

export interface AddedRequirement {
  requirement: ComplianceRequirementSummary;
}

export interface RemovedRequirement {
  requirement: ComplianceRequirementSummary;
}

export interface ModifiedRequirement {
  old_requirement: ComplianceRequirementSummary;
  new_requirement: ComplianceRequirementSummary;
  changed_fields: string[];
}

export interface ReplacedRequirement {
  old_requirement: ComplianceRequirementSummary;
  new_requirement: ComplianceRequirementSummary;
  mapping_id: string;
  relationship_type_id: string;
  implies_equivalence: boolean;
}

export interface RemappedRequirement {
  old_requirement: ComplianceRequirementSummary;
  new_requirement: ComplianceRequirementSummary;
  old_mapping_target_requirement_ids: string[];
  new_mapping_target_requirement_ids: string[];
}

export interface StandardVersionDiff {
  old_version_id: string;
  new_version_id: string;
  added: AddedRequirement[];
  removed: RemovedRequirement[];
  modified: ModifiedRequirement[];
  replaced: ReplacedRequirement[];
  re_mapped: RemappedRequirement[];
}

/** A `ComplianceRequirement` decorated with its computed tree depth and children, built client-side from the backend's flat,
 * depth-first `GET .../requirements` list (no nested-tree endpoint exists; `buildRequirementTree` in `api.ts` mirrors
 * `router.py::_flatten_requirements_dfs`). A module-local presentational shape, not a backend mirror. */
export interface ComplianceRequirementNode extends ComplianceRequirement {
  depth: number;
  children: ComplianceRequirementNode[];
}

// --- Project Compliance View (project_router.py) -----------------------
//
// Mirrors of the project-scoped Pydantic schemas (backend/app/modules/compliance/schemas.py): assignment, per-requirement
// assessment and applicability, required-action assessments, §20 status summaries, evidence, approvals and scheduled reviews.

export interface ProjectCompliance {
  id: string;
  project_id: string;
  standard_version_id: string;
  assigned_at: string;
  assigned_by: string;
  target_compliance_date: string | null;
  is_archived: boolean;
  archived_at: string | null;
  archived_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface ProjectComplianceRequirement {
  id: string;
  project_compliance_id: string;
  requirement_id: string;
  explicit_applicability: ComplianceApplicability | null;
  effective_applicability: ComplianceApplicability;
  applicability_source: ComplianceApplicabilitySource;
  justification: string;
  notes: string;
  compliance_status: ComplianceStatus;
  assessed_at: string | null;
  assessed_by: string | null;
  applicability_set_at: string | null;
  applicability_set_by: string | null;
  approval_state: ComplianceApprovalState;
  approval_decided_at: string | null;
  approval_decided_by: string | null;
  decision_note: string;
  created_at: string;
  updated_at: string;
}

export interface ComplianceRequiredActionAssessment {
  id: string;
  project_compliance_requirement_id: string;
  required_action_id: string;
  assignee: Principal | null;
  due_date: string | null;
  is_completed: boolean;
  completed_at: string | null;
  completed_by: string | null;
  notes: string;
  created_at: string;
  updated_at: string;
}

export interface ProjectComplianceStatus extends ProjectScopedRow {
  project_compliance_id: string;
  project_id: string;
  /** Shared unmodified between project and org scope, unlike this module's other cross-assignment schemas
   * (see `schemas.py::ProjectComplianceStatusOut`). */
  project_name: string;
  standard_id: string;
  standard_reference: string;
  standard_name: string;
  standard_version_id: string;
  version_label: string;
  target_compliance_date: string | null;
  assigned_at: string;
  total_requirements: number;
  applicable_count: number;
  not_applicable_count: number;
  counts_by_status: Record<string, number>;
  compliance_percentage: number;
  has_non_compliant: boolean;
  /** True when every applicable requirement is still Not Started, so the assignment has had no assessment activity. A UI showing
   * a binary "non-compliant?" from `has_non_compliant` alone must check this first, so "nobody has assessed this yet" is never
   * shown as "assessed and found compliant". */
  not_yet_assessed: boolean;
  overall_compliance_state: ComplianceOverallState;
  overall_approval_state: ComplianceApprovalState;
}

export interface NonCompliantRequirement {
  project_compliance_id: string;
  standard_id: string;
  standard_version_id: string;
  standard_reference: string;
  standard_name: string;
  version_label: string;
  project_compliance_requirement_id: string;
  requirement_id: string;
  requirement_reference: string | null;
  requirement_name: string;
  justification: string;
  notes: string;
  assessed_at: string | null;
  assessed_by: string | null;
}

export interface PendingApproval {
  project_compliance_id: string;
  standard_id: string;
  standard_version_id: string;
  standard_reference: string;
  standard_name: string;
  version_label: string;
  project_compliance_requirement_id: string;
  requirement_id: string;
  requirement_reference: string | null;
  requirement_name: string;
  compliance_status: ComplianceStatus;
  assessed_at: string | null;
  assessed_by: string | null;
}

export interface ComplianceEvidence extends ProjectScopedRow {
  id: string;
  project_id: string;
  unique_code: string;
  title: string;
  description: string;
  issuing_organisation: string | null;
  issued_date: string | null;
  expiry_date: string | null;
  provided_by: string;
  provided_at: string;
  notes: string;
  validity_state: ComplianceEvidenceValidityState;
  is_archived: boolean;
  archived_at: string | null;
  archived_by: string | null;
  created_at: string;
  updated_at: string;
  linked_requirement_ids: string[];
  linked_required_action_assessment_ids: string[];
}

export interface ComplianceEvidenceRevalidation {
  id: string;
  evidence_id: string;
  revalidated_by: string;
  revalidated_at: string;
  previous_expiry_date: string | null;
  new_expiry_date: string | null;
  justification: string;
  created_at: string;
}

/** Mirrors the generic `AuditEventOut` (`backend/app/schemas/audit.py`). It has no `actor_display_name` or `timestamp` as
 * `ChangeEntry` (`api/types.ts`) does, because `get_requirement_history` returns raw `AuditEvent` rows, so it is a separate type. */
export interface ComplianceAuditEvent {
  id: string;
  entity_type: string;
  entity_id: string;
  action: string;
  actor_id: string | null;
  detail: Record<string, unknown> | null;
  created_at: string;
}

export interface ComplianceReview {
  id: string;
  /** Resolved owning standard regardless of whether this review
   * is scoped directly to a standard or through one project's assignment —
   * see `schemas.py::ComplianceReviewOut`'s own docstring. */
  standard_id: string | null;
  standard_version_id: string | null;
  standard_reference: string | null;
  standard_name: string | null;
  version_label: string | null;
  project_compliance_id: string | null;
  frequency_label: string;
  recurrence_days: number | null;
  next_due_date: string;
  owner: Principal | null;
  status: ComplianceReviewStatus;
  schedule_state: ComplianceReviewScheduleState | null;
  notes: string;
  outcome: ComplianceReviewOutcome | null;
  completed_at: string | null;
  completed_by: string | null;
  created_by: string;
  created_at: string;
  updated_at: string;
  linked_evidence_ids: string[];
}

// --- Org Compliance View + Dashboard (router.py's org-wide aggregation endpoints) ---------------------------------------------------------
//
// `OutstandingRequiredAction` is shared by project and org scope (it carries `project_id` and `project_name`; see
// `schemas.py::OutstandingRequiredActionOut`). `OrgNonCompliantRequirement`, `OrgPendingApproval` and `OrgExpiringEvidence` extend
// their project-scoped counterparts with those two fields, mirroring the backend's `Org*Out` subclasses, so the project-scoped UI
// consumes `NonCompliantRequirement`, `PendingApproval` and `ComplianceEvidence` unchanged. `OrgReviewDue` wraps `ComplianceReview`
// because one standard-level review can be due for more than one project at once.

export interface OutstandingRequiredAction {
  project_id: string;
  project_name: string;
  project_compliance_id: string;
  standard_id: string;
  standard_version_id: string;
  standard_reference: string;
  standard_name: string;
  version_label: string;
  project_compliance_requirement_id: string;
  requirement_id: string;
  requirement_reference: string | null;
  requirement_name: string;
  required_action_assessment_id: string;
  required_action_id: string;
  required_action_name: string;
  is_mandatory: boolean;
  assignee: Principal | null;
  due_date: string | null;
  notes: string;
}

export interface OrgNonCompliantRequirement extends NonCompliantRequirement {
  project_id: string;
  project_name: string;
}

export interface OrgPendingApproval extends PendingApproval {
  project_id: string;
  project_name: string;
}

export interface OrgExpiringEvidence extends ComplianceEvidence {
  project_name: string;
}

export interface OrgReviewDue {
  project_id: string;
  project_name: string;
  review: ComplianceReview;
}

export interface ComplianceRecentActivity {
  id: string;
  project_id: string;
  project_name: string;
  standard_reference: string;
  standard_name: string;
  version_label: string;
  requirement_reference: string | null;
  requirement_name: string;
  action: string;
  actor_id: string | null;
  created_at: string;
}
