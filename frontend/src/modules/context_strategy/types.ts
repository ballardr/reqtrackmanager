/**
 * Module: modules/context_strategy/types
 *
 * The Context & Strategy module's own TypeScript shapes and enum label/tone
 * maps for the Strategy artefact (docs/plans/module-01-context-and-strategy-
 * plan.md Phase 7.1) — mirrors `backend/app/modules/context_strategy/
 * schemas.py`/`enums.py` field-for-field, the same "module's own enums/label
 * maps live in the module's own directory, not `frontend/src/api/types.ts`"
 * convention `modules/decisions/types.ts`'s own docstring documents (per
 * CLAUDE.md's enum-label-map rule: every enum/status value rendered
 * anywhere must go through one of these maps, never a raw backend string).
 *
 * Only Strategy's own shapes were here at first (Phase 7.1's scope) — Pain
 * Point/Guiding Principle/Open Question's shapes are added by their own
 * Phase 7.3-7.5 sub-phases, into this same file, mirroring how
 * `context_strategy/schemas.py`/`enums.py` themselves grow one artefact's
 * worth of symbols per backend phase rather than being split per artefact.
 * Phase 7.2 (2026-09-29) adds Future State's own shapes below, following
 * every one of Strategy's own conventions identically (backend `FutureState*`
 * is itself an exact structural mirror of `Strategy*` — see `schemas.py`'s
 * own docstring).
 *
 * Phase 7.3 (2026-09-29) adds Pain Point's own shapes below — structurally
 * different from Strategy/Future State in two ways: (1) Pain Point is
 * **project-scoped only** (no `scope`/`organization_id` discriminator, no
 * "org twin" shapes), and (2) it has a project-scoped, two-tier **type**
 * vocabulary (`PainPointTypeDefinition` org-scoped, `ProjectPainPointType`/
 * `EffectivePainPointType` project-scoped) that Strategy/Future State have
 * no equivalent of. See `PainPoint`'s own docstring below for the full
 * field-shape account and `api.ts`'s docstring on `projectPainPointApi`/
 * `orgPainPointTypeApi` for why this phase uses two plain exported objects
 * rather than `buildStrategyApi`'s factory-instantiated-twice shape.
 *
 * Phase 7.4 (2026-09-29) adds Guiding Principle's own shapes below — back to
 * Strategy/Future State's own org-**or**-project scope shape (Phase 0 Q2),
 * but with a genuinely **shorter** lifecycle (`GuidingPrincipleStatus`: six
 * states, no `under_review` — see `GUIDING_PRINCIPLE_STATUS_LABEL`'s own
 * comment) and its own `owner_id` field. The backend versions `owner_id` as
 * a plain content field (`schemas.GuidingPrincipleUpdate`'s full-replace
 * payload includes it, closer to `FutureStateFieldValues.target_date`'s
 * shape than to Pain Point's genuinely separate update surface) — but this
 * phase's own frontend still gives it a dedicated `AssigneePicker` on
 * `GuidingPrincipleDetailPage.tsx` rather than a form field (**Decided by:
 * Agent** — see that page's own docstring for the full reasoning), so
 * `owner_id` is deliberately **excluded** from `GuidingPrincipleFieldValues`
 * the same way `PainPointFieldValues` excludes it.
 *
 * Phase 7.5 (2026-09-29) adds Open Question's own shapes below — the fifth
 * and last artefact type. Structurally closest to Pain Point: **project-
 * scoped only** (source overview §9 — no org twin, no `scope`/
 * `organization_id` discriminator) and no version table (Phase 5's own
 * scope decision — `OpenQuestion` is a single mutable row). Two differences
 * from Pain Point's own shape: (1) its own **branching lifecycle has two
 * branch points**, not one (`OpenQuestionStatus`'s own comment below); (2)
 * no `title` field at all — `question` itself doubles as this artefact's
 * display title, the same precedent `GuidingPrinciple.name` already
 * established, rather than Strategy/Future State/Pain Point's
 * added-by-convention `title`.
 */

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

