/**
 * Module: product_feedback/help
 *
 * The `(?)` field help for this module's own fields (docs/ux-style-guide.md, "Pattern: field help").
 * It lives in the module, not in the core string table, so a module's copy never needs a core edit.
 * One or two sentences per field: what it is, what it affects, a typical value.
 */

/** Help text for the Product Feedback module's form fields, passed as `help` to the shared field components. */
export const PRODUCT_FEEDBACK_HELP = {
  requestOwner: "Who is accountable for deciding what happens to this request: a person or a team. Usually whoever triages it.",
  referenceSystem: "The outside tool the item is in, chosen from your organisation's list (a project can add its own).",
  referenceKey: "The item's key in that tool, such as PROJ-123. Shown in the list; give a key, a link, or both.",
  referenceUrl: "A link to the item, so people can open it. Only web (http or https) links are accepted.",
  referenceRole: "“Came from” means the request was raised in that ticket; “Delivered in” means it is being built there.",
  requesterChannel: "How this person asked: a support ticket, a call, an email and so on. It shows where demand comes from.",
  requestDerivedLevel: "Worked out from how many people asked, weighted by their influence. Choose a level only to override it; clear it to go back to the worked-out one.",
  submissionPolicy: "Who may submit a request in this project. Triagers can always edit, merge and decide requests whichever you choose.",
  declineReason: "Why the request was declined. This is kept with the request and shown to anyone told the outcome.",
  mergeNote: "Why these are the same ask. Kept in the merge history so the merge can be understood, and undone, later.",
  informedNote: "How or by whom the requesters were told, for example 'Emailed by support on release day'. Nothing is sent from here.",
} as const;
