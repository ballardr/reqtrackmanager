/**
 * Module: api/scoring
 *
 * Types and calls for the generic scoring-matrix API (Context &
 * Strategy). A module registers a scoring scheme (axes with
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

export type ScoringCriterionOrigin = "built_in" | "org" | "project";

/** Who defined a criterion, as the tier looking at it names them; a project's own is "This project". */
export function scoringOriginLabel(
  origin: ScoringCriterionOrigin | undefined, ownerProjectId: string | null | undefined, projectId?: string,
): string {
  if (origin === "org") return "Organisation";
  if (origin === "project") return ownerProjectId && ownerProjectId === projectId ? "This project" : "Parent project";
  return "Built in";
}

/** Whether the tier editing (the organisation, or `projectId`) defined this criterion, so it can edit and delete it rather than only hide it. */
export function scoringOwnsCriterion(
  origin: ScoringCriterionOrigin | undefined, ownerProjectId: string | null | undefined, projectId?: string,
): boolean {
  return projectId ? origin === "project" && ownerProjectId === projectId : origin === "org";
}

export interface ScoringLevel {
  id: string;
  name: string;
  description: string | null;
  weight: number;
  /** Only on a derived axis: the lowest derived value that falls in this level. */
  threshold?: number | null;
}

export interface ScoringAxis {
  key: string;
  label: string;
  description: string | null;
  /** Names the module-computed number a derived axis (e.g. Demand) is read from; null/absent for a manual axis. */
  derived_source?: string | null;
  /** Who defined it: the module (`built_in`), the organisation or a project (`owner_project_id`). */
  origin?: ScoringCriterionOrigin;
  owner_project_id?: string | null;
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
  /** Axes the product is divided by (e.g. Effort); absent or empty for a plain product. */
  divisor_axis_keys?: string[];
  /** `product` (axes multiplied, divisors divided, optional exponents) or `weighted_sum` (axes scaled to 0..1 and summed by importance). */
  combination?: "product" | "weighted_sum";
  /** Product only: importance exponent by axis key (an axis not listed is 1). */
  exponents?: Record<string, number>;
  /** Weighted sum only: percentage by axis key, totalling 100. */
  importance?: Record<string, number>;
  /** Weighted sum only: axes where a lower level scores higher. */
  inverted_axis_keys?: string[];
  origin?: ScoringCriterionOrigin;
  owner_project_id?: string | null;
  bands: ScoringBand[];
  bands_source: ScoringResolutionSource;
  /** Always empty unless the model has exactly two axes and no divisor. */
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
  /** The models shown side by side, the default first; absent from an older server. */
  enabled_model_keys?: string[];
  enabled_models_source?: ScoringResolutionSource;
  /** Whether the organisation and projects may define their own axes and models on this scheme. */
  allow_custom_criteria?: boolean;
  /** Whether the module scores a record with several models at once, so which models are enabled matters. */
  side_by_side_models?: boolean;
  /** Registered or inherited criteria this tier hid, which it can restore. */
  hidden_criteria?: { kind: "axis" | "model"; key: string; label: string }[];
}

