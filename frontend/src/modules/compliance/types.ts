/**
 * Module: modules/compliance/types
 *
 * TypeScript mirrors of the Compliance Module's org-router Pydantic schemas
 * (backend/app/modules/compliance/schemas.py) that Phase 12's org-level
 * management UI needs — standards, versions, the requirement tree, required
 * actions, the two extensible vocabularies (action types, mapping
 * relationship types), cross-standard requirement mappings, and the
 * version-diff response (Phase 11, §27) — plus every enum this module's UI
 * renders and its matching `*_LABEL` map.
 *
 * Kept local to this module rather than added to `frontend/src/api/types.ts`
 * — a deliberate judgment call (see docs/compliance-module-plan.md's "Phase
 * 12 notes"): this codebase's existing convention puts every feature's
 * response shapes in the one central `api/types.ts` file, but Compliance is
 * the first genuine Tier A *installed module* (Phase 3), and keeping its own
 * response-type surface, including its own enums/labels, inside its own
 * module directory matches that mechanism's actual intent ("an installed
 * module directly imports and uses real shared components... genuinely part
 * of the app, not a lookalike" — it doesn't say its *types* must also live
 * in the core file). This module's own enums/label maps used to live in
 * `api/types.ts` per this repo's general label-map rule (CLAUDE.md, style
 * guide Principle 12), which is still the right place for a *core* enum's
 * label map — but a module's own enum is this module's own display concern,
 * not a core one, so it lives here instead, mirroring the backend's
 * identical `modules.compliance.labels` split from `app.services.labels`.
 *
 * Every `id`/`*_id` field is a `string` (UUID, serialised as JSON string,
 * same convention every other frontend type in this codebase already uses).
 */

import type { OrgUser } from "../../api/types";

/** Shared "id -> display name" lookup for the Project Compliance View's own
 * assignee/actor/owner fields — mirrors `RequirementDetailPage.tsx`'s own
 * inline `userDisplayName` helper, pulled out here since several Phase 13
 * components need the same lookup over the same `orgUsers` list fetched
 * once at `ProjectCompliancePage` and threaded down. */
export function userDisplayName(orgUsers: OrgUser[], userId: string | null | undefined): string {
  if (!userId) return "Unassigned";
  return orgUsers.find((u) => u.user_id === userId)?.display_name ?? userId;
}

// Compliance module Phase 5/6/12 (compliance-module-plan.md) —
// `ComplianceStandardVersion.status`'s lifecycle (backend
// `app.modules.compliance.enums.ComplianceStandardVersionStatus`).
export type ComplianceStandardVersionStatus = "draft" | "published" | "retired";
export const COMPLIANCE_STANDARD_VERSION_STATUS_LABEL: Record<ComplianceStandardVersionStatus, string> = {
  draft: "Draft",
  published: "Published",
  retired: "Retired",
};
// Compliance module Phase 7/8/9/10/13 — the project-assessment-facing
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
export type ComplianceApplicability = "applicable" | "not_applicable";
export const COMPLIANCE_APPLICABILITY_LABEL: Record<ComplianceApplicability, string> = {
  applicable: "Applicable",
  not_applicable: "Not applicable",
};
// §9's hierarchical-applicability UI requirement: explicit/inherited/
// overridden must be visually distinct, not just labelled differently —
// see `ApplicabilityTree.tsx`'s own badge rendering, which pairs this label
// with a colour/icon per source, not text alone.
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

/** Three-state "Non-compliant" risk label shared by `ProjectCompliancePage`'s
 * list column and `ProjectComplianceDetail`'s badge (compliance-module-plan.md
 * Phase 31). Never collapses "nobody has assessed this yet" into the same
 * reading as "assessed and found compliant" — a status with `not_yet_assessed`
 * true renders as "Unknown", not "No", even though `has_non_compliant` is
 * also false in that case. */
export type ComplianceRiskLabel = "Yes" | "Unknown" | "No";
export function complianceRiskLabel(status: { has_non_compliant: boolean; not_yet_assessed: boolean }): ComplianceRiskLabel {
  if (status.has_non_compliant) return "Yes";
  if (status.not_yet_assessed) return "Unknown";
  return "No";
}

// Compliance module Phase 20 — `ComplianceStandard.applicability_default`
// (backend `app.modules.compliance.enums.ComplianceStandardApplicabilityDefault`).
// Kept in this module-local file rather than `frontend/src/api/types.ts`,
// same deliberate judgment call as every other Compliance enum/label map
// above (see this file's own module docstring) — flagged here explicitly
// since CLAUDE.md's general label-map rule names `api/types.ts` as the
// default location, but this module's own established self-containment
// convention (Phase 12 notes) is the more specific, already-recorded rule
// that applies to Compliance's own enums.
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
  owner_id: string;
  creator_id: string;
  is_archived: boolean;
  archived_at: string | null;
  archived_by: string | null;
  applicability_default: ComplianceStandardApplicabilityDefault;
  created_at: string;
  updated_at: string;
}

