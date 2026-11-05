/**
 * Module: modules/product_feedback/types
 *
 * Frontend vocabulary for the Product Feedback module: the wire values of the module's enums with their display
 * label and badge-tone maps, and the response/request shapes of `backend/app/modules/product_feedback/schemas.py`.
 * Mirrors that package's `enums.py`/`labels.py`/`schemas.py` by hand; any place that shows an enum value goes
 * through its label map, never the raw string.
 */
import type { BadgeTone, FileAsset, Principal, PrincipalRef } from "../../api/types";
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

/** What an external reference is: the ticket the request came from, or the one where it is built. */
export type ExternalRefRole = "origin" | "delivery";

export const EXTERNAL_REF_ROLE_LABEL: Record<ExternalRefRole, string> = {
  origin: "Came from",
  delivery: "Delivered in",
};

/** The order the role picker lists them in. */
export const EXTERNAL_REF_ROLES: readonly ExternalRefRole[] = ["delivery", "origin"];

/** A pointer from a request to an item in an outside tool (a Jira epic, a ServiceNow ticket). Not versioned with the request. */
export interface ExternalRef {
  id: string;
  request_id: string;
  /** An id the request's tier's system picker accepts. */
  system_id: string;
  system_name: string;
  key: string;
  url: string | null;
  role: ExternalRefRole;
  created_by: string;
  created_at: string;
}

/** The body that adds a reference, or one entry of a create payload's `references`. */
export interface ExternalRefInput {
  system_id: string;
  key?: string;
  url?: string | null;
  role?: ExternalRefRole;
}

/** The channel a requester asked through. */
export interface ChannelRef {
  id: string;
  name: string;
}

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
  /** The request's references to items in outside tools, oldest first. */
  external_refs: ExternalRef[];
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
  /** The canonical request this one was merged into (status `duplicate`), else null. */
  merged_into: RequestRef | null;
  /** Requests merged into this one. */
  merged_count: number;
  /** Distinct requesters, merged duplicates' included. */
  requester_count: number;
  /** Requesters weighted by influence or persona weight; shown beside the score, never mixed into it. */
  weighted_demand: number;
}

/** A request's derived score; `normalised` is the share of the model's best possible score. */
export interface RequestScore {
  scoring_model_key: string;
  raw: number;
  normalised: number;
  label: string | null;
  tone: string | null;
}

/** What levels still being chosen would score (the server derives it, nothing is saved). */
export interface ScorePreview {
  /** The score under each enabled model; null = not scored. */
  scores: Record<string, RequestScore | null>;
  /** The level each derived axis resolves to where none was chosen. */
  derived_levels: Record<string, string>;
  weighted_demand: number;
}

export interface EnhancementRequestCreate {
  title: string;
  description?: string;
  owner?: PrincipalRef | null;
  /** The request's first references, on create only: later changes use the reference endpoints. */
  references?: ExternalRefInput[];
  /** Level ids by axis key; null clears an axis on an update, and an axis not mentioned is kept. */
  levels?: Record<string, string | null>;
}

/** An update is a create payload plus the note recorded with the new version. */
export interface EnhancementRequestUpdate extends Partial<Omit<EnhancementRequestCreate, "references">> {
  change_note?: string;
}

/** `GET .../access`: what the viewer may do with this tier's requests. */
export interface FeedbackAccess {
  can_submit: boolean;
  can_triage: boolean;
}

export interface FeedbackSettings {
  submission_policy: SubmissionPolicy;
  /** The project's default order of a request page's sections; null is the built-in order. */
  request_page_sections: string[] | null;
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
  /** How they asked; null when none is recorded (an Engagement requester reads as an Engagement). */
  channel: ChannelRef | null;
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

/** A short reference to another request (a merge's canonical request, a merged duplicate). */
export interface RequestRef {
  id: string;
  unique_code: string;
  title: string;
}

/** One distinct party behind a request; `label` and `weight` are null (and `hidden` true) for a party the viewer may not see. */
export interface Requester {
  artefact_type: string;
  id: string;
  label: string | null;
  weight: number | null;
  effective_weight: number;
  from_merge: boolean;
  via_engagement: boolean;
  hidden: boolean;
  /** How they asked; null when none is recorded (an Engagement requester reads as an Engagement). */
  channel: ChannelRef | null;
  /** The request's own "Requested by" link to this party, which removes it; null when reached only through an
   * Engagement or a merged duplicate. */
  link_id: string | null;
}

/** An engagement the request was raised in; `label` is null while hidden. */
export interface DemandEngagement {
  id: string;
  label: string | null;
  hidden: boolean;
  /** The request's own "Requested by" link to it; null for one reached only through a merged duplicate. */
  link_id: string | null;
}

/** `GET .../requests/{id}/demand`: who asked, and the totals. `requesters` is one page (heaviest first) of
 * `requester_count`; the count and weight cover every requester. */
export interface Demand {
  request_id: string;
  requester_count: number;
  weighted_demand: number;
  offset: number;
  limit: number;
  requesters: Requester[];
  engagements: DemandEngagement[];
  merged_duplicates: RequestRef[];
}

/** One merge in a request's history, as the canonical request or as the duplicate. */
export interface RequestMerge {
  id: string;
  canonical: RequestRef;
  duplicate: RequestRef;
  prior_status: RequestStatus;
  merged_by: string;
  merged_at: string;
  /** Why the two are the same ask, as the person who merged wrote it (empty when none). */
  note: string;
  unmerged_by: string | null;
  unmerged_at: string | null;
  active: boolean;
}

/** One historical version of a request. */
export interface RequestVersion {
  id: string;
  request_id: string;
  version_number: number;
  valid_from: string;
  valid_to: string | null;
  title: string;
  description: string;
  status: RequestStatus;
  owner: Principal | null;
  decline_reason: string;
  levels: Record<string, string>;
  change_note: string;
  created_by: string;
  created_at: string;
}

export interface RequestComment {
  id: string;
  request_id: string;
  author_id: string;
  author_display_name: string;
  body: string;
  created_at: string;
  edited_at: string | null;
  attachments: FileAsset[];
}

/** A delivered or declined request with requesters still to be told (`GET .../close-the-loop`). */
export interface OpenLoop {
  request: RequestRef;
  status: RequestStatus;
  decline_reason: string;
  requester_count: number;
  open_count: number;
  uninformed: Requester[];
}

/** `PUT .../requests/{id}/requester-channel` body: how the given requesters asked (null clears it). */
export interface ChannelUpdate {
  parties: { artefact_type: string; id: string }[];
  channel_id: string | null;
}