// Same tone convention as `DECISION_STATUS_TONE` (modules/decisions/types.ts):
// muted = not yet actionable/no-longer-current, info = awaiting a decision,
// accent = a positive/in-force outcome. `ACTIVE` gets `accent` alongside
// `APPROVED` — both are "this Strategy is currently good" states, just at
// different points in its life; `RETIRED` is `muted` rather than `danger`
// since retirement (unlike Decision's `REJECTED`) isn't a negative outcome,
// just an end-of-life one.
export const STRATEGY_STATUS_TONE: Record<StrategyStatus, import("../../api/types").BadgeTone> = {
  draft: "muted",
  proposed: "info",
  under_review: "info",
  approved: "accent",
  active: "accent",
  superseded: "muted",
  retired: "muted",
};

// --- Relationship kinds (Phase 6) -----------------------------------------

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

export interface Strategy {
  id: string;
  scope: StrategyScope;
  organization_id: string | null;
  project_id: string | null;
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

/** The editable content fields shared by create (`StrategyCreate`) and full
 * replace (`StrategyUpdate`) — `change_note` is update-only (the backend's
 * own `StrategyCreate` has no such field, a new Strategy has no prior
 * version to explain a change from), so it's typed as always-present here
 * (defaulted `""`) and simply not sent by the create call site. */
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

// --- Relationships (Phase 6) ------------------------------------------------

/** One relationship touching a Strategy, from that Strategy's own viewpoint
 * — wire shape of the shared `ContextStrategyLinkOut` every one of this
 * module's five source artefact types returns. `other_display_code`/
 * `other_display_name` are `null` for an `other_type` the backend can't
 * resolve (in practice, only ever a reserved, not-yet-populated
 * `"decision"` target — see `schemas.py`'s own docstring). */
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

// --- Future State (Phase 7.2) -----------------------------------------------
//
// `FutureState*` mirrors `Strategy*` field-for-field except for its own
// content fields (no `priority`/`time_horizon` — Future State's own field
// list, per `schemas.FutureStateCreate`/`FutureStateOut`, has neither) and
// `target_date` (nullable — a plain HTML date input left empty sends `null`,
// which the backend's `PUT` treats as an explicit clear; see `api.ts`'s own
// docstring on why no separate "explicitly set" flag is needed client-side).

export type FutureStateScope = StrategyScope;

export const FUTURE_STATE_SCOPE_LABEL: Record<FutureStateScope, string> = STRATEGY_SCOPE_LABEL;

export type FutureStateStatus = StrategyStatus;

// Same seven-state lifecycle as `StrategyStatus` (Phase 0 Q1's follow-on:
// "Future State's lifecycle... mirror Strategy's in full") — the backend
// keeps `FutureStateStatus` as its own Python enum (two independent
// artefact types, two owned vocabularies, per `enums.py`'s own docstring),
// but its *values* are textually identical, so the frontend label/tone maps
// are reused directly rather than re-declared with the same content.
export const FUTURE_STATE_STATUS_LABEL: Record<FutureStateStatus, string> = STRATEGY_STATUS_LABEL;
export const FUTURE_STATE_STATUS_TONE: Record<FutureStateStatus, import("../../api/types").BadgeTone> = STRATEGY_STATUS_TONE;

// --- Future State relationship kinds (Phase 6) ------------------------------

export type FutureStateLinkKind = "related_to_pain_point" | "related_to_requirement" | "related_to_guiding_principle";

export const FUTURE_STATE_LINK_KIND_LABEL: Record<FutureStateLinkKind, string> = {
  related_to_pain_point: "Related to a Pain Point",
  related_to_requirement: "Related to a Requirement",
  related_to_guiding_principle: "Related to a Guiding Principle",
};

// --- Future States -----------------------------------------------------------

export interface FutureState {
  id: string;
  scope: FutureStateScope;
  organization_id: string | null;
  project_id: string | null;
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

// --- Pain Point (Phase 7.3) --------------------------------------------------
//
// Project-scoped only (source overview §6 — unlike Strategy/Future State/
// Guiding Principle, there is no organisation-scoped Pain Point, so none of
// these shapes carry a `scope`/`organization_id` discriminator). No
// `PainPointVersion` (Phase 3's own scope decision — see `models.py`'s
// docstring), so `PainPoint` below is a single mutable row, not an
// identity+version split the way `Strategy`/`FutureState` are.

export type PainPointPriority = "low" | "medium" | "high";

export const PAIN_POINT_PRIORITY_LABEL: Record<PainPointPriority, string> = STRATEGY_PRIORITY_LABEL;

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

// muted = not yet actionable/terminal-but-neutral, info = awaiting a
// decision/in progress, accent = a positive in-progress-to-done outcome,
// danger = a negative terminal outcome — same convention as `STRATEGY_
// STATUS_TONE`/`DECISION_STATUS_TONE`. `DUPLICATE` is `muted` rather than
// `danger` — it isn't a negative judgement on the Pain Point itself, just a
// bookkeeping outcome (see `PainPointLinkKind.DUPLICATE_OF`).
export const PAIN_POINT_STATUS_TONE: Record<PainPointStatus, import("../../api/types").BadgeTone> = {
  submitted: "muted",
  triaged: "info",
  rejected: "danger",
  duplicate: "muted",
  accepted: "info",
  addressed: "info",
  closed: "accent",
};

// --- Pain Point relationship kinds (Phase 6) --------------------------------

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

// --- Pain Point type vocabulary (Phase 0 Q3's two-tier model) ---------------

/** A plain, org-scoped `PainPointTypeDefinition` row — the shared base tier
 * an org admin (`pain_point_type_admin` module role) manages. */
export interface PainPointTypeDefinition {
  id: string;
  organization_id: string;
  name: string;
  sort_order: number;
  is_active: boolean;
}

/** One row of a project's *effective* Pain Point type list — every active
 * org type (its own project override's name/order/enabled state, if any)
 * plus every project-local type, per `service.resolve_effective_pain_point_
 * types`. `source` is `"org"` (no override), `"project_override"`, or
 * `"project_local"` — used to decide whether this row's own override can be
 * *created* (org/project_override) or only edited in place (project_local). */
export interface EffectivePainPointType {
  id: string;
  name: string;
  display_order: number;
  is_enabled: boolean;
  source: "org" | "project_override" | "project_local";
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
}

// --- Pain Points -------------------------------------------------------------

export interface PainPoint {
  id: string;
  project_id: string;
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
  owner_id: string | null;
  date_identified: string;
  /** A deliberate limitation (e.g. a lower-tier restriction that drives
   * upgrades): scored, but kept out of fix rankings by default. */
  is_intentional: boolean;
  is_locked: boolean;

