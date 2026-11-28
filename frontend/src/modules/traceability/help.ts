/**
 * Module: traceability/help
 *
 * The `(?)` field help for the Governance screens' fields (docs/ux-style-guide.md, "Pattern: field help"). It lives in
 * the module, not in the core string table, so a module's copy never needs a core edit. One or two sentences per field:
 * what it is, what it affects, a typical value. A field with several options lists every option on its own line.
 */

/** Help text for the Governance fields, passed as `help` to the shared field components. */
export const GOVERNANCE_HELP = {
  profileMode: [
    "How the profile reaches the projects it targets.",
    "Enforced: binds every targeted project; only a named exemption lifts it.",
    "Default: applies to every targeted project unless the project opts out.",
    "Opt-in: applies only to a targeted project that chooses it.",
  ].join("\n"),
  profileTargetKind: [
    "Which projects the profile reaches.",
    "All projects: every project of the organisation.",
    "Selected projects: only the projects listed, each optionally with its nested child projects.",
  ].join("\n"),
  profileTargetChildren: "Reaches the project's nested child projects as well, so a programme and its sub-projects share one policy.",
  profileExemptionProject: "The project that the Enforced profile no longer binds. Its own choices and the organisation's other profiles still apply.",
  profileExemptionReason: "Why the project is exempt, kept for audit and review. Typically the approval or the risk that was accepted.",
  profileChoice: "Opt out of a Default profile, or opt in to an Opt-in profile. An Enforced profile cannot be chosen away.",

  lifecycleRequired: "The optional states that every record of the type must pass through in the projects this profile applies to. A project cannot turn them off.",
  lifecycleSkip: "Forbids moving a record past intermediate steps in the projects this profile applies to.",
  stageWorkflow: "The organisation stage workflow that new stages of the projects this profile applies to start in. Existing stages are not moved.",
  stageWorkflowMode: [
    "How the required workflow binds a project.",
    "Start new stages in it: the project can still use its other workflows.",
    "Start new stages in it and allow only the named workflows: the project can use only the workflows its profiles name.",
  ].join("\n"),

  approvalRoles: "Roles that may also approve this record type. They are another way to be granted the approval right; they never replace the right the type already requires.",
  approvalProjectRoles: "Roles the project adds as approvers of this record type. Leave unset to follow the nearest ancestor project.",

  reviewInterval: "The longest gap, in days, between reviews of a record of this type. A review date set further ahead is brought back to this limit.",
  reviewLead: "How many days before a review is due the reminder is sent.",
  reviewOwner: "The user or group reminded when a record has no reviewer of its own.",

  baselineKinds: [
    "Which baselines the checks run before.",
    "Stage baseline: when a stage enters a locked phase.",
    "Manual baseline: when a person takes a baseline.",
  ].join("\n"),
  baselineApprovals: [
    "Whether the checks also run before a record is approved. A failing check refuses the approval.",
    "Off: approvals are not checked.",
    "Manual approvals only: when a person approves one record, including by approving a change request.",
    "Automated approvals only: when a stage is approved automatically at its review deadline.",
    "Manual and automated approvals: both.",
    "A stage approved at its review deadline is also checked whenever Stage baseline is selected.",
  ].join("\n"),
  baselineNotify: "Tells the project managers when a failing check stops the automatic approval of a stage at its review deadline.",
  baselineChecks: "The checks that must pass before a baseline. A failing check refuses the whole baseline and lists every record and check at fault.",
  baselineRequiredFields: "Fields that every record of the type must have filled before a baseline. Used by the Required fields check.",
  baselineFieldType: "The record type whose field is required.",
  baselineFieldKey: "The field the record must have filled. Custom fields appear for the project chosen above.",
  baselineFieldsProject: "The project whose fields are offered. A profile's fields are not checked against a project, because custom fields differ between projects.",

  healthMode: [
    "How governance health is produced.",
    "On demand: computed for each viewer when they open it; nothing is stored.",
    "Snapshot at an interval: a stored snapshot refreshed at the chosen interval.",
    "Snapshot on change: a stored snapshot recomputed on the first read after the project's records change.",
  ].join("\n"),
  healthInterval: "How often an interval snapshot is refreshed.",
  healthRunner: "The person the baseline checks of a snapshot run as. With none, the checks run only when someone presses Refresh now.",
} as const;

/** Help text for the traceability exception screens. */
export const EXCEPTION_HELP = {
  rule: "The traceability rule the record is excepted from.",
  record: "The one record the exception covers.",
  cover: [
    "Whether the record is excepted from the rule today.",
    "Covering: approved and in force.",
    "Not approved: requested, rejected, withdrawn or revoked.",
    "Expired: the expiry date has passed.",
    "Rule no longer applies: the rule was removed, hidden or switched off.",
    "Needs organisation approval: the organisation enforces the rule and the approval was not given at that level.",
  ].join("\n"),
  expiresOn: "The last day the exception covers. Without a date it covers until revoked.",
  reviewDate: "When the exception is next to be reviewed. It sends a reminder and does not end the cover.",
  requester: "The user or group asking for the exception. A requester never approves it.",
  approver: "A nominated approver, told of the request. Nomination gives no right to approve.",
  openOnly: "Only exceptions awaiting a decision or approved and not expired.",
};
