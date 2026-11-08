/**
 * Module: stakeholders/help
 *
 * The `(?)` field help for this module's own fields (docs/ux-style-guide.md, "Pattern: field help").
 * It lives in the module, not in the core string table, so a module's copy never needs a core edit.
 * One or two sentences per field: what it is, what it affects, a typical value.
 */

/** Help text for the Stakeholders & Personas module's form fields, passed as `help` to the shared field components. */
export const STAKEHOLDERS_HELP = {
  personaImportanceWeight: "How much this persona counts when scores are rolled up across personas. It must be greater than zero; leave it blank to weight every persona equally. A project can override it.",
  stakeholderCadence: "How often you plan to engage this stakeholder. When influence and interest are set, the form suggests a cadence for that position on the grid.",
  stakeholderInfluenceInterest: "Influence is how much the stakeholder can affect the work; interest is how much it affects them. Together they place them on the power and interest grid and suggest an engagement cadence.",
  recordVisibility: "Hiding removes the record from this project's lists and pickers without deleting it. A parent project can hide it for its children.",
  engagementParticipants: "The Stakeholders who took part. They are recorded with the engagement and can be changed later on its page; to add a whole group at once, use Audience groups there.",
  engagementParticipantsWithAnonymous: "The people who took part, recorded with the engagement and changeable later, from this form or its page. Choose Stakeholders from the list. Text typed that matches no Stakeholder can be added as an anonymous participant, a label such as “Participant 3” with no Stakeholder record; choose the Persona each one represents now or when editing. To add a whole group at once, use Audience groups on the Engagement's page.",
  engagementPurpose: "Why the engagement took place, for example a quarterly review or a discovery session.",
  engagementSummary: "A line or two on what was learned or decided; it appears in the engagement list.",
  engagementConsent: "Tick once the participants have agreed to being recorded here. The record keeps this as evidence of consent.",
  engagementRetainUntil: "The date after which the engagement should be reviewed for deletion. Nothing is deleted automatically; the engagement is flagged when this date is reached.",
  needDescription: "The need in the stakeholder's own words, before it becomes a requirement.",
  needRationale: "Why the need matters and where it came from, for example a session or document.",
  stakeholderAvailability: "What limits how often the stakeholder can engage, from their side rather than the project's, such as working hours or seasonal peaks.",
  engagementOutcomeKind: "Raised means this engagement produced the record; Answered means it answered one that already existed.",
  engagementChannel: "How the engagement took place, such as a meeting, a call or a survey.",
  stakeholderOrganisationGroup: "The employer or team the stakeholder belongs to, for reference.",
  stakeholderGroupParent: "The group this group sits inside, which forms a hierarchy of groups.",
} as const;
