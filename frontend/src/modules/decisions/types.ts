/**
 * Module: modules/decisions/types
 *
 * The Decision Management module's own TypeScript shapes and enum label/
 * tone maps — mirrors `backend/app/modules/decisions/schemas.py` and
 * `enums.py` field-for-field. Lives in this module's own directory, not
 * `frontend/src/api/types.ts`, per that file's own note that a module's
 * enums/label maps are that module's own display concern (mirroring the
 * backend's identical `modules.compliance.labels` split from
 * `app.services.labels`) — see docs/plans/module-04-decision-management-
 * plan.md Phase 5.
 *
 * `DecisionStatus` is not one of this codebase's customisable terminology
 * keys (`ProjectAdminPage.tsx`'s `TERMINOLOGY_KEYS`), so these labels are
 * plain string literals rather than routed through `useStrings()`/
 * `i18n/strings.ts` — the same "no `{term}` tokens, so a plain literal is
 * fine" reasoning `modules/compliance/module.ts`'s own docstring gives, and
 * the convention every other Compliance module component
 * (`ActionTypesPanel.tsx` etc.) already follows for its own domain text.
 */

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

// Same tone convention as `CHANGE_REQUEST_STATUS_TONE` (frontend/src/api/
// types.ts) — a Decision's lifecycle is structurally the same "propose ->
// review -> approve/reject" shape as a Change Request, so it maps the same
// way: muted = not yet actionable/no-longer-current, info = awaiting a
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

export interface Decision {
  id: string;
  project_id: string;
  unique_code: string;
  title: string;
  decision_statement: string;
  decision_type_id: string;
  status: DecisionStatus;
  decision_date: string | null;
  decision_maker_id: string | null;
  owner_id: string;
  context: string | null;
  options_considered: string | null;
  chosen_option: string | null;
  rationale: string | null;
  consequences: string | null;
  assumptions: string | null;
  constraints: string | null;
  creator_id: string;
  is_archived: boolean;
  archived_at: string | null;
  archived_by: string | null;
  is_locked: boolean;
  created_at: string;
  updated_at: string;
}

/** The editable content fields shared by create (`DecisionCreate`) and full
 * replace (`DecisionUpdate`) — `owner_id` is required on update (the
 * backend defaults it to the creator only on create) and `decision_type_id`
 * is a plain id string here (not `UUID`, this being the frontend). */
export interface DecisionFieldValues {
  title: string;
  decision_statement: string;
  decision_type_id: string;
  decision_date: string | null;
  decision_maker_id: string | null;
  owner_id: string | null;
  context: string | null;
  options_considered: string | null;
  chosen_option: string | null;
  rationale: string | null;
  consequences: string | null;
  assumptions: string | null;
  constraints: string | null;
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
