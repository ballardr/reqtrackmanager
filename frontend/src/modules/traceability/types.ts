/**
 * Module: modules/traceability/types
 *
 * TypeScript shapes and enum label maps of the Governance half of the Traceability & Governance module, mirroring
 * `backend/app/modules/traceability/schemas.py` and `enums.py` field for field. They live in the module's directory, not
 * `frontend/src/api/types.ts`, because a module's enums and label maps are its own display concern.
 *
 * Every enum value shown to a person goes through a label map here (docs/ux-style-guide.md, Principle 12).
 */
import type { BadgeTone, Principal, PrincipalRef } from "../../api/types";

// --- Profiles ---------------------------------------------------------------------------------------------------

/** How a profile reaches the projects it targets. */
export type ProfileMode = "enforced" | "default" | "opt_in";

export const PROFILE_MODE_LABEL: Record<ProfileMode, string> = {
  enforced: "Enforced",
  default: "Default",
  opt_in: "Opt-in",
};

export const PROFILE_MODE_DESCRIPTION: Record<ProfileMode, string> = {
  enforced: "Binds every targeted project. Only a named exemption lifts it.",
  default: "Applies to every targeted project unless the project opts out.",
  opt_in: "Applies only to a targeted project that chooses it.",
};

export const PROFILE_MODE_TONE: Record<ProfileMode, BadgeTone> = { enforced: "accent", default: "info", opt_in: "muted" };

/** Which projects a profile reaches. */
export type ProfileTargetKind = "all_projects" | "selected_projects";

export const PROFILE_TARGET_KIND_LABEL: Record<ProfileTargetKind, string> = {
  all_projects: "All projects",
  selected_projects: "Selected projects",
};

/** What one profile does for one project. */
export type ProfileOutcome = "enforced" | "exempt" | "default" | "opted_out" | "opted_in" | "available" | "not_targeted";

export const PROFILE_OUTCOME_LABEL: Record<ProfileOutcome, string> = {
  enforced: "Enforced",
  exempt: "Exempt",
  default: "Applies by default",
  opted_out: "Opted out",
  opted_in: "Opted in",
  available: "Available to opt in",
  not_targeted: "Not targeted",
};

export const PROFILE_OUTCOME_TONE: Record<ProfileOutcome, BadgeTone> = {
  enforced: "accent",
  exempt: "muted",
  default: "info",
  opted_out: "muted",
  opted_in: "info",
  available: "muted",
  not_targeted: "muted",
};

export interface ProfileTarget {
  project_id: string;
  include_children: boolean;
}

export interface ProfileTargetOut extends ProfileTarget {
  project_name: string;
}

export interface ProfileExemption {
  project_id: string;
  project_name: string;
  include_children: boolean;
  reason: string;
}

/** How many policy rows of one kind a profile holds. */
export interface ProfileContribution {
  key: string;
  name: string;
  count: number;
}

export interface Profile {
  id: string;
  name: string;
  description: string;
  mode: ProfileMode;
  target_kind: ProfileTargetKind;
  targets: ProfileTargetOut[];
  exemptions: ProfileExemption[];
  contributions: ProfileContribution[];
  created_at: string;
  updated_at: string;
}

/** What a profile does for one project it reaches. */
export interface ProfileProject {
  project_id: string;
  project_name: string;
  outcome: ProfileOutcome;
  applies: boolean;
  /** The project's stored choice: `true` opted in, `false` opted out, `null` none. */
  choice: boolean | null;
}

export interface ProfileDetail extends Profile {
  projects: ProfileProject[];
}

export interface ProfileCreateValues {
  name: string;
  description: string;
  mode: ProfileMode;
  target_kind: ProfileTargetKind;
  targets: ProfileTarget[];
}

export interface ProfileUpdateValues {
  name?: string;
  description?: string;
  mode?: ProfileMode;
}

export interface ExemptionValues {
  project_id: string;
  include_children: boolean;
  reason: string;
}

/** One profile as it concerns a project. */
export interface ProjectProfile {
  id: string;
  name: string;
  description: string;
  mode: ProfileMode;
  outcome: ProfileOutcome;
  applies: boolean;
  choice: boolean | null;
  can_choose: boolean;
}

export interface ProjectProfiles {
  can_manage: boolean;
  profiles: ProjectProfile[];
}

// --- Lifecycle (a profile's requirements) -----------------------------------------------------------------------

export interface LifecycleStateOption {
  key: string;
  label: string;
}

export interface LifecycleTypePolicy {
  artefact_type: string;
  label: string;
  module_key: string;
  states: LifecycleStateOption[];
  required: string[];
}

export interface ProfileLifecycle {
  types: LifecycleTypePolicy[];
  skip_forbidden: boolean;
}

