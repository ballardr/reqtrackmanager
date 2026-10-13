/**
 * Module: modules/stakeholders/types
 *
 * Frontend types for the Stakeholders & Personas module (docs/plans/
 * module-02-stakeholders-and-personas-plan.md), Phase 1.1 (Persona) and
 * Phase 1.2 (Stakeholder) — the wire shapes of `backend/app/modules/
 * stakeholders/schemas.py` plus the label/tone maps every rendered enum value
 * must go through (UX style guide principle 12).
 *
 * Neither artefact has an approval gate, so each lifecycle is the three-state
 * `draft | active | retired`. `PersonaFieldValues`/`StakeholderFieldValues`
 * deliberately exclude the people fields (`owner`, `champion`, `user_id`): the
 * detail pages assign those through `RecordPrincipalField`, the same split
 * Guiding Principle makes for its owner. `owner` and `champion` are principals
 * (a user, an organisation group or a project group), returned resolved.
 */
import type { BadgeTone, Principal } from "../../api/types";

export type PersonaScope = "organization" | "project";
export type PersonaStatus = "draft" | "active" | "retired";

export const PERSONA_STATUS_LABEL: Record<PersonaStatus, string> = {
  draft: "Draft",
  active: "Active",
  retired: "Retired",
};

export const PERSONA_STATUS_TONE: Record<PersonaStatus, BadgeTone> = {
  draft: "muted",
  active: "accent",
  retired: "muted",
};

export const PERSONA_SCOPE_LABEL: Record<PersonaScope, string> = {
  organization: "Organisation",
  project: "Project",
};

/** Where a project's resolved persona weight came from (`PersonaOut.weight_source`). */
export type PersonaWeightSource = "project" | "ancestor_project" | "persona" | "none";

/** Named for `OverridePill`'s `defaultLabel` — see docs/ux-style-guide.md,
 * "Pattern: scoring and inherited settings". */
export const PERSONA_WEIGHT_SOURCE_LABEL: Record<PersonaWeightSource, string> = {
  project: "Set on this project",
  ancestor_project: "Inherited from parent project",
  persona: "Persona's own weight",
  none: "Not weighted (equal weighting)",
};

/** A persona merged with its current version. `effective_weight`,
 * `weight_override`, `weight_source` and, for an org persona, `project_hidden`,
 * `hidden_override` and `hidden_source` (whether the project hides it, its own
 * override, and who supplied the effective value) are only populated by the
 * project-scoped endpoints. */
export interface Persona {
  id: string;
  scope: PersonaScope;
  organization_id: string | null;
  project_id: string | null;
  creator_id: string;
  is_archived: boolean;
  archived_at: string | null;
  archived_by: string | null;
  name: string;
  description: string;
  persona_type_id: string | null;
  persona_type_name: string | null;
  role_title: string;
  goals: string;
  needs: string;
  behaviours: string;
  context_environment: string;
  skills_proficiency: string;
  frequency_of_use: string;
  constraints: string;
  weight: number | null;
  status: PersonaStatus;
  owner: Principal | null;
  champion: Principal | null;
  version_number: number;
  effective_weight: number | null;
  weight_override: number | null;
  weight_source: PersonaWeightSource | null;
  project_hidden: boolean | null;
  hidden_override: boolean | null;
  hidden_source: HiddenSource | null;
  created_at: string;
  updated_at: string;
}

export interface PersonaVersion {
  id: string;
  persona_id: string;
  version_number: number;
  valid_from: string;
  valid_to: string | null;
  name: string;
  status: PersonaStatus;
  weight: number | null;
  owner: Principal | null;
  champion: Principal | null;
  change_note: string;
  created_at: string;
}

/** The content fields the create/edit modal edits. `persona_type_id` is an
 * effective-type id (`null` for untyped); `weight` is `null` for "no weight". */
export interface PersonaFieldValues {
  name: string;
  description: string;
  persona_type_id: string | null;
  role_title: string;
  goals: string;
  needs: string;
  behaviours: string;
  context_environment: string;
  skills_proficiency: string;
  frequency_of_use: string;
  constraints: string;
  weight: number | null;
  change_note: string;
}

export interface PersonaComment {
  id: string;
  persona_id: string;
  author_id: string;
  author_display_name: string;
  body: string;
  created_at: string;
  edited_at: string | null;
  attachments: import("../../api/types").FileAsset[];
}

