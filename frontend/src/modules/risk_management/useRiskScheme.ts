/**
 * Module: modules/risk_management/useRiskScheme
 *
 * Loads the project's effective `risk` scoring scheme (Likelihood,
 * Consequence and Detectability levels, models, bands and per-cell ratings),
 * which the risk form's level pickers, the matrix grid and the level-name
 * columns read. `null` while loading or when it cannot be read — callers then
 * omit the scoring controls rather than failing the page.
 */
import { useEffect, useState } from "react";

import { projectScoringApi, type ScoringAxis, type ScoringBand, type ScoringModel, type ScoringScheme } from "../../api/scoring";
import { RISK_SCORING_SCHEME } from "./types";

export const LIKELIHOOD_AXIS = "likelihood";
export const CONSEQUENCE_AXIS = "consequence";
export const DETECTABILITY_AXIS = "detectability";

/** The axis with `key`, or undefined when the scheme is not loaded or lacks it. */
export function findAxis(scheme: ScoringScheme | null, key: string): ScoringAxis | undefined {
  return scheme?.axes.find((a) => a.key === key);
}

/** Name of a level on `axisKey`, or `—` when unset or unknown. */
export function levelName(scheme: ScoringScheme | null, axisKey: string, levelId: string | null): string {
  if (!levelId) return "—";
  return findAxis(scheme, axisKey)?.levels.find((l) => l.id === levelId)?.name ?? "—";
}

/** The two-axis model (Likelihood × Consequence) the matrix grid draws; per-cell ratings only exist on it. */
export function gridModel(scheme: ScoringScheme | null): ScoringModel | undefined {
  return scheme?.models.find((m) => m.axis_keys.length === 2);
}

/**
 * @param projectId The project whose effective scheme is read.
 * @returns The scheme, or `null` until loaded / when unavailable.
 */
export function useRiskScheme(projectId: string | undefined): ScoringScheme | null {
  const [loaded, setLoaded] = useState<{ projectId: string; scheme: ScoringScheme } | null>(null);

  useEffect(() => {
    if (!projectId) return;
    let active = true;
    projectScoringApi
      .get(projectId, RISK_SCORING_SCHEME)
      .then((scheme) => active && setLoaded({ projectId, scheme }))
      .catch(() => active && setLoaded(null));
    return () => {
      active = false;
    };
  }, [projectId]);

  return loaded && loaded.projectId === projectId ? loaded.scheme : null;
}

/** The tone of the band called `label` in any of the scheme's models (the review history stores labels only), else null. */
export function bandTone(scheme: ScoringScheme | null, label: string | null): ScoringBand["tone"] | null {
  if (!scheme || !label) return null;
  for (const model of scheme.models) {
    const band = model.bands.find((b) => b.label === label);
    if (band) return band.tone;
  }
  return null;
}
