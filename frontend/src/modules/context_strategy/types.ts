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
 * Only Strategy's own shapes are here (Phase 7.1's scope) — Future State/
 * Pain Point/Guiding Principle/Open Question's shapes are added by their
 * own Phase 7.2-7.5 sub-phases, into this same file, mirroring how
 * `context_strategy/schemas.py`/`enums.py` themselves grow one artefact's
 * worth of symbols per backend phase rather than being split per artefact.
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
