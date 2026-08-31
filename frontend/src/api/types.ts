/**
 * TypeScript mirrors of the backend's Pydantic response schemas
 * (backend/app/schemas/*.py). Kept as plain interfaces rather than a
 * generated client so the frontend has zero build-time dependency on the
 * backend (I-A-01: loosely coupled).
 */

export type ProjectRole = "project_manager" | "project_administrator" | "stakeholder" | "member";
export type OrgRole = "org_admin" | "project_creator" | "member";
export type StageStatus = "scoping" | "review" | "approved" | "completed" | "archived";
// Hierarchical projects: forward (parent -> child) RBAC-cascade mode — see
// backend/app/models/enums.py::ProjectRoleInheritanceMode and
// docs/decisions.md's "Hierarchical projects" entry.
export type ProjectRoleInheritanceMode = "none" | "mirror_all" | "mirror_role" | "member_only";

// Display-only wording (matches the design mocks); the underlying API value
// stays unchanged since it gates real approval/locking logic server-side.
export const STAGE_STATUS_LABEL: Record<StageStatus, string> = {
  scoping: "Scoping",
  review: "In review",
  approved: "Ready for use",
  completed: "Implemented",
  archived: "Archived",
};
// C-G-11: completion is an overlay marker independent of lifecycle status
// (`Requirement.is_completed`, below), not a `RequirementStatus` value —
// see docs/decisions.md's entry on this rework. `"completed"` deliberately
// does not appear here any more.
export type RequirementStatus = "draft" | "reviewed" | "approved" | "archived";
export const REQUIREMENT_STATUS_LABEL: Record<RequirementStatus, string> = {
  draft: "Draft",
  reviewed: "Reviewed",
  approved: "Approved",
  archived: "Archived",
};
export type RequirementLevel = "requirement" | "recommended" | "optional";
export const REQUIREMENT_LEVEL_LABEL: Record<RequirementLevel, string> = {
  requirement: "Requirement",
  recommended: "Recommended",
  optional: "Optional",
};
export type ChangeRequestKind = "new_requirement" | "modify_requirement" | "add_action";
export type ChangeRequestStatus = "draft" | "submitted" | "in_review" | "approved" | "rejected" | "withdrawn";
export const CHANGE_REQUEST_STATUS_LABEL: Record<ChangeRequestStatus, string> = {
  draft: "Draft",
  submitted: "Submitted",
  in_review: "In review",
  approved: "Approved",
  rejected: "Rejected",
  withdrawn: "Withdrawn",
};
export type RequirementActionOutcome = "pending" | "completed" | "failed";
export const REQUIREMENT_ACTION_OUTCOME_LABEL: Record<RequirementActionOutcome, string> = {
  pending: "Pending",
  completed: "Completed",
  failed: "Failed",
};

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

/**
 * Collapses a user's held `ProjectRole` set down to the precedence style
 * guide "Pattern: role display — effective highest role only" defines, for
 * compact summary contexts (a list row, a header badge) — see
 * docs/ux-style-guide.md and docs/ux-audit-2026-08.md's "Project role
 * display" finding. `project_manager` is the sole top tier: if held, it
 * alone is shown. Otherwise `project_administrator` and `stakeholder` are a
 * shared, mutually-equal second tier — both are shown if both are held,
 * since they aren't ordered relative to each other. Otherwise `member` is
 * the floor. Deliberately NOT applied to `OrgRole` — that's a different,
 * unordered three-value enum with no defined precedence in the style
 * guide's pattern, unlike `ProjectRole`'s real four-tier structure.
 *
 * As of the 2026-08-30 reversal (docs/decisions.md), this IS now applied to
 * access-audit views too — e.g. Org Admin's "View access" panel uses this
 * as each project row's *default* display, with a per-row toggle revealing
 * the full, uncollapsed set on demand, so audit detail stays reachable
 * without being the default view. See `docs/ux-style-guide.md`'s "Pattern:
 * role display" section for the current rule.
 */
