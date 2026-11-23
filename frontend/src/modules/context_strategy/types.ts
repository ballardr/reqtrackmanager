/**
 * Module: modules/context_strategy/types
 *
 * The Context & Strategy module's TypeScript shapes and enum label and tone maps, mirroring
 * `backend/app/modules/context_strategy/schemas.py` and `enums.py` field for field. A module keeps its enums and label
 * maps in its own directory, as `modules/decisions/types.ts` does, and every enum value rendered anywhere goes
 * through one of these maps, never a raw backend string. One file holds every artefact's shapes.
 *
 * Future State follows Strategy's conventions (the backend `FutureState*` mirrors `Strategy*`; see `schemas.py`).
 *
 * Pain Point differs from Strategy and Future State in two ways: it is project-scoped only (no `scope` /
 * `organization_id` discriminator, no organisation twin shapes), and it has a two-tier type vocabulary
 * (`PainPointTypeDefinition` organisation-scoped, `ProjectPainPointType` / `EffectivePainPointType` project-scoped).
 * See `PainPoint` below and `api.ts` (`projectPainPointApi`, `orgPainPointTypeApi`) for why it uses two plain objects
 * and not `buildStrategyApi`'s factory.
 *
 * Guiding Principle is organisation- or project-scoped like Strategy, with a shorter lifecycle (`GuidingPrincipleStatus`:
 * six states, no `under_review`; see `GUIDING_PRINCIPLE_STATUS_LABEL`) and its own `owner` field. The backend versions
 * `owner` as a content field, but `GuidingPrincipleDetailPage.tsx` gives it a dedicated `PrincipalPicker`, so `owner` is
 * excluded from `GuidingPrincipleFieldValues` as it is from `PainPointFieldValues`. Pain Point, Guiding Principle and
 * Open Question owners are principals (a user, an organisation group or a project group), returned resolved as a
 * `Principal`.
 *
 * Open Question is closest to Pain Point: project-scoped only (no organisation twin, no `scope` / `organization_id`)
 * and no version table (`OpenQuestion` is a single mutable row). It differs in having two branch points in its
 * lifecycle (see `OpenQuestionStatus`) and no `title` field: `question` is the display title, as
 * `GuidingPrinciple.name` is.
 */
import type { Principal } from "../../api/types";
import type { ProjectScopedRow } from "../../api/projectScope";

// --- Strategy lifecycle --------------------------------------------------

export type StrategyScope = "organization" | "project";

export const STRATEGY_SCOPE_LABEL: Record<StrategyScope, string> = {
  organization: "Organisation",
  project: "Project",
};

export type StrategyPriority = "low" | "medium" | "high";

export const STRATEGY_PRIORITY_LABEL: Record<StrategyPriority, string> = {
  low: "Low",
  medium: "Medium",
  high: "High",
};

export type StrategyTimeHorizon = "short_term" | "medium_term" | "long_term";

export const STRATEGY_TIME_HORIZON_LABEL: Record<StrategyTimeHorizon, string> = {
  short_term: "Short term",
  medium_term: "Medium term",
  long_term: "Long term",
};

export type StrategyStatus = "draft" | "proposed" | "under_review" | "approved" | "active" | "superseded" | "retired";

export const STRATEGY_STATUS_LABEL: Record<StrategyStatus, string> = {
  draft: "Draft",
  proposed: "Proposed",
  under_review: "Under review",
  approved: "Approved",
  active: "Active",
  superseded: "Superseded",
  retired: "Retired",
};

// Tone convention as `DECISION_STATUS_TONE` (modules/decisions/types.ts): muted = not yet actionable or no longer
// current, info = awaiting a decision, accent = in force. `RETIRED` is `muted`, not `danger`: retirement is an
// end-of-life outcome, not a negative one.
export const STRATEGY_STATUS_TONE: Record<StrategyStatus, import("../../api/types").BadgeTone> = {
  draft: "muted",
  proposed: "info",
  under_review: "info",
  approved: "accent",
  active: "accent",
  superseded: "muted",
  retired: "muted",
};

