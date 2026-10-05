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
 * deliberately exclude the people fields (`owner_id`, `champion_id`,
 * `user_id`): the detail pages assign those through `AssigneePicker`, the
 * same split Guiding Principle makes for its owner.
 */
import type { BadgeTone } from "../../api/types";

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
 * `weight_override` and `weight_source` are only populated by the
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
  owner_id: string | null;
  champion_id: string | null;
  version_number: number;
  effective_weight: number | null;
  weight_override: number | null;
  weight_source: PersonaWeightSource | null;
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

/** A stakeholder merged with its current version. */
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
  owner_id: string | null;
  user_id: string | null;
  version_number: number;
  created_at: string;
  updated_at: string;
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
