/**
 * Module: modules/stakeholders/types
 *
 * Frontend types for the Stakeholders & Personas module (docs/plans/
 * module-02-stakeholders-and-personas-plan.md), Phase 1.1 (Persona) — the
 * wire shapes of `backend/app/modules/stakeholders/schemas.py` plus the
 * label/tone maps every rendered enum value must go through (UX style guide
 * principle 12).
 *
 * Persona has no approval gate, so its lifecycle is the three-state
 * `draft | active | retired`. `PersonaFieldValues` deliberately excludes
 * `owner_id`/`champion_id`: `PersonaDetailPage` assigns those through
 * `AssigneePicker`, the same split Guiding Principle makes for its owner.
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