/** An org-scoped `PersonaTypeDefinition` row. */
export interface PersonaTypeDefinition {
  id: string;
  organization_id: string;
  name: string;
  sort_order: number;
  is_active: boolean;
}

/** One row of a project's effective Persona type list. */
export interface EffectivePersonaType {
  id: string;
  name: string;
  display_order: number;
  is_enabled: boolean;
  source: "org" | "project_override" | "project_local";
}


// --- Stakeholder (Phase 1.2) --------------------------------------------------

export type StakeholderScope = "organization" | "project";
export type StakeholderStatus = "draft" | "active" | "retired";

export const STAKEHOLDER_STATUS_LABEL: Record<StakeholderStatus, string> = {
  draft: "Draft",
  active: "Active",
  retired: "Retired",
};

export const STAKEHOLDER_STATUS_TONE: Record<StakeholderStatus, BadgeTone> = {
  draft: "muted",
  active: "accent",
  retired: "muted",
};

export const STAKEHOLDER_SCOPE_LABEL: Record<StakeholderScope, string> = {
  organization: "Organisation",
  project: "Project",
};

/** How often we aim to engage a stakeholder (`TargetCadence` on the backend). */
export type TargetCadence = "one_off" | "ad_hoc" | "weekly" | "monthly" | "quarterly" | "yearly";

export const TARGET_CADENCE_LABEL: Record<TargetCadence, string> = {
  one_off: "One-off",
  ad_hoc: "Ad hoc",
  weekly: "Weekly",
  monthly: "Monthly",
  quarterly: "Quarterly",
  yearly: "Yearly",
};

/** How an Engagement took place (`EngagementChannel` on the backend). */
export type EngagementChannel =
  | "email"
  | "call"
  | "meeting"
  | "workshop"
  | "interview"
  | "focus_group"
  | "usability_test"
  | "survey";

export const ENGAGEMENT_CHANNEL_LABEL: Record<EngagementChannel, string> = {
  email: "Email",
  call: "Call",
  meeting: "Meeting",
  workshop: "Workshop",
  interview: "Interview",
  focus_group: "Focus group",
  usability_test: "Usability test",
  survey: "Survey",
};

/** The power/interest grid quadrant a pair of Influence/Interest levels falls in. */
export type GridQuadrant = "manage_closely" | "keep_satisfied" | "keep_informed" | "monitor";

export const GRID_QUADRANT_LABEL: Record<GridQuadrant, string> = {
  manage_closely: "Manage closely",
  keep_satisfied: "Keep satisfied",
  keep_informed: "Keep informed",
  monitor: "Monitor",
};

/** `GET .../stakeholders/cadence-hint` — a hint only, never applied automatically. */
export interface CadenceHint {
  quadrant: GridQuadrant | null;
  suggested_cadence: TargetCadence | null;
}

/** Which project supplied an org Persona's or Stakeholder's effective
 * visibility (`hidden_source`). */
export type HiddenSource = "project" | "ancestor_project";

/** Named for the list's Visibility column (docs/ux-style-guide.md, "Pattern:
 * platform default vs. override"). */
export const HIDDEN_SOURCE_LABEL: Record<HiddenSource, string> = {
  project: "Hidden by this project",
  ancestor_project: "Hidden by a parent project",
};

/** A stakeholder merged with its current version. `project_hidden`,
 * `hidden_override` and `hidden_source` are only populated for an org
 * stakeholder returned by the project-scoped endpoints: whether it is hidden
 * from that project, the project's own override (null when it only inherits)
 * and the project that supplied the effective value. */
export interface Stakeholder {
  id: string;
  scope: StakeholderScope;
  organization_id: string | null;
  project_id: string | null;
  creator_id: string;
  is_archived: boolean;
  archived_at: string | null;
  archived_by: string | null;
  name: string;
  description: string;
  stakeholder_type_id: string | null;
  stakeholder_type_name: string | null;
  role: string;
  organisation_group: string;
  interests: string;
  responsibilities: string;
  goals_needs: string;
  priorities: string;
  constraints: string;
  workflows_scenarios: string;
  contact_info: string;
  target_cadence: TargetCadence | null;
  availability_constraints: string;
  influence_level_id: string | null;
  interest_level_id: string | null;
  status: StakeholderStatus;
  owner: Principal | null;
  user_id: string | null;
  version_number: number;
  created_at: string;
  updated_at: string;
  project_hidden: boolean | null;
  hidden_override: boolean | null;
  hidden_source: HiddenSource | null;
  /** The stakeholder's direct groups this view can see. */
  groups: StakeholderGroupRef[];
  /** Project view only: the date (YYYY-MM-DD) of the project's latest engagement they took part in. */
  last_engaged?: string | null;
}

