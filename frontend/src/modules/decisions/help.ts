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
  decisionType: "The kind of decision, chosen from the types defined for the project.",
  decisionDate: "The date the decision was taken.",
  decisionMaker: "The person or group with the authority to take this decision. A group can be named, so the decision stays attributed when its members change.",
  decisionOwner: "The person or group accountable for the decision record and for acting on it.",
} as const;
