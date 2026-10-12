/**
 * Module: modules/risk_management/types
 *
 * Frontend vocabulary for the Risk Management module (docs/plans/module-03-
 * risk-management-plan.md): the wire values of `RiskStatus` and
 * `TreatmentStrategy` with their display label maps. Mirrors
 * `backend/app/modules/risk_management/enums.py`/`labels.py` by hand; any
 * place that shows one of these values goes through the label map, never the
 * raw string.
 */

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