  created_at: string;
  updated_at: string;
}

/** The editable content fields shared by create (`PainPointCreate`) and full
 * replace (`PainPointUpdate`) — unlike `StrategyFieldValues`, there is no
 * create/edit field-set asymmetry here (no `change_note` — no version
 * table), so both call sites use this same shape. `owner_id` is deliberately
 * **not** included — §6.5 places "Assign owner" on the manager tier, not the
 * create/edit content form, and `PainPointDetailPage.tsx`'s own dedicated
 * `AssigneePicker` control assigns it directly (**Decided by: Agent** — see
 * that page's own docstring). */
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
}

// --- Pain Point scoring (Phase 11) --------------------------------------------

/** How per-persona scores combine into one (`pain_point_scores.RollupMethod`). */
export type PainPointRollup = "weighted_average" | "worst_case" | "average";

export const PAIN_POINT_ROLLUP_LABEL: Record<PainPointRollup, string> = {
  weighted_average: "Weighted average",
  worst_case: "Worst case",
  average: "Plain average",
};

/** How a score row's persona resolves (`pain_point_scores.TargetStatus`). */
export type PainPointScoreTargetStatus = "all" | "active" | "inactive" | "unavailable";

export const PAIN_POINT_SCORE_TARGET_STATUS_LABEL: Record<PainPointScoreTargetStatus, string> = {
  all: "All personas",
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
  severity_level_id: string | null;
  frequency_level_id: string | null;
  confidence_level_id: string | null;
  score: PainPointScoreValue | null;
  is_blocker: boolean;
}

/** One Pain Point's roll-up under a model and method. */
export interface PainPointScoringSummary {
  pain_point_id: string;
  scope: "none" | "all_personas" | "per_persona";
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

/** `GET .../pain-point-scores`. */
export interface PainPointScoringList {
  model_key: string;
  model_source: string;
  rollup: PainPointRollup;
  items: PainPointScoringSummary[];
}

/** One requested row when replacing a Pain Point's scores. */
export interface PainPointScoreInput {
  target_id: string | null;
  severity_level_id: string | null;
  frequency_level_id: string | null;
  confidence_level_id: string | null;
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

// --- Guiding Principle (Phase 7.4) -------------------------------------------
//
// Org- **or** project-scoped (Phase 0 Q2's discriminator, same shape as
// Strategy/Future State), with its own three-value priority enum (its own
// backend `enum.Enum`, per `enums.py`'s "two independent artefact types, two
// owned vocabularies" reasoning — see `STRATEGY_PRIORITY_LABEL`'s own
// docstring for why the frontend nonetheless reuses that map's *content*
// directly rather than re-declaring it) and a **shorter**, six-state
// lifecycle: `Draft -> Proposed -> Approved -> Active -> Superseded/Retired`
// — no `under_review` step (`PROPOSED` moves straight to `APPROVED`), but
// `PROPOSED` can still send back to `DRAFT` with a mandatory comment (this
// module's "reject"-equivalent, same as Strategy's `send-back`).

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

// --- Guiding Principle relationship kinds (Phase 6) -------------------------
//
// `GuidingPrincipleLinkKind.GUIDES_DECISION` (§8.5's "Decision -> guided by
// -> Guiding Principle") is the reserved Decision-target relationship
// (module docstring) and is deliberately absent here — see
// `GuidingPrincipleRelationshipsSection.tsx`'s own present-but-reserved text.

export type GuidingPrincipleLinkKind = "supports_strategy" | "informs_requirement";

export const GUIDING_PRINCIPLE_LINK_KIND_LABEL: Record<GuidingPrincipleLinkKind, string> = {
  supports_strategy: "Supports a Strategy",
  informs_requirement: "Informs a Requirement",
};

// --- Guiding Principles ------------------------------------------------------

export interface GuidingPrinciple {
  id: string;
  scope: GuidingPrincipleScope;
  organization_id: string | null;
  project_id: string | null;
  creator_id: string;
  is_archived: boolean;
  archived_at: string | null;
  archived_by: string | null;

