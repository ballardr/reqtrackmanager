/**
 * Module: modules/context_strategy/painPointScoreDraft
 *
 * The editable score draft shared by `PainPointScoringPanel` (an existing Pain Point) and
 * `PainPointFormModal` (a new one) through `PainPointScoreFields`: one draft row for the General
 * scores and one per persona that differs from them, and the conversion to the API payload. A row
 * maps a scoring axis key to a level id. Kept apart from the component so the component file
 * exports only a component.
 */
import type { ScoringAxis } from "../../api/scoring";
import type { PainPointScoreEntry, PainPointScoreInput } from "./types";

/** One draft row: the chosen level id by scoring axis key (`null` = not scored). */
export type ScoreRowDraft = Record<string, string | null>;
/** Draft rows keyed `general` or by persona id. */
export type ScoreDraft = Record<string, ScoreRowDraft>;

export const GENERAL_KEY = "general";

/** One persona the scores can name: on offer to add, or already holding a row. */
export interface ScoreRow {
  key: string;
  label: string;
  note: string;
  retired: boolean;
  unavailable: boolean;
}

/** Builds the editable draft from saved rows. */
export function draftFromEntries(entries: PainPointScoreEntry[]): ScoreDraft {
  return Object.fromEntries(entries.map((e) => [e.target_id ?? GENERAL_KEY, { ...e.levels }]));
}

/** The criteria a persona row may hold: those scored per persona. */
export function personaAxes(axes: ScoringAxis[]): ScoringAxis[] {
  return axes.filter((a) => a.per_target);
}

/** The persona keys that hold a row in the draft, in the order they were added. */
export function personaKeys(draft: ScoreDraft): string[] {
  return Object.keys(draft).filter((key) => key !== GENERAL_KEY);
}

/** The API payload for the draft: the General row, then each persona row, with unscored levels left out. */
export function scoreInputsFromDraft(draft: ScoreDraft): PainPointScoreInput[] {
  return Object.entries(draft).map(([key, row]) => ({
    target_id: key === GENERAL_KEY ? null : key,
    levels: Object.fromEntries(Object.entries(row).filter(([, level]) => level !== null)),
  }));
}