export interface StakeholderVersion {
  id: string;
  stakeholder_id: string;
  version_number: number;
  valid_from: string;
  valid_to: string | null;
  name: string;
  status: StakeholderStatus;
  target_cadence: TargetCadence | null;
  owner: Principal | null;
  change_note: string;
  created_at: string;
}

/** The content fields the create/edit modal edits. `stakeholder_type_id` is an
 * effective-type id (`null` for untyped); the level ids and cadence are `null`
 * for "not set". */
export interface StakeholderFieldValues {
  name: string;
  description: string;
  stakeholder_type_id: string | null;
  role: string;
  organisation_group: string;
  interests: string;
  responsibilities: string;
  goals_needs: string;
  priorities: string;
  constraints: string;
  workflows_scenarios: string;
  contact_info: string;
  target_cadence: TargetCadence | null;
  availability_constraints: string;
  influence_level_id: string | null;
  interest_level_id: string | null;
  change_note: string;
}

export interface StakeholderComment {
  id: string;
  stakeholder_id: string;
  author_id: string;
  author_display_name: string;
  body: string;
  created_at: string;
  edited_at: string | null;
  attachments: import("../../api/types").FileAsset[];
}

/** One "represents" link seen from either end: the other record's id and
 * name, its scope, and the link's own id. */
export interface RepresentedLink {
  link_id: string;
  id: string;
  name: string;
  scope: "organization" | "project";
}


// --- Stakeholder Need (Phase 2) -----------------------------------------------

export type NeedStatus = "draft" | "active" | "retired";

export const NEED_STATUS_LABEL: Record<NeedStatus, string> = {
  draft: "Draft",
  active: "Active",
  retired: "Retired",
};

export const NEED_STATUS_TONE: Record<NeedStatus, BadgeTone> = {
  draft: "muted",
  active: "accent",
  retired: "muted",
};

/** A Stakeholder Need merged with its current version. Always project-scoped. */
export interface Need {
  id: string;
  project_id: string;
  creator_id: string;
  is_archived: boolean;
  archived_at: string | null;
  archived_by: string | null;
  name: string;
  description: string;
  rationale: string;
  status: NeedStatus;
  owner: Principal | null;
  version_number: number;
  created_at: string;
  updated_at: string;
}

export interface NeedVersion {
  id: string;
  need_id: string;
  version_number: number;
  valid_from: string;
  valid_to: string | null;
  name: string;
  status: NeedStatus;
  owner: Principal | null;
  change_note: string;
  created_at: string;
}

/** The content fields the create/edit modal edits. */
export interface NeedFieldValues {
  name: string;
  description: string;
  rationale: string;
  change_note: string;
}

export interface NeedComment {
  id: string;
  need_id: string;
  author_id: string;
  author_display_name: string;
  body: string;
  created_at: string;
  edited_at: string | null;
  attachments: import("../../api/types").FileAsset[];
}

/** Which kind of record has a need. */
export type NeedHolderKind = "stakeholder" | "persona";

/** One "has need" link seen from the need: the Stakeholder/Persona that has it. */
export interface NeedHolder {
  link_id: string;
  kind: NeedHolderKind;
  id: string;
  name: string;
  scope: "organization" | "project";
}

/** One "has need" link seen from a Stakeholder or Persona: the need. */
export interface HeldNeed {
  link_id: string;
  id: string;
  name: string;
  status: NeedStatus;
}

/** One "gives rise to" link: the Requirement the need led to. */
export interface NeedRequirement {
  link_id: string;
  id: string;
  unique_code: string;
  title: string;
}


// --- Stakeholder groups (Phase 3c) --------------------------------------------

/** A group a stakeholder is directly in, as listed on the stakeholder. */
export interface StakeholderGroupRef {
  id: string;
  name: string;
  scope: StakeholderScope;
  parent_group_id: string | null;
}

/** A node of the group tree; `member_count` counts direct members only. */
export interface StakeholderGroup extends StakeholderGroupRef {
  organization_id: string | null;
  project_id: string | null;
  description: string;
  exclusive_children: boolean;
  sort_order: number;
  member_count: number;
  child_count: number;
}

export interface StakeholderGroupFieldValues {
  name: string;
  description: string;
  parent_group_id: string | null;
  exclusive_children: boolean;
}

