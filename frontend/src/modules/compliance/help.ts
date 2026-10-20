/**
 * Module: compliance/help
 *
 * The `(?)` field help for this module's own fields (docs/ux-style-guide.md, "Pattern: field help").
 * It lives in the module, not in the core string table, so a module's copy never needs a core edit.
 * One or two sentences per field: what it is, what it affects, a typical value.
 */

/** Help text for the Compliance module's form fields, passed as `help` to the shared field components. */
export const COMPLIANCE_HELP = {
  complianceRequirementReference: "The identifier the standard itself uses for this requirement, such as a clause number (for example A.5.1).",
  complianceStandardReference: "The standard's published identifier, for example ISO/IEC 27001.",
  complianceMandatory: "Marks the action as required rather than optional for meeting the requirement.",
  complianceEffectiveDate: "The date this version of the standard comes into force.",
  complianceCloneFrom: "Copies the requirements of an existing version into the new one, so only the differences need editing.",
  complianceStatus: "Where the project stands against this requirement. A justification is required when you change it.",
  complianceApplicability: "Whether this requirement applies to the project at all. Marking it not applicable needs a reason.",
  complianceMappingRelationship: "How this requirement relates to the target one, for example whether the two are equivalent or only partly overlap.",
  complianceReviewRecurrence: "Repeat interval in days. Leave it blank if the review does not recur.",
} as const;
