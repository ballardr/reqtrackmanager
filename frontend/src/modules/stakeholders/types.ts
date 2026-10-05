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
  owner_id: string | null;
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


// --- Relationships (Phase 3) ---------------------------------------------------

/** Who can hold a §10.5 relationship (the other artefacts' own links have
 * dedicated shapes above). */
export type RelationshipHolderKind = "stakeholder" | "persona";

/** One declared relationship kind (`GET .../relationship-kinds`). A kind with
 * no `available_target_types` is reserved: its target module isn't installed. */
export interface RelationshipKind {
  key: string;
  /** Holder → target wording, e.g. "Experiences" (also the label shown). */
  forward: string;
  /** Target → holder wording, e.g. "Is experienced by". */
  reverse: string;
  holder_types: RelationshipHolderKind[];
  target_types: string[];
  available_target_types: string[];
}

/** One relationship seen from its holder. */
export interface Relationship {
  link_id: string;
  kind: string;
  forward: string;
  target_type: string;
  target_id: string;
  label: string;
  is_archived: boolean;
}

/** A record a relationship picker offers. */
export interface RelationshipTarget {
  id: string;
  label: string;
}

/** One relationship seen from its target: the Stakeholder or Persona. */
export interface IncomingRelationship {
  link_id: string;
  kind: string;
  reverse: string;
  holder_type: RelationshipHolderKind;
  holder_id: string;
  holder_name: string;
  scope: "organization" | "project";
}

/** Display names of the artefact types a relationship can point at. Targets
 * are other modules' records, so a type this map doesn't know falls back to
 * the raw key rather than being hidden. */
export const RELATIONSHIP_TARGET_TYPE_LABEL: Record<string, string> = {
  requirement: "Requirement",
  pain_point: "Pain Point",
  decision: "Decision",
  design: "Design",
  system_element: "System Element",
};

/** `RELATIONSHIP_TARGET_TYPE_LABEL`'s entry for `targetType`, or the key itself. */
export function relationshipTargetTypeLabel(targetType: string): string {
  return RELATIONSHIP_TARGET_TYPE_LABEL[targetType] ?? targetType;
}