  name: string;
  principle_statement: string;
  rationale: string;
  priority: GuidingPrinciplePriority;
  status: GuidingPrincipleStatus;
  owner_id: string | null;
  version_number: number;
  is_locked: boolean;

  created_at: string;
  updated_at: string;
}

/** The editable content fields shared by create (`GuidingPrincipleCreate`)
 * and full replace (`GuidingPrincipleUpdate`) — same `change_note`-is-
 * update-only convention as `StrategyFieldValues`. `owner_id` is
 * deliberately **not** included here — see this file's own module docstring
 * above for why `GuidingPrincipleDetailPage.tsx`'s dedicated `AssigneePicker`
 * assigns it directly instead (**Decided by: Agent**, mirroring
 * `PainPointFieldValues`'s identical exclusion). */
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
  owner_id: string | null;
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

// --- Open Question (Phase 7.5) ------------------------------------------------
//
// Project-scoped only (source overview §9 — like Pain Point, no
// organisation-scoped Open Question exists; see `enums.py`'s own "Decision
// is itself project-scoped only" reasoning for why). No `OpenQuestionVersion`
// (Phase 5's own scope decision, same reasoning as Pain Point's missing
// version table) — `OpenQuestion` below is a single mutable row.

export type OpenQuestionPriority = "low" | "medium" | "high";

export const OPEN_QUESTION_PRIORITY_LABEL: Record<OpenQuestionPriority, string> = STRATEGY_PRIORITY_LABEL;

// A **branching** lifecycle with two branch points, not Pain Point's one —
// `WITHDRAWN` is reachable directly from both `INVESTIGATING` and
// `READY_FOR_DECISION` (a question can turn out moot while still under
// active investigation, not only once ready for a decision); `OPEN` itself
// only ever advances to `INVESTIGATING` (mirrors Pain Point's own precedent
// that a lifecycle's very first state doesn't skip straight to a terminal
// outcome). See `service.OpenQuestionStatus`'s own docstring for the full
// backend account.
export type OpenQuestionStatus = "open" | "investigating" | "ready_for_decision" | "resolved" | "withdrawn";

export const OPEN_QUESTION_STATUS_LABEL: Record<OpenQuestionStatus, string> = {
  open: "Open",
  investigating: "Investigating",
  ready_for_decision: "Ready for Decision",
  resolved: "Resolved",
  withdrawn: "Withdrawn",
};

// Same tone convention as `PAIN_POINT_STATUS_TONE` — `WITHDRAWN` is `muted`
// (a bookkeeping outcome for a question that turned out moot or already
// answered elsewhere, not a negative judgement), `RESOLVED` is the positive
// terminal outcome.
export const OPEN_QUESTION_STATUS_TONE: Record<OpenQuestionStatus, import("../../api/types").BadgeTone> = {
  open: "muted",
  investigating: "info",
  ready_for_decision: "info",
  resolved: "accent",
  withdrawn: "muted",
};

// --- Open Question relationship kinds (Phase 6) -----------------------------
//
// Both untyped "related to" associations (§9.2's own plain field naming, no
// causal verb, the same as Future State's own links). `RESOLVED_BY_DECISION`
// (§9.5, the reserved Decision-target relationship, Phase 0 Q5) is
// deliberately absent here — see `OpenQuestionRelationshipsSection.tsx`'s
// own docstring for why this section renders no "reserved" note either.

export type OpenQuestionLinkKind = "related_to_strategy" | "related_to_requirement";

export const OPEN_QUESTION_LINK_KIND_LABEL: Record<OpenQuestionLinkKind, string> = {
  related_to_strategy: "Related to a Strategy",
  related_to_requirement: "Related to a Requirement",
};

// --- Open Questions ------------------------------------------------------------

export interface OpenQuestion {
  id: string;
  project_id: string;
  creator_id: string;
  is_archived: boolean;
  archived_at: string | null;
  archived_by: string | null;

  question: string;
  context: string;
  evidence: string;
  priority: OpenQuestionPriority;
  status: OpenQuestionStatus;
  owner_id: string | null;
  due_date: string | null;
  is_locked: boolean;

  created_at: string;
  updated_at: string;
}

/** The editable content fields shared by create (`OpenQuestionCreate`) and
 * full replace (`OpenQuestionUpdate`) — `owner_id` is deliberately **not**
 * included, the same exclusion `PainPointFieldValues` makes and for the same
 * reason (§9.4 places "Assign" on the manager tier, not the create/edit
 * content form); `OpenQuestionDetailPage.tsx`'s own dedicated
 * `AssigneePicker` assigns it directly instead. */
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