/** What each Strategy state means; the lifecycle track shows it as the step's tooltip. */
export const STRATEGY_STATUS_DESCRIPTION: Record<StrategyStatus, string> = {
  draft: "The Strategy is being written and its content can be edited.",
  proposed: "The Strategy has been put forward and awaits submission for review.",
  under_review: "An approver is reviewing the Strategy; it can still be sent back to Draft.",
  approved: "The Strategy has been formally approved and awaits activation.",
  active: "The Strategy is currently in force.",
  superseded: "Another Strategy has replaced this one; it is no longer current.",
  retired: "The Strategy's lifecycle has ended.",
};

/** Why a Strategy, Future State or Guiding Principle past review cannot be edited; the lifecycle track shows it beside the padlock. */
export const REVIEWED_LOCKED_REASON = "Locked: approved content can no longer be edited.";

// --- Relationship kinds -----------------------------------------

export type StrategyLinkKind =
  | "drives_requirement"
  | "defines_future_state"
  | "requires_resolution_of_open_question"
  | "contributes_to_strategy";

export const STRATEGY_LINK_KIND_LABEL: Record<StrategyLinkKind, string> = {
  drives_requirement: "Drives a Requirement",
  defines_future_state: "Defines a Future State",
  requires_resolution_of_open_question: "Requires resolution of an Open Question",
  contributes_to_strategy: "Contributes to another Strategy",
};

// --- Strategies ------------------------------------------------------------

export interface Strategy extends ProjectScopedRow {
  id: string;
  scope: StrategyScope;
  organization_id: string | null;
  project_id: string | null;
  /** Human-readable code (`PER-003`), numbered per owner; qualified by the owning project's or organisation's code where shown (`RecordCode`). */
  unique_code: string;
  creator_id: string;
  is_archived: boolean;
  archived_at: string | null;
  archived_by: string | null;

  title: string;
  objective: string;
  current_state: string;
  desired_future_state: string;
  rationale: string;
  expected_outcomes: string;
  constraints: string;
  measures_of_success: string;
  priority: StrategyPriority;
  time_horizon: StrategyTimeHorizon;
  status: StrategyStatus;
  version_number: number;
  is_locked: boolean;

  created_at: string;
  updated_at: string;
}

/** The editable content fields shared by create (`StrategyCreate`) and full replace (`StrategyUpdate`). `change_note` is update-only (a new Strategy has no prior version), so it is typed as always present (default `""`) and not sent on create. */
export interface StrategyFieldValues {
  title: string;
  objective: string;
  current_state: string;
  desired_future_state: string;
  rationale: string;
  expected_outcomes: string;
  constraints: string;
  measures_of_success: string;
  priority: StrategyPriority;
  time_horizon: StrategyTimeHorizon;
  change_note: string;
}

export interface StrategyVersion {
  id: string;
  strategy_id: string;
  version_number: number;
  valid_from: string;
  valid_to: string | null;
  title: string;
  objective: string;
  current_state: string;
  desired_future_state: string;
  rationale: string;
  expected_outcomes: string;
  constraints: string;
  measures_of_success: string;
  priority: StrategyPriority;
  time_horizon: StrategyTimeHorizon;
  status: StrategyStatus;
  change_note: string;
  created_by: string;
  created_at: string;
}

// --- Comments (no reaction mechanism — mirrors StrategyCommentOut's own docstring) -

export interface StrategyComment {
  id: string;
  strategy_id: string;
  author_id: string;
  author_display_name: string;
  body: string;
  created_at: string;
  edited_at: string | null;
  attachments: import("../../api/types").FileAsset[];
}

// --- Relationships ------------------------------------------------

/** One relationship touching a Strategy, from its viewpoint: the wire shape of the shared `ContextStrategyLinkOut` that all five source types return. `other_display_code` and `other_display_name` are `null` for an `other_type` the backend cannot resolve (only the reserved `"decision"` target; see `schemas.py`). */
export interface ContextStrategyLink {
  id: string;
  source_type: string;
  source_id: string;
  target_type: string;
  target_id: string;
  link_type_id: string | null;
  direction: "outgoing" | "incoming";
  display_name: string;
  other_type: string;
  other_id: string;
  other_display_code: string | null;
  other_display_name: string | null;
  created_by: string;
  created_at: string;
}

