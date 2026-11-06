/**
 * Module: modules/product_feedback/requestFixtures
 *
 * Shared Storybook fixtures for the Product Feedback components: the `enhancement_request` scoring scheme (Reach,
 * Impact, Confidence, Ease, Effort and the derived Demand, with ICE, RICE and a demand-based RICE), and builders for a
 * request, its demand, merge history and close-the-loop state. Imported by stories only.
 */
import type { ScoringScheme } from "../../api/scoring";
import type { OrgUser } from "../../api/types";
import type { CloseTheLoop, Demand, EnhancementRequest, ExternalRef, LoopRequester, Requester, RequestScore } from "./types";
import type { ListChoice } from "./useFeedbackLists";

export const PROJECT_ID = "project-1";
export const ORG_ID = "org-1";
export const REQUEST_ID = "request-1";

const named = (prefix: string, names: string[]) =>
  names.map((name, i) => ({ id: `${prefix}-${i + 1}`, name, description: null, weight: i + 1 }));

const BANDS = [
  { label: "Low", min_score: 0, tone: "muted" as const },
  { label: "Medium", min_score: 0.3, tone: "info" as const },
  { label: "High", min_score: 0.6, tone: "accent" as const },
];

/** Level ids are `<axis>-1..5` (`reach-1`, `impact-3`); Demand is derived with thresholds. */
export function buildRequestScheme(): ScoringScheme {
  const model = (key: string, label: string, axis_keys: string[], divisor_axis_keys: string[] = []) => ({
    key, label, axis_keys, divisor_axis_keys, bands: BANDS, bands_source: "system" as const,
    cell_ratings: [], cell_ratings_source: "none" as const,
  });
  return {
    key: "enhancement_request", label: "Enhancement request scoring", module_key: "product_feedback",
    axes: [
      { key: "reach", label: "Reach", description: null, levels: named("reach", ["Few", "Some", "Many", "Most", "Everyone"]) },
      { key: "impact", label: "Impact", description: null, levels: named("impact", ["Minimal", "Low", "Medium", "High", "Massive"]) },
      { key: "confidence", label: "Confidence", description: null, levels: named("conf", ["Guess", "Low", "Medium", "High", "Certain"]) },
      { key: "ease", label: "Ease", description: null, levels: named("ease", ["Very hard", "Hard", "Moderate", "Easy", "Trivial"]) },
      { key: "effort", label: "Effort", description: null, levels: named("effort", ["Trivial", "Small", "Medium", "Large", "Huge"]) },
      {
        key: "demand", label: "Demand", description: null, derived_source: "weighted_demand",
        levels: ["Negligible", "Some", "Strong"].map((name, i) => ({ id: `demand-${i + 1}`, name, description: null, weight: i + 1, threshold: i * 3 })),
      },
    ],
    models: [
      model("ice", "ICE", ["impact", "confidence", "ease"]),
      model("rice", "RICE", ["reach", "impact", "confidence"], ["effort"]),
      model("rice_demand", "RICE with demand", ["demand", "impact", "confidence"], ["effort"]),
    ],
    system_default_model_key: "ice", default_model_key: "ice", default_model_source: "system",
    enabled_model_keys: ["ice", "rice"], enabled_models_source: "system", allow_custom_criteria: true,
  };
}

export const ORG_USERS: OrgUser[] = [
  {
    user_id: "user-1", email: "alex@example.com", display_name: "Alex Morgan", is_active: true, is_archived: false,
    roles: ["member"], display_name_locked: false, last_login_at: null, is_2fa_enabled: false, module_roles: [], custom_roles: [],
  },
];

export function buildScore(overrides: Partial<RequestScore> = {}): RequestScore {
  return { scoring_model_key: "ice", raw: 48, normalised: 0.64, label: "High", tone: "accent", ...overrides };
}

