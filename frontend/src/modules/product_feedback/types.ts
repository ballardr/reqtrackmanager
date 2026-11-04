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
  version_number: number;
  created_at: string;
  updated_at: string;
}

export interface EnhancementRequestCreate {
  title: string;
  description?: string;
  owner?: PrincipalRef | null;
  external_ref_url?: string | null;
  external_ref_key?: string | null;
}

export interface FeedbackSettings {
  submission_policy: SubmissionPolicy;
}