/** How a profile's required stage workflow binds a project. */
export type StageWorkflowMode = "default" | "restrict";

export const STAGE_WORKFLOW_MODE_LABEL: Record<StageWorkflowMode, string> = {
  default: "Start new stages in it",
  restrict: "Start new stages in it and allow only the named workflows",
};

export interface StageWorkflowOption {
  id: string;
  name: string;
}

export interface ProfileStageWorkflow {
  workflow_id: string | null;
  workflow_name: string | null;
  mode: StageWorkflowMode;
  options: StageWorkflowOption[];
}

// --- Approval ---------------------------------------------------------------------------------------------------

/** Where an approver role is defined: a fixed project role, a module's role or an organisation's custom role. */
export type ApproverRoleKind = "project" | "module" | "custom";

export interface ApproverRole {
  kind: ApproverRoleKind;
  key: string;
}

export interface ApproverRoleOut extends ApproverRole {
  label: string;
}

export interface ApproverRoleOption extends ApproverRoleOut {
  /** `project` when the role is granted within a project, `org` when it is granted for the organisation. */
  scope: "org" | "project";
}

export interface ProfileApprovalType {
  artefact_type: string;
  label: string;
  module_key: string;
  roles: ApproverRoleOut[];
}

export interface ProfileApproval {
  types: ProfileApprovalType[];
  role_options: ApproverRoleOption[];
}

export interface RoleSource {
  role: ApproverRoleOut;
  /** Names of the profiles that give the role, then `project` and `parent_project`. */
  sources: string[];
}

export interface ProjectApprovalType {
  artefact_type: string;
  label: string;
  module_key: string;
  /** The project's own roles; `null` when it has no row (it follows the nearest ancestor project). */
  own: ApproverRoleOut[] | null;
  inherited_from: string | null;
  effective: RoleSource[];
}

export interface ProjectApproval {
  can_manage: boolean;
  types: ProjectApprovalType[];
  role_options: ApproverRoleOption[];
}

// --- Review -----------------------------------------------------------------------------------------------------

/** What a policy row sets; a field left `null` sets nothing. */
export interface ReviewSettingsValues {
  interval_days: number | null;
  lead_days: number | null;
  default_owner: PrincipalRef | null;
}

export interface ReviewSettings {
  interval_days: number | null;
  lead_days: number | null;
  default_owner: Principal | null;
}

export interface ProfileReviewType {
  artefact_type: string;
  label: string;
  module_key: string;
  settings: ReviewSettings;
}

export interface ProfileReview {
  types: ProfileReviewType[];
}

export interface EffectiveReview {
  interval_days: number | null;
  interval_source: string | null;
  lead_days: number | null;
  lead_source: string | null;
  default_owner: Principal | null;
  owner_source: string | null;
}

export interface ProjectReviewType {
  artefact_type: string;
  label: string;
  module_key: string;
  own: ReviewSettings | null;
  inherited_from: string | null;
  effective: EffectiveReview;
}

export interface ProjectReview {
  can_manage: boolean;
  types: ProjectReviewType[];
}

// --- Baseline ---------------------------------------------------------------------------------------------------

export interface RequiredField {
  artefact_type: string;
  field_key: string;
}

/** Which approvals a baseline policy's checks also run before. */
export type ApprovalCheckMode = "off" | "manual" | "automated" | "manual_and_automated";

export const APPROVAL_CHECK_LABEL: Record<ApprovalCheckMode, string> = {
  off: "Off",
  manual: "Manual approvals only",
  automated: "Automated approvals only",
  manual_and_automated: "Manual and automated approvals",
};

/** The baseline policy one owner (a profile or a project) gives. */
export interface BaselineSettings {
  applies_to_stage: boolean;
  applies_to_manual: boolean;
  approval_checks: ApprovalCheckMode;
  notify_managers: boolean;
  checks: string[];
  required_fields: RequiredField[];
}

export interface BaselineCheckOption {
  key: string;
  name: string;
  module_key: string;
  /** The types it inspects; empty for every type the baseline holds. */
  artefact_types: string[];
}

export interface BaselineType {
  artefact_type: string;
  label: string;
  module_key: string;
}

export interface BaselineFieldOption {
  key: string;
  label: string;
}

export interface ProfileBaseline {
  settings: BaselineSettings;
  check_options: BaselineCheckOption[];
  types: BaselineType[];
}

export interface BaselineFields {
  types: Record<string, BaselineFieldOption[]>;
}

export interface EffectiveBaselineCheck {
  key: string;
  name: string | null;
  available: boolean;
  stage: boolean;
  manual: boolean;
  manual_approval: boolean;
  automated_approval: boolean;
  sources: string[];
}