// --- Future State -----------------------------------------------
//
// `FutureState*` mirrors `Strategy*` field for field except its content fields (no `priority` or `time_horizon`) and
// `target_date` (nullable: an empty date input sends `null`, which the backend's `PUT` treats as an explicit clear; see
// `api.ts` for why no "explicitly set" flag is needed).

export type FutureStateScope = StrategyScope;

export const FUTURE_STATE_SCOPE_LABEL: Record<FutureStateScope, string> = STRATEGY_SCOPE_LABEL;

export type FutureStateStatus = StrategyStatus;

// Same seven-state lifecycle as `StrategyStatus`. The backend keeps `FutureStateStatus` as its own enum (`enums.py`)
// with textually identical values, so the frontend label and tone maps are reused.
export const FUTURE_STATE_STATUS_LABEL: Record<FutureStateStatus, string> = STRATEGY_STATUS_LABEL;
export const FUTURE_STATE_STATUS_TONE: Record<FutureStateStatus, import("../../api/types").BadgeTone> = STRATEGY_STATUS_TONE;

/** What each Future State state means; the lifecycle track shows it as the step's tooltip. */
export const FUTURE_STATE_STATUS_DESCRIPTION: Record<FutureStateStatus, string> = {
  draft: "The Future State is being written and its content can be edited.",
  proposed: "The Future State has been put forward and awaits submission for review.",
  under_review: "An approver is reviewing the Future State; it can still be sent back to Draft.",
  approved: "The Future State has been formally approved and awaits activation.",
  active: "The Future State is the current target.",
  superseded: "Another Future State has replaced this one; it is no longer current.",
  retired: "The Future State's lifecycle has ended.",
};

// --- Future State relationship kinds ------------------------------

export type FutureStateLinkKind = "related_to_pain_point" | "related_to_requirement" | "related_to_guiding_principle";

export const FUTURE_STATE_LINK_KIND_LABEL: Record<FutureStateLinkKind, string> = {
  related_to_pain_point: "Related to a Pain Point",
  related_to_requirement: "Related to a Requirement",
  related_to_guiding_principle: "Related to a Guiding Principle",
};

// --- Future States -----------------------------------------------------------

export interface FutureState extends ProjectScopedRow {
  id: string;
  scope: FutureStateScope;
  organization_id: string | null;
  project_id: string | null;
  /** Human-readable code (`PER-003`), numbered per owner; qualified by the owning project's or organisation's code where shown (`RecordCode`). */
  unique_code: string;
  creator_id: string;
  is_archived: boolean;
  archived_at: string | null;
  archived_by: string | null;

  title: string;
  current_state: string;
  desired_state: string;
  target_date: string | null;
  outcomes: string;
  success_measures: string;
  constraints: string;
  assumptions: string;
  status: FutureStateStatus;
  version_number: number;
  is_locked: boolean;

  created_at: string;
  updated_at: string;
}

/** The editable content fields shared by create (`FutureStateCreate`) and
 * full replace (`FutureStateUpdate`) — same `change_note`-is-update-only
 * convention as `StrategyFieldValues`. */
export interface FutureStateFieldValues {
  title: string;
  current_state: string;
  desired_state: string;
  target_date: string | null;
  outcomes: string;
  success_measures: string;
  constraints: string;
  assumptions: string;
  change_note: string;
}

export interface FutureStateVersion {
  id: string;
  future_state_id: string;
  version_number: number;
  valid_from: string;
  valid_to: string | null;
  title: string;
  current_state: string;
  desired_state: string;
  target_date: string | null;
  outcomes: string;
  success_measures: string;
  constraints: string;
  assumptions: string;
  status: FutureStateStatus;
  change_note: string;
  created_by: string;
  created_at: string;
}

// --- Comments (no reaction mechanism — mirrors StrategyComment's own docstring) ---

export interface FutureStateComment {
  id: string;
  future_state_id: string;
  author_id: string;
  author_display_name: string;
  body: string;
  created_at: string;
  edited_at: string | null;
  attachments: import("../../api/types").FileAsset[];
}

