/**
 * Module: modules/architecture/validationIssues
 *
 * The wording and counts of a state machine diagram's validation issues, shared by the toolbar's Validation button and its
 * tests. Pure functions of the issue list the server returns; nothing here works an issue out.
 */
import type { StateMachineValidationIssue } from "./types";

/** The button's visible text and the start of its accessible name. */
export const VALIDATION_LABEL = "Validation";

/** @returns How many of `issues` have each severity. */
export function countIssues(issues: readonly StateMachineValidationIssue[]): { errors: number; warnings: number } {
  const errors = issues.filter((i) => i.severity === "error").length;
  return { errors, warnings: issues.length - errors };
}

/** @returns "1 error", "2 warnings" and so on, with the singular where it belongs. */
export function plural(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? "" : "s"}`;
}

/** @returns The button's accessible name: the visible word, then what the checks found. */
export function validationName(errors: number, warnings: number): string {
  if (errors === 0 && warnings === 0) return `${VALIDATION_LABEL}: no issues`;
  return `${VALIDATION_LABEL}: ${[errors > 0 && plural(errors, "error"), warnings > 0 && plural(warnings, "warning")].filter(Boolean).join(" and ")}`;
}