export interface EffectiveBaselineField {
  artefact_type: string;
  field_key: string;
  field_label: string | null;
  stage: boolean;
  manual: boolean;
  manual_approval: boolean;
  automated_approval: boolean;
  sources: string[];
}

export interface ProjectBaseline {
  can_manage: boolean;
  own: BaselineSettings | null;
  inherited_from: string | null;
  checks: EffectiveBaselineCheck[];
  required_fields: EffectiveBaselineField[];
  notify_managers: boolean;
  check_options: BaselineCheckOption[];
  types: BaselineType[];
  field_options: Record<string, BaselineFieldOption[]>;
}

export type BaselineKind = "stage" | "manual";

export const BASELINE_KIND_LABEL: Record<BaselineKind, string> = { stage: "Stage baseline", manual: "Manual baseline" };

export interface BaselineFailure {
  check_key: string;
  check_name: string;
  artefact_type: string;
  artefact_id: string;
  code: string;
  message: string;
}

export interface BaselinePreview {
  kind: BaselineKind;
  checks: { key: string; name: string }[];
  failures: BaselineFailure[];
}

// --- Health -----------------------------------------------------------------------------------------------------

/** How a project's governance health is produced. */
export type HealthMode = "on_demand" | "snapshot_interval" | "snapshot_on_change";

export const HEALTH_MODE_LABEL: Record<HealthMode, string> = {
  on_demand: "On demand",
  snapshot_interval: "Snapshot at an interval",
  snapshot_on_change: "Snapshot on change",
};

export const HEALTH_MODE_DESCRIPTION: Record<HealthMode, string> = {
  on_demand: "Computed for each viewer when they open it. Nothing is stored.",
  snapshot_interval: "A stored snapshot, refreshed at the chosen interval.",
  snapshot_on_change: "A stored snapshot, recomputed on the first read after the project's records change.",
};

/** Where a health setting in force comes from. */
export type HealthSettingSource = "project" | "organization" | "default";

export const HEALTH_SETTING_SOURCE_LABEL: Record<HealthSettingSource, string> = {
  project: "Set by this project",
  organization: "Inherited from the organisation",
  default: "Built-in default",
};

export interface HealthRunner {
  id: string;
  name: string;
}

export interface HealthSettings {
  can_manage: boolean;
  mode: HealthMode;
  mode_source: HealthSettingSource;
  interval_hours: number;
  interval_source: HealthSettingSource;
  own_mode: HealthMode | null;
  own_interval_hours: number | null;
  organization_mode: HealthMode;
  organization_interval_hours: number;
  checks_runner: HealthRunner | null;
  runner_problem: string | null;
  interval_options: number[];
  on_demand_record_limit: number;
  checks_enabled: boolean;
}

export interface HealthSettingsValues {
  mode: HealthMode | null;
  interval_hours: number | null;
  checks_runner_id: string | null;
}

export interface HealthDefault {
  mode: HealthMode;
  interval_hours: number;
  interval_options: number[];
}

export interface HealthCategory {
  key: string;
  label: string;
  artefact_type: string;
  kind: "completion" | "outstanding";
  total: number;
  done: number;
  outstanding: number;
  percent: number | null;
}

export interface HealthReview {
  artefact_type: string;
  label: string;
  due: number;
}

export interface HealthCheckType {
  artefact_type: string;
  checked: number;
  failing: number;
  percent_passing: number | null;
}

export interface HealthCheck {
  key: string;
  name: string;
  types: HealthCheckType[];
}

export type HealthChecksStatus = "not_enabled" | "current" | "carried_forward" | "not_run" | "runner_unavailable";

export const HEALTH_CHECKS_STATUS_LABEL: Record<HealthChecksStatus, string> = {
  not_enabled: "No baseline checks are enabled.",
  current: "Current",
  carried_forward: "Carried forward from the last run",
  not_run: "Not run yet",
  runner_unavailable: "The configured person cannot run the checks",
};

export interface HealthChecks {
  status: HealthChecksStatus;
  run_by: HealthRunner | null;
  run_at: string | null;
  checks: HealthCheck[];
}

export interface Health {
  mode: HealthMode;
  source: "live" | "snapshot";
  computed_at: string;
  stale: boolean;
  can_refresh: boolean;
  categories: HealthCategory[];
  reviews: HealthReview[];
  checks: HealthChecks;
}

/** The label of a snapshot interval in hours: hours up to a day, then whole days. */
export function healthIntervalLabel(hours: number): string {
  if (hours < 24) return hours === 1 ? "Every hour" : `Every ${hours} hours`;
  const days = hours / 24;
  return days === 1 ? "Every day" : `Every ${days} days`;
}