/** A new, scored request with one requester and no Pain Point (so the warning shows). */
export function buildRequest(overrides: Partial<EnhancementRequest> = {}): EnhancementRequest {
  return {
    id: REQUEST_ID, scope: "project", organization_id: ORG_ID, project_id: PROJECT_ID, unique_code: "ENH-001",
    creator_id: "user-1", is_archived: false, archived_at: null, archived_by: null,
    title: "Export the list to Excel", description: "Support asked for a one-click export.",
    status: "new", allowed_next_statuses: ["under_review", "declined"], owner: null,
    external_refs: [], decline_reason: "",
    levels: { impact: "impact-4", confidence: "conf-4", ease: "ease-4", reach: "reach-3", effort: "effort-2" },
    derived_levels: { demand: "demand-2" },
    score: buildScore(), scoring_model_key: "ice",
    scores: { ice: buildScore(), rice: buildScore({ scoring_model_key: "rice", raw: 24, normalised: 0.4, label: "Medium", tone: "info" }) },
    version_number: 1, created_at: "2026-11-01T09:00:00Z", updated_at: "2026-11-01T09:00:00Z",
    pain_point_count: 0, requirement_count: 0, informed_count: 0, loop_open_count: 0,
    merged_into: null, merged_count: 0, requester_count: 1, weighted_demand: 1,
    ...overrides,
  };
}

/** A request with no level on Ease, so every model that needs it reads "Not scored". */
export function buildUnscoredRequest(overrides: Partial<EnhancementRequest> = {}): EnhancementRequest {
  return buildRequest({
    id: "request-2", unique_code: "ENH-002", title: "Dark mode", levels: { impact: "impact-2", confidence: "conf-2" },
    scores: { ice: null, rice: null }, score: null, requester_count: 0, weighted_demand: 0, pain_point_count: 1, ...overrides,
  });
}

export function buildRequester(overrides: Partial<Requester> = {}): Requester {
  return {
    artefact_type: "stakeholder", id: "stakeholder-1", label: "Priya Shah", weight: 3, weight_source: "influence", effective_weight: 3,
    from_merge: false, via_engagement: false, hidden: false, channel: null, link_id: "link-1", ...overrides,
  };
}

/** The external systems a project offers (ids as the system picker returns them). */
export const SYSTEM_CHOICES: ListChoice[] = [
  { value: "system-jira", label: "Jira" },
  { value: "system-servicenow", label: "ServiceNow" },
  { value: "system-other", label: "Other" },
];

/** The channels a project offers. */
export const CHANNEL_CHOICES: ListChoice[] = [
  { value: "channel-ticket", label: "Support ticket" },
  { value: "channel-call", label: "Call" },
  { value: "channel-email", label: "Email" },
];

export function buildExternalRef(overrides: Partial<ExternalRef> = {}): ExternalRef {
  return {
    id: "ref-1", request_id: REQUEST_ID, system_id: "system-jira", system_name: "Jira", key: "PROJ-123",
    url: "https://jira.example.com/browse/PROJ-123", role: "delivery", created_by: "user-1", created_at: "2026-11-02T09:00:00Z",
    ...overrides,
  };
}

export function buildDemand(overrides: Partial<Demand> = {}): Demand {
  return {
    request_id: REQUEST_ID, requester_count: 2, weighted_demand: 4.5, offset: 0, limit: 25,
    requesters: [buildRequester(), buildRequester({ artefact_type: "persona", id: "persona-1", label: "Power user", weight: null, weight_source: "project", effective_weight: 1.5, via_engagement: true, link_id: null })],
    engagements: [{ id: "engagement-1", label: "Customer workshop", hidden: false, link_id: "link-e1" }], merged_duplicates: [], ...overrides,
  };
}

export function buildLoopRequester(overrides: Partial<LoopRequester> = {}): LoopRequester {
  return {
    ...buildRequester(), informed: false, informed_at: null, informed_by: null, note: "", ...overrides,
  };
}

export function buildLoop(overrides: Partial<CloseTheLoop> = {}): CloseTheLoop {
  return {
    request_id: REQUEST_ID, status: "delivered", decline_reason: "", can_record: true,
    requesters: [buildLoopRequester(), buildLoopRequester({ id: "stakeholder-2", label: "Sam Rivera", informed: true, informed_at: "2026-11-03T10:00:00Z", note: "Emailed on release" })],
    informed_count: 1, open_count: 1, pain_points: [], realising_requirements: [], all_requirements_complete: null,
    suggest_delivered: false, ...overrides,
  };
}
