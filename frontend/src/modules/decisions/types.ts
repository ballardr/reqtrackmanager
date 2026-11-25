/**
 * Module: modules/decisions/types
 *
 * The Decision Management module's TypeScript shapes and enum label and tone maps, mirroring
 * `backend/app/modules/decisions/schemas.py` and `enums.py` field for field. They live in the module's directory, not
 * `frontend/src/api/types.ts`, because a module's enums and label maps are its own display concern (as the backend's
 * `modules.compliance.labels` is apart from `app.services.labels`).
 *
 * `DecisionStatus` is not a customisable terminology key (`ProjectAdminPage.tsx`'s `TERMINOLOGY_KEYS`), so its labels
 * are plain string literals, not routed through `useStrings()` / `i18n/strings.ts`, as in `modules/compliance/module.ts`.
 */

import type { Principal, PrincipalRef } from "../../api/types";
import type { ProjectScopedRow } from "../../api/projectScope";

// --- Decision lifecycle ------------------------------------------------------

export type DecisionStatus = "draft" | "proposed" | "under_review" | "approved" | "rejected" | "superseded";

export const DECISION_STATUS_LABEL: Record<DecisionStatus, string> = {
  draft: "Draft",
  proposed: "Proposed",
  under_review: "Under review",
  approved: "Approved",
  rejected: "Rejected",
  superseded: "Superseded",
};

/** What each status means, the tooltip of its step in the lifecycle track. */
export const DECISION_STATUS_DESCRIPTION: Record<DecisionStatus, string> = {
  draft: "Being written; the Decision can be edited directly.",
  proposed: "Put forward for consideration and not yet under review.",
  under_review: "Being reviewed by the decision maker, who approves or rejects it.",
  approved: "Formally approved. The content is locked.",
  rejected: "Declined by the decision maker. The reason is recorded in the comment.",
  superseded: "Replaced by a later Decision. The content is locked.",
};

/** Decisions still to be made (not yet approved, rejected or superseded); the Decisions list opens on these. */
export const DECISION_OPEN_STATUSES: readonly DecisionStatus[] = ["draft", "proposed", "under_review"];

// Tone convention as `CHANGE_REQUEST_STATUS_TONE` (frontend/src/api/types.ts): a Decision's lifecycle has the same
// "propose -> review -> approve/reject" shape, so muted = not yet actionable or no longer current, info = awaiting a
// decision, accent = a positive terminal outcome, danger = a negative one.
export const DECISION_STATUS_TONE: Record<DecisionStatus, import("../../api/types").BadgeTone> = {
  draft: "muted",
  proposed: "info",
  under_review: "info",
  approved: "accent",
  rejected: "danger",
  superseded: "muted",
};

// --- Relationship kinds -------------------------------------------------------

export type DecisionRequirementLinkKind = "implements" | "affects";

export const DECISION_REQUIREMENT_LINK_KIND_LABEL: Record<DecisionRequirementLinkKind, string> = {
  implements: "Implements",
  affects: "Affects",
};

export type DecisionDecisionLinkKind = "depends_on" | "conflicts_with";

export const DECISION_DECISION_LINK_KIND_LABEL: Record<DecisionDecisionLinkKind, string> = {
  depends_on: "Depends on",
  conflicts_with: "Conflicts with",
};

// --- Decision Types (project-scoped) ------------------------------------------

export interface DecisionTypeDefinition {
  id: string;
  project_id: string;
  name: string;
  sort_order: number;
}

// --- Decision Templates (org-scoped) ------------------------------------------

export interface DecisionTemplate {
  id: string;
  organization_id: string;
  name: string;
  description: string | null;
  context_prompt: string | null;
  options_considered_prompt: string | null;
  chosen_option_prompt: string | null;
  rationale_prompt: string | null;
  consequences_prompt: string | null;
  assumptions_prompt: string | null;
  constraints_prompt: string | null;
  sort_order: number;
}

export type DecisionTemplateFieldValues = Omit<DecisionTemplate, "id" | "organization_id" | "sort_order">;

// --- Decisions -----------------------------------------------------------------

export interface Decision extends ProjectScopedRow {
  id: string;
  project_id: string;
  unique_code: string;
  title: string;
  decision_statement: string;
  decision_type_id: string;
  status: DecisionStatus;
  decision_date: string | null;
  /** Who made (or will make) the call: a user or a group; null while unassigned. */
  decision_maker: Principal | null;
  /** Who maintains the record: a user, an organisation group or a project group. */
  owner: Principal;
  context: string | null;
  options_considered: string | null;
  chosen_option: string | null;
  rationale: string | null;
  consequences: string | null;
  assumptions: string | null;
  constraints: string | null;
  /** The decision written out in full, as Markdown (tables and diagrams allowed). */
  document: string | null;
  creator_id: string;
  is_archived: boolean;
  archived_at: string | null;
  archived_by: string | null;
  is_locked: boolean;
  created_at: string;
  updated_at: string;
}

/** The editable content fields shared by create (`DecisionCreate`) and full replace (`DecisionUpdate`). `owner` is required on update (the backend defaults it to the creator only on create) and `decision_type_id` is a plain id string. */
export interface DecisionFieldValues {
  title: string;
  decision_statement: string;
  decision_type_id: string;
  decision_date: string | null;
  decision_maker: PrincipalRef | null;
  owner: PrincipalRef | null;
  context: string | null;
  options_considered: string | null;
  chosen_option: string | null;
  rationale: string | null;
  consequences: string | null;
  assumptions: string | null;
  constraints: string | null;
  document: string | null;
}

// --- Comments (no reaction mechanism — see DecisionCommentOut's own docstring) -

export interface DecisionComment {
  id: string;
  decision_id: string;
  author_id: string;
  author_display_name: string;
  body: string;
  created_at: string;
  edited_at: string | null;
  attachments: import("../../api/types").FileAsset[];
}

// --- Relationships ---------------------------------------------------------

export interface DecisionLink {
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