/** One stakeholder in a group; `direct` is false when it is only in a descendant. */
export interface StakeholderGroupMember {
  stakeholder_id: string;
  name: string;
  scope: StakeholderScope;
  direct: boolean;
}

/** A distinct free-text "Organisation / group" value that could become a group. */
export interface GroupTextProposal {
  name: string;
  stakeholder_count: number;
  existing_group_id: string | null;
}

export interface GroupFromTextResult {
  root_group_id: string;
  group_ids: string[];
  memberships_added: number;
}

// --- Engagements (Phase 4 backend, Phase 5 UI) --------------------------------

/** An Engagement as the project API returns it. `retention_due` is true once `retain_until` has been reached. */
export interface Engagement {
  id: string;
  project_id: string;
  creator_id: string;
  /** Project-scoped code, e.g. "ENG-003" (never reused). */
  unique_code: string;
  title: string;
  channel: EngagementChannel;
  /** YYYY-MM-DD. */
  engagement_date: string;
  /** Everyone who ran it, in the order given. */
  facilitators: Principal[];
  purpose: string;
  summary: string;
  notes: string;
  consent_recorded: boolean;
  /** YYYY-MM-DD, or null when no disposal date is set. */
  retain_until: string | null;
  retention_due: boolean;
  participant_count: number;
  anonymous_participant_count: number;
  created_at: string;
  updated_at: string;
}

/** The content fields the create/edit form edits (the facilitators are set from the detail page). */
export interface EngagementFieldValues {
  title: string;
  channel: EngagementChannel;
  engagement_date: string;
  purpose: string;
  summary: string;
  notes: string;
  consent_recorded: boolean;
  retain_until: string | null;
}

/** One row of a Stakeholder's engagement timeline (no notes: open the engagement for those). */
export interface StakeholderEngagement {
  id: string;
  title: string;
  channel: EngagementChannel;
  engagement_date: string;
}

export interface EngagementParticipant {
  link_id: string;
  stakeholder_id: string;
  name: string;
  scope: "organization" | "project";
}

export interface EngagementPersona {
  link_id: string;
  persona_id: string;
  name: string;
  scope: "organization" | "project";
}

export interface EngagementAudience {
  link_id: string;
  group_id: string;
  name: string;
  scope: "organization" | "project";
}

/** The result of aiming an engagement at a group: the audience link and the members it copied in. */
export interface EngagementAudienceAdded {
  audience: EngagementAudience;
  participants_added: EngagementParticipant[];
  already_participating: number;
}

/** A record an Engagement or finding raised or answered. */
export type OutcomeKind = "raised" | "answered";

export const OUTCOME_KIND_LABEL: Record<OutcomeKind, string> = {
  raised: "Raised",
  answered: "Answered",
};

/** The artefact types an outcome can point at (`engagements.OUTCOME_KINDS` on the backend). */
export type OutcomeTargetType = "pain_point" | "stakeholder_need" | "open_question";

export const OUTCOME_TARGET_TYPE_LABEL: Record<OutcomeTargetType, string> = {
  pain_point: "Pain Point",
  stakeholder_need: "Stakeholder Need",
  open_question: "Open Question",
};

export interface EngagementOutcome {
  link_id: string;
  kind: OutcomeKind;
  target_type: string;
  target_id: string;
  label: string;
}

/** One record the outcome picker can offer. */
export interface OutcomeTarget {
  id: string;
  label: string;
  status: string | null;
}

export interface EngagementComment {
  id: string;
  engagement_id: string;
  author_id: string;
  author_display_name: string;
  body: string;
  created_at: string;
  edited_at: string | null;
  attachments: import("../../api/types").FileAsset[];
}

/** Research extras: one ordered session prompt with the notes taken against it. */
export interface EngagementPrompt {
  id: string;
  engagement_id: string;
  sort_order: number;
  prompt: string;
  response_notes: string;
}

/** Research extras: a participant who is a label (and optionally a Persona) rather than a Stakeholder record. */
export interface AnonymousParticipant {
  id: string;
  engagement_id: string;
  label: string;
  persona_id: string | null;
  persona_name: string | null;
}

/** Research extras: something learned in an engagement. */
export interface ResearchFinding {
  id: string;
  project_id: string;
  engagement_id: string;
  creator_id: string;
  /** Project-scoped code, e.g. "FND-003" (never reused). */
  unique_code: string;
  title: string;
  description: string;
  created_at: string;
  updated_at: string;
}