// Compliance module Phase 21 — outcome of `POST .../standards/import`
// (backend `StandardImportResult`). `standard` is `null` only when
// `skipped` is true (the caller chose "skip" on a reference collision).
export interface StandardImportResult {
  standard: ComplianceStandard | null;
  skipped: boolean;
  warnings: string[];
}

// Compliance module Phase 20 — a project excepted out of a standard's
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

// Compliance module Phase 22 — standard-scoped RBAC (backend
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

// Compliance module Phase 30 — a group-based grant on a standard
// (`GroupModuleRole`, module system Phase 30's generic group-grant
// mechanism), the group-grant sibling of `ComplianceStandardMember`.
// `member_count` is resolved live by the backend, not stored.
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
  /** Phase 24 — the version's own current standing, distinct from
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
  /** Phase 24 — post-publish clarification tracking (see
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

/** A `ComplianceRequirement` decorated with its computed tree depth and
 * children, built client-side from the backend's flat, DFS-ordered
 * `GET .../requirements` list — there is no nested-tree endpoint (see
 * `router.py::_flatten_requirements_dfs`, the algorithm `buildRequirementTree`
 * in `api.ts` mirrors). Module-local presentational shape, not a backend
 * mirror. */
export interface ComplianceRequirementNode extends ComplianceRequirement {
  depth: number;
  children: ComplianceRequirementNode[];
}

// --- Phase 13: Project Compliance View (project_router.py) -----------------------
//
// Mirrors of the Phase 7-11 project-scoped Pydantic schemas
// (backend/app/modules/compliance/schemas.py) that the Project Compliance
// View needs — assignment, per-requirement assessment/applicability,
// required-action assessments, §20 status summaries, evidence, approvals,
// and scheduled reviews. Kept alongside the org-router types above per this
// file's own documented convention (module-local data shapes; enums/label
// maps live in `api/types.ts`).

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
  assignee_id: string | null;
  due_date: string | null;
  is_completed: boolean;
  completed_at: string | null;
  completed_by: string | null;
  notes: string;
  created_at: string;
  updated_at: string;
}

export interface ProjectComplianceStatus {
  project_compliance_id: string;
  project_id: string;
  /** Added Phase 14 — see `schemas.py::ProjectComplianceStatusOut`'s own
   * docstring for why this schema (uniquely among this module's
   * cross-assignment schemas) is shared unmodified between project and
   * org scope rather than getting a separate `Org*` variant. */
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
  /** True when every applicable requirement is still Not Started — i.e.
   * this assignment has had zero assessment activity. A UI rendering a
   * binary "non-compliant?" affordance from `has_non_compliant` alone
   * must check this first, so "nobody has assessed this yet" is never
   * displayed the same way as "assessed and found compliant"
   * (compliance-module-plan.md Phase 31). */
  not_yet_assessed: boolean;
  overall_compliance_state: ComplianceOverallState;
  overall_approval_state: ComplianceApprovalState;
}

export interface NonCompliantRequirement {
  project_compliance_id: string;
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

export interface ComplianceEvidence {
  id: string;
  project_id: string;
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

/** Mirrors the generic `AuditEventOut` (`backend/app/schemas/audit.py`) —
 * no `actor_display_name`/`timestamp` the way `ChangeEntry` (`api/types.ts`,
 * the activity-feed shape) has, since `get_requirement_history` returns raw
 * `AuditEvent` rows rather than resolving them into an activity-feed shape;
 * a dedicated type rather than reusing `ChangeEntry` for a differently-
 * shaped response. */
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
  standard_id: string | null;
  project_compliance_id: string | null;
  frequency_label: string;
  recurrence_days: number | null;
  next_due_date: string;
  owner_id: string | null;
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

// --- Phase 14: Org Compliance View + Dashboard (router.py's org-wide
// aggregation endpoints) ---------------------------------------------------------
//
// `OutstandingRequiredAction` is new in Phase 14 and used unmodified at both
// project and org scope (it carries `project_id`/`project_name` from the
// start — see `schemas.py::OutstandingRequiredActionOut`'s own docstring).
// `OrgNonCompliantRequirement`/`OrgPendingApproval`/`OrgExpiringEvidence`
// extend their pre-existing project-scoped counterparts with the same two
// fields, mirroring the backend's `Org*Out` subclasses rather than
// retrofitting `NonCompliantRequirement`/`PendingApproval`/`ComplianceEvidence`
// (which Phase 12/13 UI already consumes unchanged). `OrgReviewDue` wraps
// `ComplianceReview` rather than extending it flat, since one standard-level
// review can legitimately be "due" for more than one project at once.

export interface OutstandingRequiredAction {
  project_id: string;
  project_name: string;
  project_compliance_id: string;
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
  assignee_id: string | null;
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
