/**
 * Module: modules/product_feedback/types
 *
 * Frontend vocabulary for the Product Feedback module: the wire values of the module's enums with their display
 * label and badge-tone maps, and the response/request shapes of `backend/app/modules/product_feedback/schemas.py`.
 * Mirrors that package's `enums.py`/`labels.py`/`schemas.py` by hand; any place that shows an enum value goes
 * through its label map, never the raw string.
 */
import type { BadgeTone, Principal, PrincipalRef } from "../../api/types";
import type { ProjectScopedRow } from "../../api/projectScope";

export type RequestStatus = "new" | "under_review" | "accepted" | "delivered" | "declined" | "duplicate";

export const REQUEST_STATUS_LABEL: Record<RequestStatus, string> = {
  new: "New",
  under_review: "Under review",
  accepted: "Accepted",
  delivered: "Delivered",
  declined: "Declined",
  duplicate: "Duplicate",
};

/** Tone of a status badge: working states informational, the favourable outcomes green, the closed-out rest muted. */
export const REQUEST_STATUS_TONE: Record<RequestStatus, BadgeTone> = {
  new: "info",
  under_review: "info",
  accepted: "accent",
  delivered: "accent",
  declined: "muted",
  duplicate: "muted",
};

/** Statuses the list's "Open only" view keeps (mirrors `REQUEST_OPEN_STATUSES` in the backend `service.py`). */
export const REQUEST_OPEN_STATUSES: readonly RequestStatus[] = ["new", "under_review", "accepted"];

export type SubmissionPolicy = "members" | "triagers";

export const SUBMISSION_POLICY_LABEL: Record<SubmissionPolicy, string> = {
  members: "Any project member",
  triagers: "Triagers only",
};

export interface EnhancementRequest extends ProjectScopedRow {
  id: string;
  scope: "organization" | "project";
  organization_id: string | null;
  project_id: string | null;
  unique_code: string;
  creator_id: string;
  is_archived: boolean;
  archived_at: string | null;
  archived_by: string | null;
  title: string;
  description: string;
  status: RequestStatus;
  allowed_next_statuses: RequestStatus[];
  owner: Principal | null;
  external_ref_url: string | null;
  external_ref_key: string | null;
  decline_reason: string;
  /** Levels chosen on the organisation's `enhancement_request` scoring scheme, by axis key; an axis with no level is absent. */
  levels: Record<string, string>;
  /** The level each derived axis (Demand) resolves to where none is chosen, by axis key. */
  derived_levels: Record<string, string>;
  /** The primary score, derived under `scoring_model_key`; null until every manual axis that model needs has a level. */
  score: RequestScore | null;
  scoring_model_key: string;
  /** The score under each model scored (the enabled ones, or those asked for), by model key. */
  scores: Record<string, RequestScore | null>;
  version_number: number;
  created_at: string;
  updated_at: string;
  /** Pain Points the request addresses; 0 is flagged (a solution with no stated problem), never blocked. */
  pain_point_count: number;
  /** Requirements that realise the request. */
  requirement_count: number;
  /** Requesters recorded as told the outcome. */
  informed_count: number;
  /** Requesters still to be told; 0 unless the request is delivered or declined. */
  loop_open_count: number;
}

/** A request's derived score; `normalised` is the share of the model's best possible score. */
export interface RequestScore {
  scoring_model_key: string;
  raw: number;
  normalised: number;
  label: string | null;
  tone: string | null;
}

export interface EnhancementRequestCreate {
  title: string;
  description?: string;
  owner?: PrincipalRef | null;
  external_ref_url?: string | null;
  external_ref_key?: string | null;
  /** Level ids by axis key; null clears an axis on an update, and an axis not mentioned is kept. */
  levels?: Record<string, string | null>;
}

export interface FeedbackSettings {
  submission_policy: SubmissionPolicy;
}

/** A record linked to a request; `label` is null (and `hidden` true) when the viewer may not see it. */
export interface LinkedRecord {
  id: string;
  label: string | null;
  hidden: boolean;
}

export interface RealisingRequirement extends LinkedRecord {
  /** The requirement's completion overlay; null while hidden. */
  is_completed: boolean | null;
}

/** A requester of a request with whether they were told its outcome. */
export interface LoopRequester {
  artefact_type: string;
  id: string;
  label: string | null;
  weight: number | null;
  effective_weight: number;
  from_merge: boolean;
  via_engagement: boolean;
  hidden: boolean;
  informed: boolean;
  informed_at: string | null;
  informed_by: string | null;
  note: string;
}

/** `GET .../requests/{id}/close-the-loop`: what became of a request and who has been told. */
export interface CloseTheLoop {
  request_id: string;
  status: RequestStatus;
  decline_reason: string;
  /** True when the request is delivered or declined, so telling requesters can be recorded. */
  can_record: boolean;
  requesters: LoopRequester[];
  informed_count: number;
  open_count: number;
  pain_points: LinkedRecord[];
  realising_requirements: RealisingRequirement[];
  all_requirements_complete: boolean | null;
  /** Prompt only: an accepted request whose requirements are all complete may be marked delivered. */
  suggest_delivered: boolean;
}

/** `PUT .../requests/{id}/informed` body. */
export interface InformedUpdate {
  parties: { artefact_type: string; id: string }[];
  informed?: boolean;
  note?: string;
}
