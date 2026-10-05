/**
 * Module: modules/stakeholders/useStakeholderScheme
 *
 * Loads the effective `stakeholder` scoring scheme (Influence × Interest
 * levels) for an org or project, which the Stakeholder form's level pickers
 * and the list's level columns read. `null` while loading or if the scheme
 * can't be read — callers then omit the scoring controls rather than failing.
 */
import { useEffect, useState } from "react";

import { orgScoringApi, projectScoringApi, type ScoringScheme } from "../../api/scoring";

/** Backend scheme key registered by `modules/stakeholders/scoring.py`. */
export const STAKEHOLDER_SCORING_SCHEME = "stakeholder";

/** Name of a level on `axisKey`, or `—` when unset or unknown. */
export function levelName(scheme: ScoringScheme | null, axisKey: string, levelId: string | null): string {
  if (!levelId || !scheme) return "—";
  return scheme.axes.find((a) => a.key === axisKey)?.levels.find((l) => l.id === levelId)?.name ?? "—";
}

/**
 * @param scope `{ projectId }` for the project's effective view, or `{ orgId }`.
 * @returns The scheme, or `null` until loaded / when unavailable.
 */
export function useStakeholderScheme(scope: { projectId: string } | { orgId: string }): ScoringScheme | null {
  const [scheme, setScheme] = useState<ScoringScheme | null>(null);
  const scopeKey = "projectId" in scope ? `p:${scope.projectId}` : `o:${scope.orgId}`;

  useEffect(() => {
    let active = true;
    const load =
      "projectId" in scope
        ? projectScoringApi.get(scope.projectId, STAKEHOLDER_SCORING_SCHEME)
        : orgScoringApi.get(scope.orgId, STAKEHOLDER_SCORING_SCHEME);
    load.then((s) => active && setScheme(s)).catch(() => active && setScheme(null));
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scopeKey]);

  return scheme;
}
