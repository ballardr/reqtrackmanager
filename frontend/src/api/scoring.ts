/**
 * Module: api/scoring
 *
 * Types and calls for the generic scoring-matrix API (Module 1 — Context &
 * Strategy — Phase 10). A module registers a scoring scheme (axes with
 * weighted levels, models, default bands) on the backend; these calls read
 * a scheme's effective configuration for an org or project and edit it.
 * Core code only ever addresses a scheme by its key — the module that owns
 * it passes that key into the shared components (`ScoringSchemeEditor`,
 * `ProjectScoringSettings`).
 *
 * Score maths mirror `backend/app/services/scoring.py`: a model's score is
 * the product of its axes' level weights; bands use the score normalised by
 * the model's maximum possible score. A two-axis model may also carry
 * explicit per-cell ratings (`ScoringCellRating`), which win over the
 * thresholds for their cell only.
 */
import { api } from "./client";
import type { BadgeTone } from "./types";

/** Where an effective value came from, most specific first. */
export type ScoringResolutionSource = "project" | "ancestor" | "org" | "system" | "none";

export const SCORING_SOURCE_LABEL: Record<ScoringResolutionSource, string> = {
  project: "Set on this project",
  ancestor: "Inherited from parent project",
  org: "Inherited from organisation",
  system: "Module default",
  none: "None defined",
};

/** Rating-band tones, labelled for the band editor's tone picker. */
export const SCORING_BAND_TONE_LABEL: Record<BadgeTone, string> = {
  muted: "Grey",
  info: "Blue",
  accent: "Green",
  warning: "Amber",
  danger: "Red",
};

export interface ScoringLevel {
  id: string;
  name: string;
  description: string | null;
  weight: number;
}

export interface ScoringAxis {
  key: string;
  label: string;
  description: string | null;
  /** Ascending weight order; the last is the axis's top level. */
  levels: ScoringLevel[];
}

export interface ScoringBand {
  label: string;
  /** Normalised lower bound in [0, 1). */
  min_score: number;
  tone: BadgeTone;
}

/** An explicit band for one cell of a two-axis model (first axis = rows, second = columns). */
export interface ScoringCellRating {
  first_level_id: string;
  second_level_id: string;
  /** Label of a band in the model's effective band set. */
  band_label: string;
}

export interface ScoringModel {
  key: string;
  label: string;
  axis_keys: string[];
  bands: ScoringBand[];
  bands_source: ScoringResolutionSource;
  /** Always empty unless the model has exactly two axes. */
  cell_ratings: ScoringCellRating[];
  cell_ratings_source: ScoringResolutionSource;
}

export interface ScoringScheme {
  key: string;
  label: string;
  module_key: string;
  axes: ScoringAxis[];
  models: ScoringModel[];
  system_default_model_key: string;
  default_model_key: string;
  default_model_source: ScoringResolutionSource;
}

export interface ScoringLevelInput {
  name: string;
  weight: number;
  description: string | null;
}

/** Returns the band whose threshold `normalised` reaches last, or null. */
export function bandFor(normalised: number, bands: ScoringBand[]): ScoringBand | null {
  let match: ScoringBand | null = null;
  for (const band of bands) if (normalised >= band.min_score) match = band;
  return match;
}

/**
 * The band of one cell of a two-axis model: its explicit rating if it has
 * one whose band still exists, else the threshold band for `normalised`.
 */
export function bandForCell(
  firstLevelId: string, secondLevelId: string, normalised: number, bands: ScoringBand[], cells: ScoringCellRating[] = [],
): ScoringBand | null {
  const cell = cells.find((c) => c.first_level_id === firstLevelId && c.second_level_id === secondLevelId);
  const explicit = cell ? bands.find((b) => b.label === cell.band_label) : undefined;
  return explicit ?? bandFor(normalised, bands);
}

/** The top (maximum) weight of an axis, or 0 if it has no levels. */
export function topWeight(axis: ScoringAxis): number {
  return axis.levels.length ? axis.levels[axis.levels.length - 1].weight : 0;
}

const orgBase = (orgId: string, scheme: string) => `/api/v1/orgs/${orgId}/scoring-schemes/${scheme}`;
const projectBase = (projectId: string, scheme: string) => `/api/v1/projects/${projectId}/scoring-schemes/${scheme}`;

/** Org-level configuration (levels, default model, bands, cell ratings). */
export const orgScoringApi = {
  get: (orgId: string, scheme: string) => api.get<ScoringScheme>(orgBase(orgId, scheme)),
  createLevel: (orgId: string, scheme: string, axisKey: string, body: ScoringLevelInput) =>
    api.post<ScoringLevel>(`${orgBase(orgId, scheme)}/axes/${axisKey}/levels`, body),
  updateLevel: (orgId: string, scheme: string, levelId: string, body: ScoringLevelInput) =>
    api.patch<ScoringLevel>(`${orgBase(orgId, scheme)}/levels/${levelId}`, body),
  deleteLevel: (orgId: string, scheme: string, levelId: string, reassignToId?: string) =>
    api.delete<void>(
      `${orgBase(orgId, scheme)}/levels/${levelId}${reassignToId ? `?reassign_to_id=${encodeURIComponent(reassignToId)}` : ""}`,
    ),
  /** `null` clears the org default so the module default applies. */
  setDefaultModel: (orgId: string, scheme: string, model: string | null) =>
    api.put<ScoringScheme>(`${orgBase(orgId, scheme)}/default-model`, { model }),
  /** `null` clears the org bands so the module defaults apply. */
  setBands: (orgId: string, scheme: string, model: string, bands: ScoringBand[] | null) =>
    api.put<ScoringScheme>(`${orgBase(orgId, scheme)}/models/${model}/bands`, { bands }),
  /** `null` clears the org's cell ratings so cells use the bands' thresholds. */
  setCellRatings: (orgId: string, scheme: string, model: string, cells: ScoringCellRating[] | null) =>
    api.put<ScoringScheme>(`${orgBase(orgId, scheme)}/models/${model}/cell-ratings`, { cells }),
};

/** Project-level overrides (default model, bands, cell ratings); levels are org-only. */
export const projectScoringApi = {
  get: (projectId: string, scheme: string) => api.get<ScoringScheme>(projectBase(projectId, scheme)),
  /** `null` clears the override so the project inherits. */
  setDefaultModel: (projectId: string, scheme: string, model: string | null) =>
    api.put<ScoringScheme>(`${projectBase(projectId, scheme)}/default-model`, { model }),
  /** `null` clears the override so the project inherits. */
  setBands: (projectId: string, scheme: string, model: string, bands: ScoringBand[] | null) =>
    api.put<ScoringScheme>(`${projectBase(projectId, scheme)}/models/${model}/bands`, { bands }),
  /** `null` clears the override so the project inherits. */
  setCellRatings: (projectId: string, scheme: string, model: string, cells: ScoringCellRating[] | null) =>
    api.put<ScoringScheme>(`${projectBase(projectId, scheme)}/models/${model}/cell-ratings`, { cells }),
};
