/**
 * Module: modules/risk_management/riskFixtures
 *
 * Shared Storybook fixtures for the Risk Management components: a five-level
 * Likelihood × Consequence × Detectability `risk` scheme (with one pinned
 * non-monotonic cell, Rare × Catastrophic = High), and builders for a risk, a
 * treatment link and a review. Imported by stories only.
 */
import type { ScoringBand, ScoringScheme } from "../../api/scoring";
import type { OrgUser } from "../../api/types";
import type { Risk, RiskReview, RiskTreatment } from "./types";

export const PROJECT_ID = "project-1";
export const RISK_ID = "risk-1";

const BANDS: ScoringBand[] = [
  { label: "Low", min_score: 0, tone: "muted" },
  { label: "Medium", min_score: 0.2, tone: "info" },
  { label: "High", min_score: 0.4, tone: "warning" },
  { label: "Critical", min_score: 0.7, tone: "danger" },
];

const named = (prefix: string, names: string[]) =>
  names.map((name, i) => ({ id: `${prefix}-${i + 1}`, name, description: null, weight: i + 1 }));

/** The ids are `lik-1..5` (Rare..Almost certain), `con-1..5` (Insignificant..Catastrophic), `det-1..5`. */
export function buildRiskScheme(): ScoringScheme {
  return {
    key: "risk", label: "Risk scoring", module_key: "risk_management",
    axes: [
      { key: "likelihood", label: "Likelihood", description: null, levels: named("lik", ["Rare", "Unlikely", "Possible", "Likely", "Almost certain"]) },
      { key: "consequence", label: "Consequence", description: null, levels: named("con", ["Insignificant", "Minor", "Moderate", "Major", "Catastrophic"]) },
      { key: "detectability", label: "Detectability", description: null, levels: named("det", ["Detected immediately", "Detected early", "Detected before impact", "Detected late", "Undetectable"]) },
    ],
    models: [
      {
        key: "lxc", label: "Likelihood × Consequence", axis_keys: ["likelihood", "consequence"], bands: BANDS, bands_source: "system",
        cell_ratings: [{ first_level_id: "lik-1", second_level_id: "con-5", band_label: "High" }], cell_ratings_source: "org",
      },
      {
        key: "lxcxd", label: "Likelihood × Consequence × Detectability", axis_keys: ["likelihood", "consequence", "detectability"],
        bands: BANDS, bands_source: "system", cell_ratings: [], cell_ratings_source: "none",
      },
    ],
    system_default_model_key: "lxc", default_model_key: "lxc", default_model_source: "system",
  };
}

export const ORG_USERS: OrgUser[] = [
  {
    user_id: "user-1", email: "alex@example.com", display_name: "Alex Morgan", is_active: true, is_archived: false,
    roles: ["member"], display_name_locked: false, last_login_at: null, is_2fa_enabled: false, module_roles: [], custom_roles: [],
  },
  {
    user_id: "user-2", email: "sam@example.com", display_name: "Sam Rivera", is_active: true, is_archived: false,
    roles: ["member"], display_name_locked: false, last_login_at: null, is_2fa_enabled: false, module_roles: [], custom_roles: [],
  },
];

export const RISK_TYPES = [
  { id: "rt-1", name: "Safety", display_order: 0, is_enabled: true, source: "org" as const },
  { id: "rt-2", name: "Schedule", display_order: 1, is_enabled: true, source: "org" as const },
];

/** A risk: assessed, Likely × Major inherent (High), owned by Alex, no treatment, next review in 2099. */
export function buildRisk(overrides: Partial<Risk> = {}): Risk {
  return {
    id: RISK_ID, project_id: PROJECT_ID, unique_code: "RSK-001", creator_id: "user-1",
    is_archived: false, archived_at: null, archived_by: null,
    title: "Supplier firmware may be late", statement: "If the supplier slips, integration testing starts late.",
    cause: "Single-source supplier with no contractual date.", risk_event: "Firmware delivered after week 12.",
    consequence: "Integration window shrinks by a month.", risk_type_id: "rt-2", risk_type_name: "Schedule",
    treatment_strategy: "mitigate", acceptance_criteria: "",
    inherent_likelihood_level_id: "lik-4", inherent_consequence_level_id: "con-4", inherent_detectability_level_id: null,
    residual_likelihood_level_id: null, residual_consequence_level_id: null, residual_detectability_level_id: null,
    inherent_rating: { scoring_model_key: "lxc", raw: 16, normalised: 0.64, label: "High", tone: "warning" },
    residual_rating: null, status: "assessed", allowed_next_statuses: ["treatment_planned", "accepted", "rejected"],
    owner_id: "user-1", review_date: "2099-01-15", version_number: 2,
    effective_treatment_count: 0, is_effectively_treated: false, is_review_overdue: false,
    created_at: "2026-01-10T09:00:00Z", updated_at: "2026-01-12T09:00:00Z",
    ...overrides,
  };
}

export function buildTreatment(overrides: Partial<RiskTreatment> = {}): RiskTreatment {
  return {
    link_id: "link-1", relationship: "Mitigated by", other_type: "requirement", other_type_label: "Requirement",
    other_id: "req-1", other_project_id: PROJECT_ID, label: "REQ-001 Dual-source the firmware", other_status: "approved",
    other_is_archived: false, status: "proposed", rationale: "", reassessment_reason: "", assessed_by: null, assessed_at: null,
    ...overrides,
  };
}

export function buildReview(overrides: Partial<RiskReview> = {}): RiskReview {
  return {
    id: "review-1", risk_id: RISK_ID, risk_version_number: 2, reviewed_by: "user-1", reviewed_at: "2026-02-01T09:00:00Z",
    outcome: "confirmed", notes: "Supplier confirmed the date.", risk_status: "assessed",
    inherent_rating_label: "High", inherent_rating_score: 16, residual_rating_label: null, residual_rating_score: null,
    effective_treatment_count: 0, scheduled_for: "2026-02-01", next_review_date: "2099-01-15",
    ...overrides,
  };
}