// --- Pain Point --------------------------------------------------
//
// Project-scoped only: unlike Strategy, Future State and Guiding Principle there is no organisation-scoped Pain
// Point, so no shape carries a `scope` / `organization_id` discriminator. `PainPoint` is a single mutable row (no
// `PainPointVersion`, see `models.py`).

export type PainPointPriority = "low" | "medium" | "high";

export const PAIN_POINT_PRIORITY_LABEL: Record<PainPointPriority, string> = STRATEGY_PRIORITY_LABEL;

/** Who may submit a Pain Point: any project member, or only a Pain Point Manager. */
export type PainPointSubmissionPolicy = "members" | "managers";

export const PAIN_POINT_SUBMISSION_POLICY_LABEL: Record<PainPointSubmissionPolicy, string> = {
  members: "Any project member",
  managers: "Pain Point Managers only",
};

/** Where a project's resolved submission policy comes from. */
export type PainPointSubmissionSource = "project" | "ancestor" | "organization" | "default";

export const PAIN_POINT_SUBMISSION_SOURCE_LABEL: Record<PainPointSubmissionSource, string> = {
  project: "this project",
  ancestor: "a parent project",
  organization: "the organisation",
  default: "the platform default",
};

/** `GET/PUT …/pain-point-settings` on a project: the resolved policy and what the caller may do under it. */
export interface PainPointSubmissionSettings {
  submission_policy: PainPointSubmissionPolicy;
  source: PainPointSubmissionSource;
  /** The project's own setting; null when it inherits. */
  own_policy: PainPointSubmissionPolicy | null;
  /** The organisation's default; null when it has not set one. */
  organization_default: PainPointSubmissionPolicy | null;
  can_submit: boolean;
  /** Why the caller cannot submit and where to raise the request instead; null when they can. */
  restriction_message: string | null;
}

/** `GET/PUT …/pain-point-settings` on an organisation. */
export interface OrgPainPointSubmissionSettings {
  submission_policy: PainPointSubmissionPolicy | null;
}

export type PainPointStatus = "submitted" | "triaged" | "rejected" | "duplicate" | "accepted" | "addressed" | "closed";

export const PAIN_POINT_STATUS_LABEL: Record<PainPointStatus, string> = {
  submitted: "Submitted",
  triaged: "Triaged",
  rejected: "Rejected",
  duplicate: "Duplicate",
  accepted: "Accepted",
  addressed: "Addressed",
  closed: "Closed",
};

// muted = not yet actionable or terminal-but-neutral, info = awaiting a decision or in progress, accent = a positive
// outcome, danger = a negative terminal outcome, as `STRATEGY_STATUS_TONE` and `DECISION_STATUS_TONE`. `DUPLICATE` is
// `muted`: it is a bookkeeping outcome, not a negative judgement (`PainPointLinkKind.DUPLICATE_OF`).
export const PAIN_POINT_STATUS_TONE: Record<PainPointStatus, import("../../api/types").BadgeTone> = {
  submitted: "muted",
  triaged: "info",
  rejected: "danger",
  duplicate: "muted",
  accepted: "info",
  addressed: "info",
  closed: "accent",
};

/** What each Pain Point state means; the lifecycle track shows it as the step's tooltip. */
export const PAIN_POINT_STATUS_DESCRIPTION: Record<PainPointStatus, string> = {
  submitted: "The Pain Point has been raised and awaits triage.",
  triaged: "The Pain Point has been assessed and awaits a decision to accept, reject or mark as a duplicate.",
  rejected: "The Pain Point was rejected and will not be worked on.",
  duplicate: "The Pain Point repeats another Pain Point and is tracked there.",
  accepted: "The Pain Point is accepted and is in active work.",
  addressed: "The underlying problem has been dealt with and awaits closure.",
  closed: "The Pain Point's lifecycle has ended.",
};

/** Why a Pain Point or Open Question at a terminal outcome cannot be edited; the lifecycle track shows it beside the padlock. */
export const TERMINAL_LOCKED_REASON = "Locked: a terminal outcome has been recorded.";

// --- Pain Point relationship kinds --------------------------------

export type PainPointLinkKind =
  | "drives_strategy"
  | "motivates_requirement"
  | "raises_open_question"
  | "related_to_future_state"
  | "duplicate_of";

