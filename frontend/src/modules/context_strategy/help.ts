/**
 * Module: context_strategy/help
 *
 * The `(?)` field help for this module's own fields (docs/ux-style-guide.md, "Pattern: field help").
 * It lives in the module, not in the core string table, so a module's copy never needs a core edit.
 * One or two sentences per field: what it is, what it affects, a typical value.
 */

/** Help text for the Context & Strategy module's form fields, passed as `help` to the shared field components. */
export const CONTEXT_STRATEGY_HELP = {
  scoringPersonaOverride:
    "General holds one level for each criterion. Add a persona only where its levels differ from General: it overrides the criteria scored per persona (such as Severity) and takes General's level for the rest.\nCriteria scored for the whole Pain Point (such as Job size) are set under General only.\nWith personas added, the roll-up combines them; with none, General is the score.",
  painPointSubmission:
    "Any project member: everyone with access to the project can submit a Pain Point.\nPain Point Managers only: only Pain Point Managers and project managers can submit; other members raise an Enhancement Request where Product Feedback is enabled.\nEditing and triage are always for Pain Point Managers.",
  painPointSubmissionProject:
    "Inherit: use the parent project's setting, else the organisation default, else Pain Point Managers only.\nAny project member: everyone with access to the project can submit a Pain Point.\nPain Point Managers only: only Pain Point Managers and project managers can submit.\nEditing and triage are always for Pain Point Managers.",
} as const;
