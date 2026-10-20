/**
 * Module: decisions/help
 *
 * The `(?)` field help for this module's own fields (docs/ux-style-guide.md, "Pattern: field help").
 * It lives in the module, not in the core string table, so a module's copy never needs a core edit.
 * One or two sentences per field: what it is, what it affects, a typical value.
 */

/** Help text for the Decision Management module's form fields, passed as `help` to the shared field components. */
export const DECISIONS_HELP = {
  decisionTemplate: "Pre-fills the form from a decision template defined for this project. You can still edit everything.",
} as const;