export const PAIN_POINT_LINK_KIND_LABEL: Record<PainPointLinkKind, string> = {
  drives_strategy: "Drives a Strategy",
  motivates_requirement: "Motivates a Requirement",
  raises_open_question: "Raises an Open Question",
  related_to_future_state: "Related to a Future State",
  duplicate_of: "Duplicate of another Pain Point",
};

// --- Pain Point type vocabulary (two-tier model) ----------------------------

/** A plain, org-scoped `PainPointTypeDefinition` row — the shared base tier
 * an org admin (`pain_point_type_admin` module role) manages. */
export interface PainPointTypeDefinition {
  id: string;
  organization_id: string;
  name: string;
  sort_order: number;
  is_active: boolean;
  /** What belongs under this type; `null` when none was written. */
  definition: string | null;
}

/** One row of a project's effective Pain Point type list: every active organisation type (with its project override's name, order and enabled state, if any) plus every project-local type (`service.resolve_effective_pain_point_types`). `source` is `"org"` (no override), `"project_override"` or `"project_local"`; it decides whether an override can be created (org, project_override) or the row only edited in place (project_local). */
export interface EffectivePainPointType {
  id: string;
  name: string;
  display_order: number;
  is_enabled: boolean;
  source: "org" | "project_override" | "project_local";
  /** The project's own definition, else the organisation's; `null` when neither wrote one. */
  definition: string | null;
}

/** A raw `ProjectPainPointType` row (override or project-local) — returned
 * by the project-scoped create/override endpoints. */
export interface ProjectPainPointType {
  id: string;
  project_id: string;
  org_type_id: string | null;
  name_override: string | null;
  display_order_override: number | null;
  is_enabled: boolean;
  definition_override: string | null;
}

// --- Pain Points -------------------------------------------------------------

export interface PainPoint extends ProjectScopedRow {
  id: string;
  project_id: string;
  unique_code: string;
  pain_point_type_id: string;
  pain_point_type_name: string;
  creator_id: string;
  is_archived: boolean;
  archived_at: string | null;
  archived_by: string | null;

  title: string;
  description: string;
  source: string;
  impact: string;
  evidence: string;
  priority: PainPointPriority;
  status: PainPointStatus;
  owner: Principal | null;
  date_identified: string;
  /** A deliberate limitation (e.g. a lower-tier restriction that drives
   * upgrades): scored, but kept out of fix rankings by default. */
  is_intentional: boolean;
  is_locked: boolean;

  created_at: string;
  updated_at: string;
}

/** The editable content fields shared by create (`PainPointCreate`) and full replace (`PainPointUpdate`). There is no `change_note` (no version table), so both call sites use one shape. `owner` is excluded: "Assign owner" is a manager-tier action done through `PainPointDetailPage.tsx`'s `PrincipalPicker`. */
export interface PainPointFieldValues {
  pain_point_type_id: string;
  title: string;
  description: string;
  source: string;
  impact: string;
  evidence: string;
  priority: PainPointPriority;
  date_identified: string | null;
  /** Omitted on update = unchanged. */
  is_intentional?: boolean;
  /** Scores at creation (create only; an existing record is scored in its scoring panel). */
  scores?: PainPointScoreInput[];
}

// --- Pain Point scoring --------------------------------------------

/** How per-persona scores combine into one (`pain_point_scores.RollupMethod`). */
export type PainPointRollup = "weighted_average" | "worst_case" | "average";

export const PAIN_POINT_ROLLUP_LABEL: Record<PainPointRollup, string> = {
  weighted_average: "Weighted average",
  worst_case: "Worst case",
  average: "Plain average",
};

/** How a score row's persona resolves (`pain_point_scores.TargetStatus`). */
export type PainPointScoreTargetStatus = "general" | "active" | "inactive" | "unavailable";

export const PAIN_POINT_SCORE_TARGET_STATUS_LABEL: Record<PainPointScoreTargetStatus, string> = {
  general: "General",
  active: "Active",
  inactive: "Retired (not counted)",
  unavailable: "Persona unavailable",
};