export function collapseProjectRoles(roles: ProjectRole[]): ProjectRole[] {
  if (roles.includes("project_manager")) return ["project_manager"];
  const tierTwo = roles.filter((r) => r === "project_administrator" || r === "stakeholder");
  if (tierTwo.length > 0) return tierTwo;
  if (roles.includes("member")) return ["member"];
  return [];
}
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
  file_asset: "File",
  project_status_definition: "Project status",
  requirement_link_type_definition: "Link type",
  action_type_definition: "Action type",
  requirement_action: "Action",
  requirement_action_link: "Action link",
};

function capitalize(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

/** `entityType === "organization"` isn't in `ENTITY_TYPE_LABEL` since its
 * label depends on the deployment's organisation-label override
 * (`useOrgLabelCapitalized`) rather than being a fixed word — callers pass
 * it as `orgLabel`. */
export function activityEntityLabel(entityType: string, orgLabel: string): string {
  if (entityType === "organization") return orgLabel;
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
  completion_cleared_by_review: "cleared completion (failed review)",
  completion_cleared_via_change_request: "cleared completion via change request",
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
  email_footer_company_name: string | null;
  email_footer_website: string | null;
  email_footer_address: string | null;
}

export interface OrgImportResult {
  organization: Organization;
  warnings: string[];
}

export interface MergeConflict {
  id: string;
  kind: "project" | "report_template";
  name: string;
  existing_id: string;
}

export interface OrgMergePreviewResult {
  conflicts: MergeConflict[];
}

export interface OrgMergeResult {
  warnings: string[];
  projects_imported: number;
  projects_skipped: number;
  report_templates_imported: number;
  report_templates_overwritten: number;
}

export interface ServerSettings {
  accent_color_hex: string;
  default_logo_file_id: string | null;
  default_header_title: string | null;
  default_login_background_file_id: string | null;
  email_footer_company_name: string | null;
  email_footer_website: string | null;
  email_footer_address: string | null;
  org_label_singular: string | null;
  org_label_plural: string | null;
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

/** One row of `GET /projects/{id}/files` (ProjectFilesPage) — a file
 * reachable from a project's requirements, with the context needed to say
 * where it came from. `requirement_id`/`requirement_unique_code`/
 * `requirement_name` are set for "requirement_attachment"/
 * "comment_attachment" rows; `action_id`/`action_unique_code`/
 * `action_title` are set for "action_attachment" rows (an action may be
 * linked to zero, one, or several requirements, so it has no single owning
 * requirement to attribute the file to). See backend `ProjectFileOut`. */
export interface ProjectFile {
  file: FileAsset;
  uploaded_by_display_name: string;
  source: "requirement_attachment" | "action_attachment" | "comment_attachment";
  requirement_id: string | null;
  requirement_unique_code: string | null;
  requirement_name: string | null;
  action_id: string | null;
  action_unique_code: string | null;
  action_title: string | null;
  comment_id: string | null;
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

/** A project's outstanding (not-yet-accepted) `PendingInvite` — see
 * `PendingInviteOut`'s docstring in the backend schema. Standard
 * (non-SSO) invite flow only (Phase 3, docs/decisions.md); `status` is
 * computed server-side from `expires_at`, not stored. */
export type PendingInviteStatus = "pending" | "expired";
export const PENDING_INVITE_STATUS_LABEL: Record<PendingInviteStatus, string> = {
  pending: "Pending",
  expired: "Expired",
};

export interface PendingInvite {
  id: string;
  email: string;
  role: ProjectRole;
  status: PendingInviteStatus;
  created_at: string;
  expires_at: string;
}

/** An organisation's outstanding (not-yet-accepted) org-only `PendingInvite`
 * — see `OrgPendingInviteOut`'s docstring in the backend schema. The
 * org-level counterpart to `PendingInvite` above (Phase A, follow-up UX
 * batch): `GET /orgs/{id}/pending-invites` only ever returns `project_id
 * IS NULL` rows, and unlike the project-level shape this carries
 * `invited_by_display_name` (surfaced in Org Admin's merged Users table). */
export interface OrgPendingInvite {
  id: string;
  email: string;
  status: PendingInviteStatus;
  created_at: string;
  expires_at: string;
  invited_by_display_name: string;
}

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
  group_names: string[];
}

export interface OrgGroup {
  id: string;
  name: string;
  member_user_ids: string[];
  member_org_group_ids: string[];
  idp_synced_group_name: string | null;
  /** Only meaningful alongside `idp_synced_group_name` — a user whose IdP
   * groups/roles claim matches it is granted this `OrgRole` at SSO login
   * (2026-08 UX audit roadmap item 522). */
  granted_org_role: OrgRole | null;
}

/** A read-only "what does this user have access to" summary (2026-08 UX
 * audit, sixth pass: "No way to view a user's access") — see
 * `GET /orgs/{orgId}/users/{userId}/access`. */
export interface UserAccessGroupRef {
  id: string;
  name: string;
}

export interface UserAccessProject {
  project_id: string;
  project_name: string;
  roles: ProjectRole[];
  project_groups: UserAccessGroupRef[];
}

export interface UserAccess {
  org_groups: UserAccessGroupRef[];
  projects: UserAccessProject[];
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
  visibility: "only_specified" | "org_wide";
  terminology: Record<string, string>;
  status_id: string;
  // Hierarchical projects (docs/decisions.md). parent_project_id/
  // parent_project_name are both null unless the caller has effective view
  // access to the parent — a visibility-boundary redaction applied
  // server-side, not something this frontend needs to re-derive.
  parent_project_id: string | null;
  parent_project_name?: string | null;
  role_inheritance_mode: ProjectRoleInheritanceMode;
  role_inheritance_filter_role: ProjectRole | null;
  // Whether *this* project may be selected as a parent for other projects —
  // defaults to false; a project's own manager must opt in before the
  // "Parent project" picker elsewhere will offer it. Never redacted (unlike
  // parent_project_id/parent_project_name above) — it's this project's own
  // setting, not information about another project.
  can_be_parent: boolean;
}

/** One entry in a project's ancestor chain or direct-children list — just
 * enough to render a link/label. See `Project`'s visibility-boundary note:
 * a list of these never includes a project the caller can't view. */
export interface ProjectAncestor {
  id: string;
  name: string;
}

/** One node of the project hierarchy tree (`GET /projects/tree`). A node
 * whose real parent isn't in the caller's accessible set is rendered as a
 * root, never omitted or hinting at a hidden parent. */
export interface ProjectTreeNode {
  id: string;
  name: string;
  organization_id: string;
  is_archived: boolean;
  children: ProjectTreeNode[];
}

/** One entry in a project's member-source list (the source -> receiving
 * RBAC mechanism) — the other project this project consumes members from.
 * Managed entirely from the receiving side; see docs/decisions.md for why.
 * Originally restricted to a direct child and always MEMBER-only;
 * generalized to any same-organisation project, with `mirror_mode`/
 * `mirror_filter_role` controlling what's mirrored (same vocabulary as
 * `role_inheritance_mode`/`role_inheritance_filter_role`'s forward
 * mechanism, applied in reverse). */
export interface ProjectMemberSource {
  source_project_id: string;
  source_project_name: string;
  mirror_mode: ProjectRoleInheritanceMode;
  mirror_filter_role: ProjectRole | null;
}

export const PROJECT_ROLE_INHERITANCE_MODE_LABEL: Record<ProjectRoleInheritanceMode, string> = {
  none: "None",
  mirror_all: "Mirror all roles",
  mirror_role: "Mirror one role",
  member_only: "Member only",
};

// Access provenance (decision 10, docs/decisions.md) — why a user has a
// given effective role: one of five direct sources on this exact project
// (split from a single collapsed "direct" kind in the follow-up UX batch's
// Phase D, 2026-08-31 — see the backend's
// `_direct_effective_project_roles_by_kind` docstring for the full
// rationale), forward-inherited (role_inheritance_mode, with
// via_project_name/via_mode naming the ancestor hop), or member-source-
// inherited (via_project_name intentionally omitted for member_source —
// see the backend's get_effective_project_members_with_provenance
// docstring). Only `"direct_role"` — a genuine, individually-revocable
// `UserProjectRole` row — is ever safe to offer as toggle-off-able in a UI
// (`DELETE /{project_id}/roles/{user_id}/{role}` only ever deletes
// `UserProjectRole` rows): the other four all resolve through a group,
// nested-group, project-reference, or org-wide-visibility mechanism that
// endpoint has no effect on.
export type MemberSourceProvenanceKind =
  | "direct_role"
  | "direct_group"
  | "direct_org_group"
  | "direct_project_ref"
  | "direct_org_wide"
  | "forward_inherited"
  | "member_source_inherited";

/** True only for the one provenance kind that's a genuine, individually-
 * revocable `UserProjectRole` row — see `MemberSourceProvenanceKind`'s own
 * doc comment for why the other six kinds must never be offered as
 * toggle-off-able via `DELETE /{project_id}/roles/{user_id}/{role}`. */
export function isDirectRoleKind(kind: MemberSourceProvenanceKind): boolean {
  return kind === "direct_role";
}

export interface MemberSourceProvenance {
  kind: MemberSourceProvenanceKind;
  role: ProjectRole;
  via_project_id: string | null;
  via_project_name: string | null;
  via_mode: ProjectRoleInheritanceMode | null;
}

export interface EffectiveMember {
  user_id: string;
  display_name: string;
  email: string;
  effective_role: ProjectRole;
  sources: MemberSourceProvenance[];
}

export interface MaterializeResult {
  created: { user_id: string; role: string }[];
  skipped: { user_id: string; role: string }[];
}

/** Org-definable project status (C-G-XX) — seeded with Proposed/Active/
 * Abandoned/Completed per org, extensible/renamable/deletable like any
 * other definition list. See `docs/decisions.md` for why deletion requires
 * either zero usages or an explicit `reassign_to_id`. */
export interface ProjectStatusDefinition {
  id: string;
  organization_id: string;
  name: string;
  sort_order: number;
}

/** Org-definable, bidirectional requirement link type — a link is always
 * created from one requirement's point of view (the source), but must
 * render sensibly when viewed from either end, hence the separate forward/
 * reverse names (e.g. "Depends on" / "Is a dependency of"). */
export interface LinkTypeDefinition {
  id: string;
  organization_id: string;
  forward_name: string;
  reverse_name: string;
  sort_order: number;
}

/** Project-scoped requirement-action type (e.g. Review, Test) — project-
 * scoped rather than org-scoped, matching `CustomFieldDefinition`, per
 * `docs/decisions.md`. */
export interface ActionTypeDefinition {
  id: string;
  project_id: string;
  name: string;
  sort_order: number;
}

export interface ProjectImportResult {
  project: Project;
  warnings: string[];
}

export interface ProjectListItem extends Project {
  current_stage_name: string | null;
  current_stage_status: StageStatus | null;
  my_roles: ProjectRole[];
  is_favorite: boolean;
  organization_name: string;
  requirement_count: number;
  // Direct children, filtered to ones the caller can view (visibility
  // boundary — see `Project`'s note). No count of hidden ones either.
  children: ProjectAncestor[];
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
  member_user_ids: string[];
  member_org_group_ids: string[];
  /** Members defined as "the direct members of that other project" — see
   * `models.project.ProjectGroupMember.source_project_id`'s docstring. */
  member_source_project_ids: string[];
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
  description: string;
  status: RequirementStatus;
  owner_id: string;
  component_id: string;
  category_id: string;
  target_stage_id: string;
  level: RequirementLevel;
  sort_order: number;
  creator_id: string;
  is_archived: boolean;
  is_locked: boolean;
  // C-G-11 overlay marker, independent of `status` — see the note on
  // `RequirementStatus` above.
  is_completed: boolean;
  completed_at: string | null;
  completed_by: string | null;
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
  // Only populated by the cross-project `/me/reviews/due` listing
  // (`MyReviewsDuePage`) — its project-scoped sibling has the project in
  // context already (it's in the URL) and never sets this.
  project_name?: string | null;
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
  description: string;
  status: RequirementStatus;
  owner_id: string;
  target_stage_id: string;
  level: RequirementLevel;
  change_note: string;
  change_request_id: string | null;
  created_by: string;
  created_at: string;
  valid_to: string | null;
}

/**
 * A traceability link between two requirements, resolved server-side from
 * the point of view of whichever requirement `GET
 * /projects/{id}/requirements/{requirement_id}/links` was called for —
 * `direction`/`display_name`/`other_requirement_*` describe the *other*
 * end from that viewpoint, so the frontend never has to work out which
 * side it's looking from or which of `forward_name`/`reverse_name` to show.
 */
export interface RequirementLink {
  id: string;
  source_requirement_id: string;
  target_requirement_id: string;
  link_type_id: string;
  direction: "outgoing" | "incoming";
  display_name: string;
  other_requirement_id: string;
  other_requirement_unique_code: string;
  other_requirement_name: string;
}

/**
 * A required action (e.g. review, test) with its own project-scoped
 * identity (`unique_code`, like a requirement) — independent of any single
 * requirement so one action can be linked from several via
 * `RequirementActionLink` (see `routers/requirements.py`'s
 * requirement<->action linking endpoints). Never hard-deleted, only
 * archived (mirrors `Requirement.is_archived`).
 */
export interface RequirementAction {
  id: string;
  project_id: string;
  unique_code: string;
  action_type_id: string;
  title: string;
  description: string;
  outcome_status: RequirementActionOutcome;
  assignee_id: string | null;
  due_date: string | null;
  completed_at: string | null;
  completed_by: string | null;
  creator_id: string;
  is_archived: boolean;
  archived_at: string | null;
  archived_by: string | null;
  created_at: string;
  updated_at: string;
  comment_count: number;
}

export interface Comment {
  id: string;
  author_id: string;
  author_display_name: string;
  body: string;
  created_at: string;
  edited_at: string | null;
  reaction_count: number;
  reacted_by_me: boolean;
  attachments: FileAsset[];
}

/** Field names a MODIFY_REQUIREMENT change request may propose to change —
 * mirrors backend `CHANGEABLE_REQUIREMENT_FIELDS` (schemas/change_request.py).
 * A field not listed in `ChangeRequest.changed_fields` means "untouched",
 * not "cleared" — its `proposed_*` counterpart (if any) must be ignored. */
export const CHANGEABLE_REQUIREMENT_FIELDS = [
  "name",
  "reasoning",
  "clarification",
  "description",
  "target_stage_id",
  "level",
  "review_date",
  "review_lead_days",
  "reviewer_id",
  "custom_fields",
  "attachments",
] as const;
export type ChangeableRequirementField = (typeof CHANGEABLE_REQUIREMENT_FIELDS)[number];

export const CHANGEABLE_FIELD_LABEL: Record<ChangeableRequirementField, string> = {
  name: "Name",
  reasoning: "Reasoning",
  clarification: "Clarification",
  description: "Description",
  target_stage_id: "Target version",
  level: "Level",
  review_date: "Review date",
  review_lead_days: "Reminder lead time",
  reviewer_id: "Assigned reviewer",
  custom_fields: "Custom fields",
  attachments: "Attachments",
};

export interface ChangeRequest {
  id: string;
  project_id: string;
  requirement_id: string | null;
  kind: ChangeRequestKind;
  status: ChangeRequestStatus;
  creator_id: string;
  proposed_name: string | null;
  proposed_reasoning: string | null;
  proposed_clarification: string | null;
  proposed_description: string | null;
  proposed_target_stage_id: string | null;
  proposed_level: RequirementLevel | null;
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
  /** Which fields this MODIFY_REQUIREMENT change request actually proposes
   * to change — empty for NEW_REQUIREMENT change requests, which always
   * propose every field. See `CHANGEABLE_REQUIREMENT_FIELDS` above. */
  changed_fields: ChangeableRequirementField[];
  proposed_attachment_file_ids: string[];
  /** ADD_ACTION-only (2026-08 UX audit roadmap item 514) — either
   * `proposed_action_link_id` (link an existing action) or
   * `proposed_action_title` + `proposed_action_type_id` (create a new
   * one) is set, mutually exclusive. */
  proposed_action_link_id: string | null;
  proposed_action_title: string | null;
  proposed_action_description: string | null;
  proposed_action_type_id: string | null;
  proposed_action_assignee_id: string | null;
  proposed_action_due_date: string | null;
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

/**
 * Where clicking a notification should navigate — `null` means it isn't
 * navigable (e.g. a password-changed notification about the viewer's own
 * account). Falls back to the project overview when `entity_type`/
 * `entity_id` aren't set but `project_id` is (e.g. "you were added to
 * project X" carries no specific entity, just the project itself).
 */
export function notificationLink(n: Notification): string | null {
  if (n.project_id && n.entity_type && n.entity_id) {
    if (n.entity_type === "requirement") return `/projects/${n.project_id}/requirements/${n.entity_id}`;
    if (n.entity_type === "change_request") return `/projects/${n.project_id}/change-requests/${n.entity_id}`;
    if (n.entity_type === "project_stage") return `/projects/${n.project_id}/admin`;
  }
  if (n.project_id) return `/projects/${n.project_id}`;
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
  default_report_template_id: string | null;
}

export interface OrgReportDefaults {
  intro: string;
  chapters: ReportChapter[];
  appendices: ReportChapter[];
}

export type ExternalUserPolicy = "disabled" | "org_domain_only" | "anyone";

/** SSO group→role mapping used to live here (`sso_group_mappings`) — it's
 * now a per-`OrgGroup` property (`OrgGroup.granted_org_role`, alongside
 * `idp_synced_group_name`) instead of a disconnected flat list — 2026-08
 * UX audit roadmap item 522. */
export interface OrgAdvancedSettings {
  smtp_host: string | null;
  smtp_port: number | null;
  smtp_username: string | null;
  smtp_use_tls: boolean;
  pat_max_lifetime_days: number | null;
  require_2fa: boolean;
  allow_self_signup: boolean;
  auto_accept_email_domain: string | null;
  external_user_policy: ExternalUserPolicy;
  allow_relaxed_child_project_creation: boolean;
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
  chapters_per_component: boolean;
}

export interface OrgSsoConfig {
  slug: string | null;
  sso_enabled: boolean;
  sso_only: boolean;
  oidc_issuer_url: string | null;
  oidc_client_id: string | null;
  oidc_required_group: string | null;
}

export interface ScimTokenStatus {
  enabled: boolean;
  token_prefix: string | null;
}

export interface ScimTokenCreated {
  token: string;
  token_prefix: string;
}

export interface MyOrgGroup {
  id: string;
  name: string;
  direct: boolean;
}

export interface MyProjectMembership {
  id: string;
  name: string;
  roles: ProjectRole[];
}

export interface MyOrgMembership {
  organization_id: string;
  organization_name: string;
  org_roles: OrgRole[];
  groups: MyOrgGroup[];
  projects: MyProjectMembership[];
}

export interface MyMemberships {
  organizations: MyOrgMembership[];
}

export interface OrgLoginInfo {
  name: string;
  slug: string;
  logo_file_id: string | null;
  login_background_file_id: string | null;
  sso_enabled: boolean;
  sso_only: boolean;
}

/** The running backend's own build identity — `GET /api/v1/system/version`. */
export interface SystemVersion {
  version: string;
  git_sha: string;
  build_date: string;
}
