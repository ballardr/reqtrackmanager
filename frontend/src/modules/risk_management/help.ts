/**
 * Module: risk_management/help
 *
 * The `(?)` field help for this module's own fields (docs/ux-style-guide.md, "Pattern: field help").
 * It lives in the module, not in the core string table, so a module's copy never needs a core edit.
 * One or two sentences per field: what it is, what it affects, a typical value.
 */

/** Help text for the Risk Management module's form fields, passed as `help` to the shared field components. */
export const RISK_HELP = {
  riskInherent: "The rating before any treatment: how likely the risk is and how serious the consequences would be with no controls in place.",
  riskResidual: "The rating that remains once the effective treatments are taken into account.",
  riskTreatmentSummary: "Whether at least one effective treatment is recorded against this risk.",
  riskTreatmentStrategy: "How the risk will be handled: mitigate reduces it, transfer shifts it to another party, avoid removes its cause, accept lives with it.",
} as const;