/** A computed score: raw product, 0–1 normalised value and its rating band. */
export interface PainPointScoreValue {
  raw: number;
  normalised: number;
  band_label: string | null;
  band_tone: import("../../api/types").BadgeTone | null;
}

export interface PainPointScoreEntry {
  target_id: string | null;
  target_type: string | null;
  label: string | null;
  weight: number | null;
  status: PainPointScoreTargetStatus;
  /** What the row itself holds, level id by scoring axis key. */
  levels: Record<string, string>;
  /** What the row scores with: its own per-persona levels over the General row's. */
  effective_levels: Record<string, string>;
  score: PainPointScoreValue | null;
  is_blocker: boolean;
}

/** One Pain Point's roll-up under a model and method. */
export interface PainPointScoringSummary {
  pain_point_id: string;
  scope: "none" | "general" | "per_persona";
  score: PainPointScoreValue | null;
  counted: number;
  is_blocker: boolean;
  blocker_labels: string[];
  personas_degraded: boolean;
  entries: PainPointScoreEntry[];
}

export interface PainPointScoringTarget {
  id: string;
  label: string;
  weight: number | null;
  is_active: boolean;
}

/** `GET .../pain-points/{id}/scores`. `model_source` is a
 * `ScoringResolutionSource` or `"chosen"` (a non-default model was asked for). */
export interface PainPointScores extends PainPointScoringSummary {
  model_key: string;
  model_source: string;
  rollup: PainPointRollup;
  available_targets: PainPointScoringTarget[];
}

/** `GET .../pain-point-scoring-targets`: what a create form needs before the Pain Point exists.
 * `can_score` is false for a member who may create but not score. */
export interface PainPointScoringTargets {
  can_score: boolean;
  available_targets: PainPointScoringTarget[];
}

/** `GET .../pain-point-scores`. */
export interface PainPointScoringList {
  model_key: string;
  model_source: string;
  rollup: PainPointRollup;
  items: PainPointScoringSummary[];
}

/** One requested row when replacing a Pain Point's scores. */
export interface PainPointScoreInput {
  /** The persona, or null for the General row. */
  target_id: string | null;
  /** Level id by scoring axis key; a null level is not scored. */
  levels: Record<string, string | null>;
}

// --- Comments (no reaction mechanism — same shape as StrategyComment/FutureStateComment) -

export interface PainPointComment {
  id: string;
  pain_point_id: string;
  author_id: string;
  author_display_name: string;
  body: string;
  created_at: string;
  edited_at: string | null;
  attachments: import("../../api/types").FileAsset[];
}

// --- Guiding Principle -------------------------------------------
//
// Organisation- or project-scoped, like Strategy and Future State, with its own three-value priority enum (a separate
// backend `enum.Enum`; the frontend reuses `STRATEGY_PRIORITY_LABEL`'s content) and a shorter six-state lifecycle:
// `Draft -> Proposed -> Approved -> Active -> Superseded/Retired`. There is no `under_review` step (`PROPOSED` moves
// straight to `APPROVED`), and `PROPOSED` can send back to `DRAFT` with a mandatory comment.

export type GuidingPrincipleScope = StrategyScope;

export const GUIDING_PRINCIPLE_SCOPE_LABEL: Record<GuidingPrincipleScope, string> = STRATEGY_SCOPE_LABEL;

export type GuidingPrinciplePriority = "low" | "medium" | "high";

export const GUIDING_PRINCIPLE_PRIORITY_LABEL: Record<GuidingPrinciplePriority, string> = STRATEGY_PRIORITY_LABEL;

export type GuidingPrincipleStatus = "draft" | "proposed" | "approved" | "active" | "superseded" | "retired";

export const GUIDING_PRINCIPLE_STATUS_LABEL: Record<GuidingPrincipleStatus, string> = {
  draft: "Draft",
  proposed: "Proposed",
  approved: "Approved",
  active: "Active",
  superseded: "Superseded",
  retired: "Retired",
};

// Same tone convention as `STRATEGY_STATUS_TONE` — `RETIRED` is `muted`
// (end-of-life, not a negative outcome), `SUPERSEDED` is also `muted` (no
// longer current, but not a rejection).
export const GUIDING_PRINCIPLE_STATUS_TONE: Record<GuidingPrincipleStatus, import("../../api/types").BadgeTone> = {
  draft: "muted",
  proposed: "info",
  approved: "accent",
  active: "accent",
  superseded: "muted",
  retired: "muted",
};

