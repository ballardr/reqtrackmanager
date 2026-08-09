/**
 * TypeScript mirrors of the backend's Pydantic response schemas
 * (backend/app/schemas/*.py). Kept as plain interfaces rather than a
 * generated client so the frontend has zero build-time dependency on the
 * backend (I-A-01: loosely coupled).
 */

export type ProjectRole = "project_manager" | "project_administrator" | "stakeholder" | "member";
export type OrgRole = "org_admin" | "project_creator" | "member";
export type StageStatus = "scoping" | "review" | "approved" | "completed" | "archived";

// Display-only wording (matches the design mocks); the underlying API value
// stays unchanged since it gates real approval/locking logic server-side.
export const STAGE_STATUS_LABEL: Record<StageStatus, string> = {
  scoping: "Scoping",
  review: "In review",
  approved: "Ready for use",
  completed: "Implemented",
  archived: "Archived",
};
export type RequirementStatus = "draft" | "reviewed" | "approved" | "completed" | "archived";
export const REQUIREMENT_STATUS_LABEL: Record<RequirementStatus, string> = {
  draft: "Draft",
  reviewed: "Reviewed",
  approved: "Approved",
  completed: "Completed",
  archived: "Archived",
};
export type RequirementLevel = "requirement" | "recommended";
export const REQUIREMENT_LEVEL_LABEL: Record<RequirementLevel, string> = {
  requirement: "Requirement",
  recommended: "Recommended",
};
export type ChangeRequestKind = "new_requirement" | "modify_requirement";
export type ChangeRequestStatus = "draft" | "submitted" | "in_review" | "approved" | "rejected" | "withdrawn";
export const CHANGE_REQUEST_STATUS_LABEL: Record<ChangeRequestStatus, string> = {
  draft: "Draft",
  submitted: "Submitted",
  in_review: "In review",
  approved: "Approved",
  rejected: "Rejected",
  withdrawn: "Withdrawn",
};
export type LinkType = "relates_to" | "depends_on" | "derived_from";

// Sentence-cased per the Australian Government Style Manual's "minimal
// capitalisation" rule — see docs/decisions.md. Every raw enum value
// rendered directly into the UI should go through one of these maps
// (or ENTITY_TYPE_LABEL/activityActionLabel below) rather than appearing
// verbatim; `?? value` fallbacks exist only as a safety net, not a design.
export const PROJECT_ROLE_LABEL: Record<ProjectRole, string> = {
  project_manager: "Project manager",
  project_administrator: "Project administrator",
  stakeholder: "Stakeholder",
  member: "Member",
};
export const ORG_ROLE_LABEL: Record<OrgRole, string> = {
  org_admin: "Org admin",
  project_creator: "Project creator",
  member: "Member",
};
export const CUSTOM_FIELD_ENTITY_KIND_LABEL: Record<CustomFieldEntityKind, string> = {
  requirement: "Requirement",
  change_request: "Change request",
};
export const CUSTOM_FIELD_TYPE_LABEL: Record<CustomFieldType, string> = {
  short_text: "Short text",
  long_text: "Long text",
  checkbox: "Checkbox",
  list: "List",
};

// Activity-feed labels (project overview/history, and the requirement/CR
// side-panel activity list) — shown as a standalone badge next to the
// actor/action text, so sentence-cased like every other badge in the app.
// Covers the `entity_type`/`action` values `services/changes.py` can
// actually surface in a project's activity feed; anything unmapped falls
// back to a humanised version of the raw value rather than looking broken.
export const ENTITY_TYPE_LABEL: Record<string, string> = {
  requirement: "Requirement",
  change_request: "Change request",
  change_request_task: "Change request task",
  change_request_vote: "Change request vote",
  project: "Project",
  project_stage: "Project stage",
  project_component: "Component",
  project_category: "Category",
  project_group: "Project group",
  user_project_role: "Project role",
  custom_field_definition: "Custom field",
  requirement_link: "Requirement link",
  organization: "Organisation",
  file_asset: "File",
};

