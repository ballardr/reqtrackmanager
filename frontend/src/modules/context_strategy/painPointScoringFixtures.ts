/**
 * Module: modules/context_strategy/painPointScoringFixtures
 *
 * Storybook-only fixture builders for Pain Point scoring responses, shaped like the backend's `PainPointScoresOut`/`PainPointScoringListOut`
 * for the shared `buildScoringScheme` levels (ids `sev-*`, `freq-*`,
 * `conf-*`). Kept beside the stories rather than in the global
 * `testing/storybook-helpers` so core test helpers never import a module's
 * types.
 */
import type { ScoringScheme } from "../../api/scoring";
import { buildScoringScheme } from "../../testing/storybook-helpers";
import type { PainPointScoreEntry, PainPointScores, PainPointScoringSummary, PainPointScoreValue } from "./types";

/** The Pain Point scheme with a criterion scored for the whole Pain Point (Job size, levels `size-*`) beside the per-persona ones. */
export function buildPainPointScheme(overrides: Partial<ScoringScheme> = {}): ScoringScheme {
  const base = buildScoringScheme();
  return {
    ...base,
    axes: [
      ...base.axes,
      { key: "job_size", label: "Job size", description: "How large the work is.", per_target: false, levels: [
        { id: "size-1", name: "Small", description: null, weight: 1 },
        { id: "size-2", name: "Large", description: null, weight: 5 },
      ] },
    ],
    allow_custom_criteria: true, side_by_side_models: true, enabled_model_keys: ["sxfxc", "sxf"],
    ...overrides,
  };
}

/** A computed score in the "High" band by default. */
export function scoreValue(overrides: Partial<PainPointScoreValue> = {}): PainPointScoreValue {
  return { raw: 12, normalised: 0.6, band_label: "High", band_tone: "warning", ...overrides };
}

/** One score row (an active persona by default). */
export function scoreEntry(overrides: Partial<PainPointScoreEntry> = {}): PainPointScoreEntry {
  return {
    target_id: "persona-1", target_type: "persona", label: "Field Technician", weight: 3, status: "active",
    levels: { severity: "sev-4", frequency: "freq-4" }, effective_levels: { severity: "sev-4", frequency: "freq-4" },
    score: scoreValue(), is_blocker: false, ...overrides,
  };
}

/** A Pain Point's roll-up summary. */
export function scoringSummary(overrides: Partial<PainPointScoringSummary> = {}): PainPointScoringSummary {
  return {
    pain_point_id: "pain-point-1", scope: "none", score: null, counted: 0, is_blocker: false, blocker_labels: [],
    personas_degraded: false, entries: [], ...overrides,
  };
}

/** The single-Pain-Point scoring response; two personas are available by default. */
export function painPointScores(overrides: Partial<PainPointScores> = {}): PainPointScores {
  return {
    ...scoringSummary(), model_key: "sxfxc", model_source: "system", rollup: "weighted_average",
    available_targets: [
      { id: "persona-1", label: "Field Technician", weight: 3, is_active: true },
      { id: "persona-2", label: "Back-office Planner", weight: 1, is_active: true },
    ],
    ...overrides,
  };
}
