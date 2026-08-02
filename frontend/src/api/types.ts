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
export type RequirementLevel = "requirement" | "recommended";
export type ChangeRequestKind = "new_requirement" | "modify_requirement";
export type ChangeRequestStatus = "draft" | "submitted" | "in_review" | "approved" | "rejected" | "withdrawn";
export type LinkType = "relates_to" | "depends_on" | "derived_from";
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

export interface SystemUser {
  user_id: string;
  email: string;
  display_name: string;
  is_active: boolean;
  last_login_at: string | null;
  is_2fa_enabled: boolean;
  created_at: string;
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
  name: string;
  prefix: string;
  sort_order: number;
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
}

export interface SsoGroupMapping {
  sso_group: string;
  org_role: OrgRole;
}

export interface OrgAdvancedSettings {
  smtp_host: string | null;
  smtp_port: number | null;
  smtp_username: string | null;
  smtp_use_tls: boolean;
  sso_group_mappings: SsoGroupMapping[];
}

export interface ReportTemplate {
  id: string;
  organization_id: string;
  name: string;
  accent_color_hex: string;
  include_cover_page: boolean;
  include_logo: boolean;
  footer_text: string | null;
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
