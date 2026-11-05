/**
 * Module: modules/product_feedback/requestLevels
 *
 * Helpers for the scoring levels a request form edits: the draft is a map of axis key to chosen level id (or
 * null for "not set"), and the wire shape is the same map where, on an update, a null clears an axis the request
 * had a level on. Kept out of the form component so the create form, the edit form and the bulk grid agree.
 */
import type { ScoringAxis, ScoringScheme } from "../../api/scoring";

export type LevelDraft = Record<string, string | null>;

/** The axes the form offers, in the scheme's order: a derived axis (Demand) is overridable, never required. */
export function formAxes(scheme: ScoringScheme | null): ScoringAxis[] {
  return scheme?.axes ?? [];
}

/** True for an axis whose level is worked out from demand unless chosen by hand. */
export function isDerivedAxis(axis: ScoringAxis): boolean {
  return Boolean(axis.derived_source);
}

/** The draft a form starts from: the levels the request already has (none on a create). */
export function initialLevelDraft(levels: Record<string, string> | undefined): LevelDraft {
  return { ...(levels ?? {}) };
}

/**
 * The `levels` value to send.
 *
 * @param draft The edited draft.
 * @param previous The levels the request had before the edit (omit on a create).
 * @returns Each chosen level; on an update also a null for every axis that had a level and no longer does.
 */
export function levelsPayload(draft: LevelDraft, previous?: Record<string, string>): Record<string, string | null> {
  const out: Record<string, string | null> = {};
  for (const [axis, level] of Object.entries(draft)) if (level) out[axis] = level;
  for (const axis of Object.keys(previous ?? {})) if (!draft[axis]) out[axis] = null;
  return out;
}
