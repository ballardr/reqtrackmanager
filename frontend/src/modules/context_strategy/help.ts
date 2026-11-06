/**
 * Module: context_strategy/help
 *
 * The `(?)` field help for this module's own fields (docs/ux-style-guide.md, "Pattern: field help").
 * It lives in the module, not in the core string table, so a module's copy never needs a core edit.
 * One or two sentences per field: what it is, what it affects, a typical value.
 */

/** Help text for the Context & Strategy module's form fields, passed as `help` to the shared field components. */
export const CONTEXT_STRATEGY_HELP = {
  scoringMode: "All personas together records one score for the pain point. Each persona separately records a score per persona, which are then combined by the persona roll-up.",
  painPointSubmission:
    "Any project member: everyone with access to the project can submit a Pain Point.\nPain Point Managers only: only Pain Point Managers and project managers can submit; other members raise an Enhancement Request where Product Feedback is enabled.\nEditing and triage are always for Pain Point Managers.",
  painPointSubmissionProject:
    "Inherit: use the parent project's setting, else the organisation default, else Pain Point Managers only.\nAny project member: everyone with access to the project can submit a Pain Point.\nPain Point Managers only: only Pain Point Managers and project managers can submit.\nEditing and triage are always for Pain Point Managers.",
} as const;
