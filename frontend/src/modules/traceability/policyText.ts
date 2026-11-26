/**
 * Module: modules/traceability/policyText
 *
 * Pure helpers shared by the review and baseline policy screens: the wording of where a setting comes from, the
 * conversion between a review policy row as the API returns it and as the form edits it, and the rules a form checks
 * before it offers Save.
 *
 * Responsibilities:
 * - Name a policy source (`project`, `parent_project` or a profile's name) in formal words.
 * - Convert `ReviewSettings` (a resolved principal) to `ReviewSettingsValues` (a principal reference) and back to text.
 * - State why review or baseline settings cannot be saved yet.
 *
 * Design decisions: kept apart from the components so each component file exports only components. The limits match
 * the backend schema (`ReviewSettingsIn`: interval 1 to 3650 days, lead 0 to 365 days).
 */
import type { BaselineSettings, ReviewSettings, ReviewSettingsValues } from "./types";

/** The longest review interval the API accepts, in days. */
export const REVIEW_INTERVAL_MAX_DAYS = 3650;
/** The longest reminder lead the API accepts, in days. */
export const REVIEW_LEAD_MAX_DAYS = 365;

/** Review settings with nothing set. */
export const EMPTY_REVIEW_VALUES: ReviewSettingsValues = { interval_days: null, lead_days: null, default_owner: null };

/** The baseline policy a project or profile that has set nothing starts its form from. */
export const DEFAULT_BASELINE_SETTINGS: BaselineSettings = {
  applies_to_stage: true, applies_to_manual: false, notify_managers: true, checks: [], required_fields: [],
};

/**
 * @param source A source as the API names it: a profile's name, `project`, `parent_project` or nothing.
 * @returns The words shown for it ("This project", "Parent project", the profile's name, or an empty string).
 */
export function sourceLabel(source: string | null | undefined): string {
  if (!source) return "";
  if (source === "project") return "This project";
  if (source === "parent_project") return "Parent project";
  return source;
}

/**
 * @param sources The sources that give one setting.
 * @returns The sources as one sentence fragment ("Profile A, This project"), or an empty string.
 */
export function sourcesLabel(sources: readonly string[]): string {
  return sources.map(sourceLabel).join(", ");
}

/**
 * @param settings A policy row as the API returns it, or `null` for none.
 * @returns The same settings as a form edits them (the default owner reduced to a reference).
 */
export function reviewValuesOf(settings: ReviewSettings | null): ReviewSettingsValues {
  if (!settings) return EMPTY_REVIEW_VALUES;
  const owner = settings.default_owner;
  return {
    interval_days: settings.interval_days,
    lead_days: settings.lead_days,
    default_owner: owner ? { type: owner.type, id: owner.id } : null,
  };
}

/**
 * @param values The review settings a form holds.
 * @returns Why they cannot be saved, or `null` when they can.
 */
export function reviewProblem(values: ReviewSettingsValues): string | null {
  const { interval_days: interval, lead_days: lead } = values;
  if (interval !== null && (!Number.isInteger(interval) || interval < 1 || interval > REVIEW_INTERVAL_MAX_DAYS)) {
    return `The review interval is a whole number of days from 1 to ${REVIEW_INTERVAL_MAX_DAYS}.`;
  }
  if (lead !== null && (!Number.isInteger(lead) || lead < 0 || lead > REVIEW_LEAD_MAX_DAYS)) {
    return `The reminder lead is a whole number of days from 0 to ${REVIEW_LEAD_MAX_DAYS}.`;
  }
  return null;
}

/**
 * @param text The text of a number input.
 * @returns The number it holds, or `null` when it is empty or not a number.
 */
export function numberOrNull(text: string): number | null {
  if (text.trim() === "") return null;
  const parsed = Number(text);
  return Number.isNaN(parsed) ? null : parsed;
}

/** The key suffix of the baseline check that uses a policy's required fields. */
const REQUIRED_FIELDS_CHECK_SUFFIX = ":required_fields";

/**
 * @param checks The namespaced keys of the checks a policy enables.
 * @returns Whether the Required fields check is among them.
 */
export function usesRequiredFields(checks: readonly string[]): boolean {
  return checks.some((key) => key.endsWith(REQUIRED_FIELDS_CHECK_SUFFIX));
}

/**
 * @param settings The baseline policy a form holds.
 * @returns Why it cannot be saved, or `null` when it can.
 */
export function baselineProblem(settings: BaselineSettings): string | null {
  if (!settings.applies_to_stage && !settings.applies_to_manual) return "Select at least one kind of baseline for the checks to run before.";
  return null;
}

/**
 * @param left A baseline policy.
 * @param right Another baseline policy.
 * @returns Whether both hold the same values, ignoring the order of checks and fields.
 */
export function sameBaseline(left: BaselineSettings, right: BaselineSettings): boolean {
  const fields = (s: BaselineSettings) => s.required_fields.map((f) => `${f.artefact_type}/${f.field_key}`).sort().join("|");
  return left.applies_to_stage === right.applies_to_stage
    && left.applies_to_manual === right.applies_to_manual
    && left.notify_managers === right.notify_managers
    && [...left.checks].sort().join("|") === [...right.checks].sort().join("|")
    && fields(left) === fields(right);
}