function capitalize(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

export function activityEntityLabel(entityType: string): string {
  return ENTITY_TYPE_LABEL[entityType] ?? capitalize(entityType.replace(/_/g, " "));
}

const ACTIVITY_ACTION_LABEL: Record<string, string> = {
  created: "created",
  updated: "updated",
  archived: "archived",
  deleted: "deleted",
  submitted: "submitted",
  withdrawn: "withdrew",
  approved: "approved",
  rejected: "rejected",
  cast: "voted",
  reordered: "reordered",
  completed: "completed",
  uncompleted: "reopened",
  granted: "granted",
  revoked: "revoked",
  member_added: "added a member",
  member_removed: "removed a member",
  status_changed: "changed status",
  review_deadline_set: "set a review deadline",
  review_recorded: "recorded a review",
  file_attached: "attached a file",
  file_linked: "linked a file",
  file_unlinked: "unlinked a file",
  requirements_imported: "imported requirements",
  settings_updated: "updated settings",
  terminology_updated: "updated terminology",
  report_config_updated: "updated the report configuration",
  comment_added: "commented on",
};

export function activityActionLabel(action: string): string {
  return ACTIVITY_ACTION_LABEL[action] ?? action.replace(/_/g, " ");
}
export type DigestMode = "instant" | "daily" | "none";
export type NotificationType =
  | "project_joined"
  | "stage_scoping"
  | "stage_review"
  | "stage_approved"
  | "stage_completed"
  | "change_request_submitted"
  | "stakeholder_input_requested"
  | "change_request_approved"
  | "change_request_rejected"
  | "requirements_updated"
  | "password_changed"
  | "permission_granted"
  | "permission_revoked"
  | "comment_added";

export interface Notification {
  id: string;
  type: NotificationType;
  title: string;
  body: string;
  project_id: string | null;
  entity_type: string | null;
  entity_id: string | null;
  created_at: string;
  read_at: string | null;
}

export interface NotificationPreference {
  type: NotificationType;
  ui_enabled: boolean;
  email_enabled: boolean;
}

export interface User {
  id: string;
  email: string;
  display_name: string;
  is_server_admin: boolean;
  is_active: boolean;
  landing_preference: string;
  theme_preference: string;
  pronouns: string | null;
  avatar_file_id: string | null;
  display_name_locked: boolean;
  is_2fa_enabled: boolean;
  email_digest_mode: DigestMode;
  /** General-purpose key/value bag for lightweight UI display preferences
   * that don't warrant their own dedicated field — e.g. per-list tile/list
   * view mode, keyed `view_mode:<page>`. Deliberately loosely typed so a
   * new preference of this kind never needs an API type change. */
  ui_preferences: Record<string, string | boolean>;
}

export interface TwoFactorChallenge {
  requires_2fa: true;
  challenge_token: string;
}

export interface Organization {
  id: string;
  name: string;
  created_at: string;
  logo_file_id: string | null;
  default_template_project_id: string | null;
  login_background_file_id: string | null;
  slug: string | null;
  is_active: boolean;
  disabled_at: string | null;
  accent_color_hex: string | null;
  header_title: string | null;
}

export interface ServerSettings {
  accent_color_hex: string;
  default_logo_file_id: string | null;
  default_header_title: string | null;
  default_login_background_file_id: string | null;
}

export type SignupMode = "disabled" | "always_on" | "org_specified";

export interface SelfSignupOrg {
  id: string;
  name: string;
}

export interface SignupConfig {
  signup_mode: SignupMode;
  self_signup_organizations: SelfSignupOrg[];
}

export interface FileAsset {
  id: string;
  organization_id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  uploaded_by: string;
  is_org_resource: boolean;
  created_at: string;
}

export interface OrgUser {
  user_id: string;
  email: string;
  display_name: string;
  is_active: boolean;
  is_archived: boolean;
  roles: OrgRole[];
  display_name_locked: boolean;
  last_login_at: string | null;
  is_2fa_enabled: boolean;
}

/** A search result for an email not (yet) a member of the searched org —
 * only present when `Organization.external_user_policy` allows it. */
export interface ExternalUserMatch {
  email: string;
  exists: boolean;
}

export interface OrgUserSearchResult {
  members: OrgUser[];
  external: ExternalUserMatch | null;
}

export interface OutsideDomainUser {
  user_id: string;
  email: string;
  display_name: string;
}

/** Outcome of adding a project member by email — see
 * `AssignByEmailOut`'s docstring in the backend schema for what each
 * value means. */
export type AssignByEmailOutcome = "added" | "invited" | "sso_provisioned";

export interface SystemUser {
  user_id: string;
  email: string;
  display_name: string;
  is_active: boolean;
  is_banned: boolean;
  last_login_at: string | null;
  is_2fa_enabled: boolean;
  created_at: string;
  is_server_admin: boolean;
  has_org_membership: boolean;
  organization_count: number;
  organization_names: string[];
}

export interface OrgGroup {
  id: string;
  name: string;
  member_user_ids: string[];
}

export interface Project {
  id: string;
  organization_id: string;
  name: string;
  summary: string;
  created_at: string;
  updated_at: string;
  is_archived: boolean;
  is_template: boolean;
  allow_member_change_requests: boolean;
  terminology: Record<string, string>;
}

export interface ProjectListItem extends Project {
  current_stage_name: string | null;
  current_stage_status: StageStatus | null;
  my_roles: ProjectRole[];
  is_favorite: boolean;
  organization_name: string;
  requirement_count: number;
}

export type CustomFieldEntityKind = "requirement" | "change_request";
export type CustomFieldType = "short_text" | "long_text" | "checkbox" | "list";

export interface CustomFieldDefinition {
  id: string;
  project_id: string;
  entity_kind: CustomFieldEntityKind;
  name: string;
  field_type: CustomFieldType;
  options: string[] | null;
  required: boolean;
  sort_order: number;
}

export interface ProjectStage {
  id: string;
  project_id: string;
  name: string;
  status: StageStatus;
  sort_order: number;
  is_current: boolean;
  approved_at: string | null;
  completed_at: string | null;
  completed_by: string | null;
  review_deadline: string | null;
}

export type StageReviewResponseChoice = "approved" | "rejected";

export interface StageReviewResponseEntry {
  id: string;
  stage_id: string;
  user_id: string;
  response: StageReviewResponseChoice;
  comment: string | null;
  responded_at: string;
}

export interface Component {
  id: string;
  project_id: string;
  name: string;
  prefix: string;
  sort_order: number;
}

export interface Category {
  id: string;
  project_id: string;
  component_id: string;
  name: string;
  prefix: string;
  sort_order: number;
}

export interface OrgProjectSummary {
  id: string;
  name: string;
  is_archived: boolean;
}

export interface ProjectGroup {
  id: string;
  name: string;
  role: ProjectRole;
  is_default: boolean;
  member_user_ids: string[];
  member_org_group_ids: string[];
}

export interface StageProgress {
  stage_id: string;
  name: string;
  status: StageStatus;
  requirement_count: number;
  completed_percent: number;
}

export interface ProjectMetrics {
  requirement_count: number;
  requirement_completed_percent: number;
  change_requests_proposed: number;
  change_requests_approved: number;
  change_requests_rejected: number;
  file_count: number;
  requirements_by_status: Record<string, number>;
  stage_progress: StageProgress[];
}

export interface Requirement {
  id: string;
  project_id: string;
  unique_code: string;
  name: string;
  reasoning: string;
  clarification: string;
  status: RequirementStatus;
  owner_id: string;
  component_id: string;
  category_id: string;
  target_stage_id: string | null;
  level: RequirementLevel;
  sort_order: number;
  creator_id: string;
  is_archived: boolean;
  is_locked: boolean;
  keywords: string[];
  custom_fields: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  is_subscribed: boolean;
  comment_count: number;
  has_open_change_request: boolean;
  requires_approval: boolean;
  review_date: string | null;
  review_lead_days: number | null;
  reviewer_id: string | null;
}

export type RequirementReviewOutcome = "met" | "failed";

export interface RequirementReview {
  id: string;
  requirement_id: string;
  reviewed_by: string;
  reviewed_at: string;
  outcome: RequirementReviewOutcome;
  comment: string | null;
}

export interface RequirementDueForReview {
  requirement_id: string;
  project_id: string;
  unique_code: string;
  name: string;
  review_date: string;
  reviewer_id: string | null;
  reviewer_name: string | null;
  component_id: string;
  component_name: string;
}

export interface RequirementVersionEntry {
  version_number: number;
  name: string;
  reasoning: string;
  clarification: string;
  status: RequirementStatus;
  owner_id: string;
  target_stage_id: string | null;
  level: RequirementLevel;
  change_note: string;
  change_request_id: string | null;
  created_by: string;
  created_at: string;
  valid_to: string | null;
}

export interface RequirementLink {
  id: string;
  source_requirement_id: string;
  target_requirement_id: string;
  link_type: LinkType;
}

export interface Comment {
  id: string;
  author_id: string;
  author_display_name: string;
  body: string;
  created_at: string;
  reaction_count: number;
  reacted_by_me: boolean;
}

export interface ChangeRequest {
  id: string;
  project_id: string;
  requirement_id: string | null;
  kind: ChangeRequestKind;
  status: ChangeRequestStatus;
  creator_id: string;
  proposed_name: string;
  proposed_reasoning: string;
  proposed_clarification: string;
  proposed_target_stage_id: string | null;
  proposed_level: RequirementLevel;
  reason: string;
  custom_fields: Record<string, unknown>;
  submitted_at: string | null;
  decided_at: string | null;
  decided_by: string | null;
  decision_note: string;
  created_at: string;
  is_subscribed: boolean;
  comment_count: number;
  requires_approval: boolean;
  proposed_review_date: string | null;
  proposed_review_lead_days: number | null;
  proposed_reviewer_id: string | null;
}

export interface ChangeRequestTask {
  id: string;
  change_request_id: string;
  description: string;
  assignee_id: string | null;
  due_date: string | null;
  is_done: boolean;
  completed_at: string | null;
  created_by: string;
  created_at: string;
}

export type ChangeRequestVoteChoice = "approve" | "reject";

export interface ChangeRequestVote {
  id: string;
  change_request_id: string;
  user_id: string;
  vote: ChangeRequestVoteChoice;
  comment: string | null;
  voted_at: string;
}

export interface ChangeRequestVoteTally {
  votes: ChangeRequestVote[];
  approve_count: number;
  reject_count: number;
}

export interface ChangeEntry {
  timestamp: string;
  entity_type: string;
  entity_id: string;
  action: string;
  actor_id: string | null;
  actor_display_name: string | null;
  detail: Record<string, unknown> | null;
}

/** Actor + action text for one activity entry (the entity-type badge, and
 * the linked item identifier from `activityEntryLink`, are rendered
 * separately by the caller) — the one shared description used by the
 * project overview activity card, the project history page, and the
 * requirement/change-request side-panel activity list, so the three no
 * longer describe the same data three different, inconsistent ways. */
export function describeActivityEntry(entry: ChangeEntry): string {
  const who = entry.actor_display_name ?? "Someone";
  const action = activityActionLabel(entry.action);
  const changeNote = entry.detail && typeof entry.detail.change_note === "string" ? entry.detail.change_note : "";
  return `${who} ${action}${changeNote ? ` — ${changeNote}` : ""}`;
}

/**
 * The item an activity entry is about, as a link + always-present label —
 * `services/changes.py::get_project_changes` resolves `detail.unique_code`/
 * `detail.name` (requirement) and `detail.proposed_name` (change request)
 * for every entry of that entity type, from current state, regardless of
 * which of the three underlying sources produced the entry, so this is
 * never missing for those two types. `null` for entity types with no
 * per-item page to link to (project structure/role/group events, ...).
 */
export function activityEntryLink(entry: ChangeEntry, projectId: string): { to: string; label: string } | null {
  const detail = entry.detail;
  if (entry.entity_type === "requirement") {
    const code = detail && typeof detail.unique_code === "string" ? detail.unique_code : null;
    const name = detail && typeof detail.name === "string" ? detail.name : null;
    return {
      to: `/projects/${projectId}/requirements/${entry.entity_id}`,
      label: code && name ? `${code} — ${name}` : code ?? name ?? entry.entity_id,
    };
  }
  if (entry.entity_type === "change_request") {
    const name = detail && typeof detail.proposed_name === "string" ? detail.proposed_name : null;
    return { to: `/projects/${projectId}/change-requests/${entry.entity_id}`, label: name ?? entry.entity_id };
  }
  return null;
}

export interface RequirementImportResult {
  created: number;
  errors: { row: number; message: string }[];
}

export interface ReportChapter {
  title: string;
  body: string;
}

export interface ProjectReportConfig {
  intro: string;
  chapters: ReportChapter[];
  appendices: ReportChapter[];
  intro_is_organisation_default: boolean;
  chapters_is_organisation_default: boolean;
  appendices_is_organisation_default: boolean;
}

export interface OrgReportDefaults {
  intro: string;
  chapters: ReportChapter[];
  appendices: ReportChapter[];
}

export interface SsoGroupMapping {
  sso_group: string;
  org_role: OrgRole;
}

export type ExternalUserPolicy = "disabled" | "org_domain_only" | "anyone";

export interface OrgAdvancedSettings {
  smtp_host: string | null;
  smtp_port: number | null;
  smtp_username: string | null;
  smtp_use_tls: boolean;
  sso_group_mappings: SsoGroupMapping[];
  pat_max_lifetime_days: number | null;
  require_2fa: boolean;
  allow_self_signup: boolean;
  auto_accept_email_domain: string | null;
  external_user_policy: ExternalUserPolicy;
}

export interface PersonalAccessTokenOrgRef {
  id: string;
  name: string;
}

export interface PersonalAccessTokenProjectRef {
  id: string;
  name: string;
}

export interface PersonalAccessTokenCreateResult {
  id: string;
  name: string;
  token: string;
  token_prefix: string;
  allowed_organizations: PersonalAccessTokenOrgRef[];
  allowed_projects: PersonalAccessTokenProjectRef[];
  expires_at: string;
  created_at: string;
}

export interface PersonalAccessToken {
  id: string;
  name: string;
  token_prefix: string;
  allowed_organizations: PersonalAccessTokenOrgRef[];
  allowed_projects: PersonalAccessTokenProjectRef[];
  expires_at: string;
  revoked_at: string | null;
  last_used_at: string | null;
  created_at: string;
}

export interface OrgPersonalAccessToken {
  id: string;
  user_id: string;
  user_email: string;
  user_display_name: string;
  name: string;
  token_prefix: string;
  expires_at: string;
  other_org_count: number;
  last_used_at: string | null;
  created_at: string;
}

export interface BulkRevokeResult {
  revoked_count: number;
}

export interface ReportTemplate {
  id: string;
  organization_id: string;
  name: string;
  accent_color_hex: string;
  include_cover_page: boolean;
  include_logo: boolean;
  footer_text: string | null;
  intro: string;
  chapters: ReportChapter[];
  appendices: ReportChapter[];
}

export interface OrgSsoConfig {
  slug: string | null;
  sso_enabled: boolean;
  sso_only: boolean;
  oidc_issuer_url: string | null;
  oidc_client_id: string | null;
  oidc_required_group: string | null;
}

export interface OrgLoginInfo {
  name: string;
  slug: string;
  logo_file_id: string | null;
  login_background_file_id: string | null;
  sso_enabled: boolean;
  sso_only: boolean;
}
