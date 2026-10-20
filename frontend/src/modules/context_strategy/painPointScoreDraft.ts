/**
 * Module: modules/context_strategy/painPointScoreDraft
 *
 * The editable score draft shared by `PainPointScoringPanel` (an existing Pain Point) and
 * `PainPointFormModal` (a new one) through `PainPointScoreFields`: the row shape, the "all
 * personas" vs "each persona" mode, and the conversion to the API payload. Kept apart from the
 * component so the component file exports only a component.
 */
import type { PainPointScoreEntry, PainPointScoreInput } from "./types";

export const SCORE_AXIS_KEYS = ["severity", "frequency", "confidence"] as const;
export type ScoreAxisKey = (typeof SCORE_AXIS_KEYS)[number];
export type ScoreRowDraft = Record<ScoreAxisKey, string | null>;
/** Draft rows keyed `all` or by persona id. */
export type ScoreDraft = Record<string, ScoreRowDraft>;
export type ScoreMode = "all" | "persona";

export const ALL_PERSONAS_KEY = "all";
export const EMPTY_SCORE_ROW: ScoreRowDraft = { severity: null, frequency: null, confidence: null };

export const SCORE_MODE_OPTIONS = [
  { value: "all", label: "All personas together" },
  { value: "persona", label: "Each persona separately" },
];

/** One row of the score grid: the all-personas row, or one persona. */
export interface ScoreRow {
  key: string;
  label: string;
  note: string;
  retired: boolean;
  unavailable: boolean;
}

/** Builds the editable draft from saved rows. */
export function draftFromEntries(entries: PainPointScoreEntry[]): ScoreDraft {
  return Object.fromEntries(entries.map((e) => [
    e.target_id ?? ALL_PERSONAS_KEY,
    { severity: e.severity_level_id, frequency: e.frequency_level_id, confidence: e.confidence_level_id },
  ]));
}

/** The rows the grid shows: one all-personas row, or the persona rows. */
export function visibleScoreRows(mode: ScoreMode, personaRows: ScoreRow[]): ScoreRow[] {
  return mode === "all"
    ? [{ key: ALL_PERSONAS_KEY, label: "All personas", note: "", retired: false, unavailable: false }]
    : personaRows;
}

/** The API payload for the draft rows that are visible in the current mode. */
export function scoreInputsFromDraft(draft: ScoreDraft, rows: ScoreRow[]): PainPointScoreInput[] {
  const visible = new Set(rows.map((r) => r.key));
  return Object.entries(draft)
    .filter(([key]) => visible.has(key))
    .map(([key, row]) => ({
      target_id: key === ALL_PERSONAS_KEY ? null : key,
      severity_level_id: row.severity, frequency_level_id: row.frequency, confidence_level_id: row.confidence,
    }));
}