/** What each Guiding Principle state means; the lifecycle track shows it as the step's tooltip. */
export const GUIDING_PRINCIPLE_STATUS_DESCRIPTION: Record<GuidingPrincipleStatus, string> = {
  draft: "The Guiding Principle is being written and its content can be edited.",
  proposed: "The Guiding Principle has been put forward and awaits approval; it can still be sent back to Draft.",
  approved: "The Guiding Principle has been formally approved and awaits activation.",
  active: "The Guiding Principle is currently in force.",
  superseded: "Another Guiding Principle has replaced this one; it is no longer current.",
  retired: "The Guiding Principle's lifecycle has ended.",
};

// --- Guiding Principle relationship kinds -------------------------
//
// `GuidingPrincipleLinkKind.GUIDES_DECISION`, the reserved Decision-target relationship, is absent: Decision links
// are generic links in the shared Links panel.

export type GuidingPrincipleLinkKind = "supports_strategy" | "informs_requirement";

export const GUIDING_PRINCIPLE_LINK_KIND_LABEL: Record<GuidingPrincipleLinkKind, string> = {
  supports_strategy: "Supports a Strategy",
  informs_requirement: "Informs a Requirement",
};

// --- Guiding Principles ------------------------------------------------------

export interface GuidingPrinciple extends ProjectScopedRow {
  id: string;
  scope: GuidingPrincipleScope;
  organization_id: string | null;
  project_id: string | null;
  /** Human-readable code (`PER-003`), numbered per owner; qualified by the owning project's or organisation's code where shown (`RecordCode`). */
  unique_code: string;
  creator_id: string;
  is_archived: boolean;
  archived_at: string | null;
  archived_by: string | null;

  name: string;
  principle_statement: string;
  rationale: string;
  priority: GuidingPrinciplePriority;
  status: GuidingPrincipleStatus;
  owner: Principal | null;
  version_number: number;
  is_locked: boolean;

  created_at: string;
  updated_at: string;
}

/** The editable content fields shared by create (`GuidingPrincipleCreate`) and full replace (`GuidingPrincipleUpdate`); `change_note` is update-only, as in `StrategyFieldValues`. `owner` is excluded, as in `PainPointFieldValues`; `GuidingPrincipleDetailPage.tsx`'s `PrincipalPicker` assigns it. */
export interface GuidingPrincipleFieldValues {
  name: string;
  principle_statement: string;
  rationale: string;
  priority: GuidingPrinciplePriority;
  change_note: string;
}

export interface GuidingPrincipleVersion {
  id: string;
  guiding_principle_id: string;
  version_number: number;
  valid_from: string;
  valid_to: string | null;
  name: string;
  principle_statement: string;
  rationale: string;
  priority: GuidingPrinciplePriority;
  status: GuidingPrincipleStatus;
  owner: Principal | null;
  change_note: string;
  created_by: string;
  created_at: string;
}

// --- Comments (no reaction mechanism — same shape as StrategyComment/FutureStateComment/PainPointComment) ---

export interface GuidingPrincipleComment {
  id: string;
  guiding_principle_id: string;
  author_id: string;
  author_display_name: string;
  body: string;
  created_at: string;
  edited_at: string | null;
  attachments: import("../../api/types").FileAsset[];
}

// --- Open Question ------------------------------------------------
//
// Project-scoped only, like Pain Point (`enums.py`: Decision is itself project-scoped only). `OpenQuestion` is a
// single mutable row with no version table.

export type OpenQuestionPriority = "low" | "medium" | "high";

export const OPEN_QUESTION_PRIORITY_LABEL: Record<OpenQuestionPriority, string> = STRATEGY_PRIORITY_LABEL;

// A branching lifecycle with two branch points: `WITHDRAWN` is reachable from both `INVESTIGATING` and
// `READY_FOR_DECISION` (a question can turn moot while under investigation), and `OPEN` only advances to
// `INVESTIGATING`. See `service.OpenQuestionStatus` for the backend account.
export type OpenQuestionStatus = "open" | "investigating" | "ready_for_decision" | "resolved" | "withdrawn";

