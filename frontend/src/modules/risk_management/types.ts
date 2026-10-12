/**
 * Module: modules/risk_management/types
 *
 * Frontend vocabulary for the Risk Management module (docs/plans/module-03-
 * risk-management-plan.md): the wire values of the module's enums with their
 * display label and badge-tone maps, and the response/request shapes of
 * `backend/app/modules/risk_management/schemas.py`. Mirrors that package's
 * `enums.py`/`labels.py`/`schemas.py` by hand; any place that shows an enum
 * value goes through its label map, never the raw string.
 */
import type { BadgeTone, FileAsset } from "../../api/types";

export type RiskStatus =
  | "identified"
  | "assessed"
  | "treatment_planned"
  | "treatment_in_progress"
  | "mitigated"
  | "accepted"
  | "transferred"
  | "avoided"
  | "realised"
  | "rejected"
  | "closed";

export const RISK_STATUS_LABEL: Record<RiskStatus, string> = {
  identified: "Identified",
  assessed: "Assessed",
  treatment_planned: "Treatment planned",
  treatment_in_progress: "Treatment in progress",
  mitigated: "Mitigated",
  accepted: "Accepted",
  transferred: "Transferred",
  avoided: "Avoided",
  realised: "Realised",
  rejected: "Rejected",
  closed: "Closed",
};

export type TreatmentStrategy = "mitigate" | "transfer" | "avoid" | "accept";

export const TREATMENT_STRATEGY_LABEL: Record<TreatmentStrategy, string> = {
  mitigate: "Mitigate",
  transfer: "Transfer",
  avoid: "Avoid",
  accept: "Accept",
};

/** Tone of a status badge: working states are informational, the favourable
 * outcomes green, `realised` (the risk happened) red, the rest muted. */
export const RISK_STATUS_TONE: Record<RiskStatus, BadgeTone> = {
  identified: "muted",
  assessed: "info",
  treatment_planned: "info",
  treatment_in_progress: "info",
  mitigated: "accent",
  accepted: "warning",
  transferred: "accent",
  avoided: "accent",
  realised: "danger",
  rejected: "muted",
  closed: "muted",
};

/** The backend scoring-scheme key and its two models (`scoring.py`). */
export const RISK_SCORING_SCHEME = "risk";

/** Statuses at which a risk is still being worked and so is shown by default in the register's "open" view. */
export const RISK_OPEN_STATUSES: RiskStatus[] = [
  "identified", "assessed", "treatment_planned", "treatment_in_progress", "mitigated", "accepted",
];

// --- Treatment assessment (Phase 3) ------------------------------------------

export type TreatmentAssessmentStatus = "proposed" | "effective" | "ineffective" | "needs_reassessment";

export const TREATMENT_ASSESSMENT_STATUS_LABEL: Record<TreatmentAssessmentStatus, string> = {
  proposed: "Proposed",
  effective: "Effective",
  ineffective: "Ineffective",
  needs_reassessment: "Needs reassessment",
};

export const TREATMENT_ASSESSMENT_STATUS_TONE: Record<TreatmentAssessmentStatus, BadgeTone> = {
  proposed: "muted",
  effective: "accent",
  ineffective: "danger",
  needs_reassessment: "warning",
};

// --- Reviews (Phase 4) -------------------------------------------------------

export type RiskReviewOutcome = "confirmed" | "reassessed";

export const RISK_REVIEW_OUTCOME_LABEL: Record<RiskReviewOutcome, string> = {
  confirmed: "Confirmed",
  reassessed: "Reassessed",
};

export const RISK_REVIEW_OUTCOME_TONE: Record<RiskReviewOutcome, BadgeTone> = {
  confirmed: "accent",
  reassessed: "info",
};

// --- Records -------------------------------------------------------------------

/** A derived (never stored) rating; `label`/`tone` are null when the model's bands do not cover the score. */
export interface RiskRating {
  scoring_model_key: string;
  raw: number;
  normalised: number;
  label: string | null;
  tone: BadgeTone | null;
}

