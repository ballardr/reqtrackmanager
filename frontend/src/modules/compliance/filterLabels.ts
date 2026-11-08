/**
 * Module: compliance/filterLabels
 *
 * The filter-panel captions the Compliance lists share, so a caption is spelled once and the
 * project, organisation and outstanding-items panels read the same (docs/ux-style-guide.md,
 * "one term for one thing"). The module's own vocabulary lives here, not in the core string
 * table, so a module's copy never needs a core edit.
 */

/** Captions for the Standard, version and sub-section filters of the Compliance list panels. */
export const COMPLIANCE_FILTER_LABEL = {
  standard: "Standard",
  standardVersion: "Standard version",
  subSection: "Sub-section",
} as const;