export const OPEN_QUESTION_STATUS_LABEL: Record<OpenQuestionStatus, string> = {
  open: "Open",
  investigating: "Investigating",
  ready_for_decision: "Ready for Decision",
  resolved: "Resolved",
  withdrawn: "Withdrawn",
};

// Same tone convention as `PAIN_POINT_STATUS_TONE`: `WITHDRAWN` is `muted` (a question that turned moot or was
// answered elsewhere, not a negative judgement) and `RESOLVED` is the positive terminal outcome.
export const OPEN_QUESTION_STATUS_TONE: Record<OpenQuestionStatus, import("../../api/types").BadgeTone> = {
  open: "muted",
  investigating: "info",
  ready_for_decision: "info",
  resolved: "accent",
  withdrawn: "muted",
};

/** What each Open Question state means; the lifecycle track shows it as the step's tooltip. */
export const OPEN_QUESTION_STATUS_DESCRIPTION: Record<OpenQuestionStatus, string> = {
  open: "The question has been raised and awaits investigation.",
  investigating: "The question is being investigated.",
  ready_for_decision: "Investigation is complete and a decision can be made.",
  resolved: "A decision has been reached and the question is answered.",
  withdrawn: "The question was withdrawn because it is no longer relevant or was answered elsewhere.",
};

// --- Open Question relationship kinds -----------------------------
//
// Both are untyped "related to" associations. `RESOLVED_BY_DECISION`, the reserved Decision-target relationship, is
// absent: a Decision resolves a Question through a generic link.

export type OpenQuestionLinkKind = "related_to_strategy" | "related_to_requirement";

export const OPEN_QUESTION_LINK_KIND_LABEL: Record<OpenQuestionLinkKind, string> = {
  related_to_strategy: "Related to a Strategy",
  related_to_requirement: "Related to a Requirement",
};

// --- Open Questions ------------------------------------------------------------

export interface OpenQuestion extends ProjectScopedRow {
  id: string;
  project_id: string;
  unique_code: string;
  creator_id: string;
  is_archived: boolean;
  archived_at: string | null;
  archived_by: string | null;

  question: string;
  context: string;
  evidence: string;
  priority: OpenQuestionPriority;
  status: OpenQuestionStatus;
  owner: Principal | null;
  due_date: string | null;
  is_locked: boolean;

  created_at: string;
  updated_at: string;
}

/** The editable content fields shared by create (`OpenQuestionCreate`) and full replace (`OpenQuestionUpdate`). `owner` is excluded, as in `PainPointFieldValues`: assignment is a manager-tier action done through `OpenQuestionDetailPage.tsx`'s `PrincipalPicker`. */
export interface OpenQuestionFieldValues {
  question: string;
  context: string;
  evidence: string;
  priority: OpenQuestionPriority;
  due_date: string | null;
}

// --- Comments (no reaction mechanism — same shape as every other artefact's own comment type) ---

export interface OpenQuestionComment {
  id: string;
  open_question_id: string;
  author_id: string;
  author_display_name: string;
  body: string;
  created_at: string;
  edited_at: string | null;
  attachments: import("../../api/types").FileAsset[];
}

/** Pain Points still being worked (not rejected, duplicate, addressed or closed); mirrors the report's `OPEN_PAIN_POINT_STATUSES`. */
export const PAIN_POINT_OPEN_STATUSES: readonly PainPointStatus[] = ["submitted", "triaged", "accepted"];

/** Open Questions still unresolved; mirrors the report's `OPEN_QUESTION_OPEN_STATUSES`. */
export const OPEN_QUESTION_OPEN_STATUSES: readonly OpenQuestionStatus[] = ["open", "investigating", "ready_for_decision"];

/** Future States still expected to arrive (not superseded or retired); mirrors the report's `ROADMAP_FUTURE_STATE_STATUSES`. */
export const FUTURE_STATE_ROADMAP_STATUSES: readonly FutureStateStatus[] = ["draft", "proposed", "under_review", "approved", "active"];