/** The six scoring level ids a risk carries: inherent and residual Likelihood/Consequence/Detectability. */
export interface RiskLevelIds {
  inherent_likelihood_level_id: string | null;
  inherent_consequence_level_id: string | null;
  inherent_detectability_level_id: string | null;
  residual_likelihood_level_id: string | null;
  residual_consequence_level_id: string | null;
  residual_detectability_level_id: string | null;
}

export interface Risk extends RiskLevelIds {
  id: string;
  project_id: string;
  unique_code: string;
  creator_id: string;
  is_archived: boolean;
  archived_at: string | null;
  archived_by: string | null;
  title: string;
  statement: string;
  cause: string;
  risk_event: string;
  consequence: string;
  risk_type_id: string | null;
  risk_type_name: string | null;
  treatment_strategy: TreatmentStrategy | null;
  acceptance_criteria: string;
  inherent_rating: RiskRating | null;
  residual_rating: RiskRating | null;
  status: RiskStatus;
  allowed_next_statuses: RiskStatus[];
  owner_id: string | null;
  review_date: string | null;
  version_number: number;
  effective_treatment_count: number;
  is_effectively_treated: boolean;
  is_review_overdue: boolean;
  created_at: string;
  updated_at: string;
}

/** The editable fields of a risk (create payload; an update sends a subset). */
export interface RiskFieldValues extends RiskLevelIds {
  title: string;
  statement: string;
  cause: string;
  risk_event: string;
  consequence: string;
  risk_type_id: string | null;
  treatment_strategy: TreatmentStrategy | null;
  acceptance_criteria: string;
  owner_id: string | null;
  review_date: string | null;
}

/** An update payload: any subset of the fields, plus the note stored on the new version. */
export type RiskUpdateValues = Partial<RiskFieldValues> & { change_note?: string };

export interface RiskVersion extends RiskLevelIds {
  id: string;
  risk_id: string;
  version_number: number;
  valid_from: string;
  valid_to: string | null;
  title: string;
  statement: string;
  cause: string;
  risk_event: string;
  consequence: string;
  project_type_id: string | null;
  treatment_strategy: TreatmentStrategy | null;
  acceptance_criteria: string;
  status: RiskStatus;
  owner_id: string | null;
  review_date: string | null;
  change_note: string;
  created_by: string;
  created_at: string;
}

export interface RiskComment {
  id: string;
  risk_id: string;
  author_id: string;
  author_display_name: string;
  body: string;
  created_at: string;
  edited_at: string | null;
  attachments: FileAsset[];
}

/** One treatment link of a risk with its far end and verdict. */
export interface RiskTreatment {
  link_id: string;
  relationship: string;
  other_type: string;
  other_type_label: string;
  other_id: string;
  other_project_id: string | null;
  label: string;
  other_status: string | null;
  other_is_archived: boolean;
  status: TreatmentAssessmentStatus;
  rationale: string;
  reassessment_reason: string;
  assessed_by: string | null;
  assessed_at: string | null;
}

export interface RiskTreatmentList {
  items: RiskTreatment[];
  hidden_count: number;
  effective_count: number;
  needs_reassessment_count: number;
}

export interface RiskReview {
  id: string;
  risk_id: string;
  risk_version_number: number;
  reviewed_by: string;
  reviewed_at: string;
  outcome: RiskReviewOutcome;
  notes: string;
  risk_status: RiskStatus;
  inherent_rating_label: string | null;
  inherent_rating_score: number | null;
  residual_rating_label: string | null;
  residual_rating_score: number | null;
  effective_treatment_count: number;
  scheduled_for: string | null;
  next_review_date: string | null;
}

export interface RiskReviewValues {
  outcome: RiskReviewOutcome;
  notes: string;
  /** A future ISO date, or null for no further review. */
  next_review_date: string | null;
}