export interface ScoringLevelInput {
  name: string;
  weight: number;
  description: string | null;
  /** Required on a derived axis, refused on a manual one. */
  threshold?: number | null;
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

/** One level of a new axis. */
export interface ScoringLevelSpec {
  name: string;
  weight: number;
  description: string | null;
}

/** Defines an axis: a name, optional guidance and its first levels (two to twelve). */
export interface ScoringAxisInput {
  label: string;
  description: string | null;
  levels: ScoringLevelSpec[];
}

/** How a model uses one axis: `multiply` or `divide` (with an exponent) in a product, `sum` (with an importance) in a weighted sum. */
export interface ScoringModelAxisInput {
  axis_key: string;
  role: "multiply" | "divide" | "sum";
  exponent?: number;
  importance?: number | null;
  lower_is_better?: boolean;
}

export interface ScoringModelInput {
  label: string;
  combination: "product" | "weighted_sum";
  axes: ScoringModelAxisInput[];
}

/** An axis or model a tier hid, or is asked to hide or restore. */
export interface ScoringCriterionRef {
  kind: "axis" | "model";
  key: string;
}

const orgBase = (orgId: string, scheme: string) => `/api/v1/orgs/${orgId}/scoring-schemes/${scheme}`;
const projectBase = (projectId: string, scheme: string) => `/api/v1/projects/${projectId}/scoring-schemes/${scheme}`;

/**
 * The calls that edit a tier's enabled models, own axes and models, and hidden criteria. The organisation and a
 * project expose them at the same paths under their own base, so both tiers share one set (`ScoringCriteria`).
 * Every call returns the tier's refreshed effective scheme.
 */
function criteriaCalls(base: string) {
  const enc = encodeURIComponent;
  return {
    /** `null` clears the override so the tier inherits; the default model is always shown. */
    setEnabledModels: (models: string[] | null) => api.put<ScoringScheme>(`${base}/enabled-models`, { models }),
    createAxis: (body: ScoringAxisInput) => api.post<ScoringScheme>(`${base}/axes`, body),
    updateAxis: (axisKey: string, body: { label?: string; description?: string | null }) =>
      api.patch<ScoringScheme>(`${base}/axes/${enc(axisKey)}`, body),
    /** 409 while a model uses the axis, or while scores use it unless `clearScores` drops them. */
    deleteAxis: (axisKey: string, clearScores = false) =>
      api.delete<ScoringScheme>(`${base}/axes/${enc(axisKey)}${clearScores ? "?clear_scores=true" : ""}`),
    createModel: (body: ScoringModelInput) => api.post<ScoringScheme>(`${base}/models`, body),
    updateModel: (modelKey: string, body: Partial<ScoringModelInput>) =>
      api.patch<ScoringScheme>(`${base}/models/${enc(modelKey)}`, body),
    deleteModel: (modelKey: string) => api.delete<ScoringScheme>(`${base}/models/${enc(modelKey)}`),
    hideCriterion: (ref: ScoringCriterionRef) => api.post<ScoringScheme>(`${base}/hidden-criteria`, ref),
    restoreCriterion: (ref: ScoringCriterionRef) =>
      api.delete<ScoringScheme>(`${base}/hidden-criteria?kind=${ref.kind}&key=${enc(ref.key)}`),
  };
}

/** The calls `ScoringCriteria` makes, for whichever tier (organisation or project) it is editing. */
export type ScoringCriteriaCalls = ReturnType<typeof criteriaCalls>;

/** Org-level configuration (levels, default model, enabled models, bands, cell ratings, own criteria). */
export const orgScoringApi = {
  /** The enabled-models, own-criteria and hide/restore calls for one scheme. */
  criteria: (orgId: string, scheme: string): ScoringCriteriaCalls => criteriaCalls(orgBase(orgId, scheme)),
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

/** Project-level overrides (default model, enabled models, bands, cell ratings, own criteria and their levels). */
export const projectScoringApi = {
  get: (projectId: string, scheme: string) => api.get<ScoringScheme>(projectBase(projectId, scheme)),
  /** The enabled-models, own-criteria and hide/restore calls for one scheme. */
  criteria: (projectId: string, scheme: string): ScoringCriteriaCalls => criteriaCalls(projectBase(projectId, scheme)),
  /** Levels of an axis this project defined (the organisation's levels are edited there). */
  createLevel: (projectId: string, scheme: string, axisKey: string, body: ScoringLevelInput) =>
    api.post<ScoringLevel>(`${projectBase(projectId, scheme)}/axes/${axisKey}/levels`, body),
  updateLevel: (projectId: string, scheme: string, levelId: string, body: ScoringLevelInput) =>
    api.patch<ScoringLevel>(`${projectBase(projectId, scheme)}/levels/${levelId}`, body),
  deleteLevel: (projectId: string, scheme: string, levelId: string, reassignToId?: string) =>
    api.delete<void>(
      `${projectBase(projectId, scheme)}/levels/${levelId}${reassignToId ? `?reassign_to_id=${encodeURIComponent(reassignToId)}` : ""}`,
    ),
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
