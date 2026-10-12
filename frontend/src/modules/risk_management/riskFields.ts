/**
 * Module: modules/risk_management/riskFields
 *
 * Plain helpers for a risk's editable field set, shared by the create/edit
 * form and the detail page: the blank form values, the values of an existing
 * risk, and the minimal partial update between the two. An update sends only
 * the fields that changed, so an unchanged level on an Accepted risk (whose
 * levels, strategy and criteria are locked) never trips the backend's lock, and
 * an edit that changes nothing writes no version. Also the matrix cell lookup
 * (`cellOf`/`countPlottable`) shared by the grid and the register.
 */
import type { Risk, RiskFieldValues, RiskUpdateValues } from "./types";

/** The form values for a new risk, owned by `ownerId`. */
export function blankRiskValues(ownerId: string | null): RiskFieldValues {
  return {
    title: "", statement: "", cause: "", risk_event: "", consequence: "",
    risk_type_id: null, treatment_strategy: null, acceptance_criteria: "",
    inherent_likelihood_level_id: null, inherent_consequence_level_id: null, inherent_detectability_level_id: null,
    residual_likelihood_level_id: null, residual_consequence_level_id: null, residual_detectability_level_id: null,
    owner_id: ownerId, review_date: null,
  };
}

/** The editable values of `risk`. */
export function valuesFromRisk(risk: Risk): RiskFieldValues {
  return {
    title: risk.title, statement: risk.statement, cause: risk.cause, risk_event: risk.risk_event,
    consequence: risk.consequence, risk_type_id: risk.risk_type_id, treatment_strategy: risk.treatment_strategy,
    acceptance_criteria: risk.acceptance_criteria,
    inherent_likelihood_level_id: risk.inherent_likelihood_level_id,
    inherent_consequence_level_id: risk.inherent_consequence_level_id,
    inherent_detectability_level_id: risk.inherent_detectability_level_id,
    residual_likelihood_level_id: risk.residual_likelihood_level_id,
    residual_consequence_level_id: risk.residual_consequence_level_id,
    residual_detectability_level_id: risk.residual_detectability_level_id,
    owner_id: risk.owner_id, review_date: risk.review_date,
  };
}

/**
 * @param before The risk's current values.
 * @param after The edited values.
 * @returns Only the keys whose value differs (empty when nothing changed).
 */
export function diffRiskFields(before: RiskFieldValues, after: RiskFieldValues): RiskUpdateValues {
  const changed: Record<string, unknown> = {};
  for (const key of Object.keys(after) as (keyof RiskFieldValues)[]) {
    if (before[key] !== after[key]) changed[key] = after[key];
  }
  return changed as RiskUpdateValues;
}

export type RiskMatrixBasis = "inherent" | "residual";

/** What `RiskMatrix` plots: one rating, or both of each risk (a single risk's detail view). */
export type RiskMatrixPlot = RiskMatrixBasis | "both";

/** The risk's likelihood and consequence level ids on `basis`, or null if either is unset. */
export function cellOf(risk: Risk, basis: RiskMatrixBasis): { likelihood: string; consequence: string } | null {
  const likelihood = basis === "inherent" ? risk.inherent_likelihood_level_id : risk.residual_likelihood_level_id;
  const consequence = basis === "inherent" ? risk.inherent_consequence_level_id : risk.residual_consequence_level_id;
  return likelihood && consequence ? { likelihood, consequence } : null;
}

/** How many of `risks` have a cell on `basis` (the ones `RiskMatrix` plots). */
export function countPlottable(risks: Risk[], basis: RiskMatrixBasis): number {
  return risks.filter((r) => cellOf(r, basis) !== null).length;
}
