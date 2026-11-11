/**
 * Module: utils/stageBadge
 *
 * The one text a project row shows for its current stage: the stage name followed by the name of the
 * workflow phase it is in, shared by the project list and the favourites page so they cannot drift.
 */

import type { StagePhaseKind } from "../api/types";
import { STAGE_PHASE_KIND_LABEL } from "../api/types";

/**
 * The text a phase is shown with where its kind matters: the name, then the kind when the name does not
 * already say it ("Approved · Locked"; "Review" alone, since it is a Review phase).
 *
 * @param phaseName The phase's own (free-text) name.
 * @param kind The phase's kind.
 */
export function stagePhaseLabel(phaseName: string, kind: StagePhaseKind): string {
  const kindLabel = STAGE_PHASE_KIND_LABEL[kind];
  return phaseName.toLowerCase() === kindLabel.toLowerCase() ? phaseName : `${phaseName} · ${kindLabel}`;
}

/**
 * @param stageName The current stage's name.
 * @param phaseName The name of the phase the stage is in, or null when the project has no current stage.
 * @returns The stage name alone when the phase has the same name, else "Stage · Phase".
 */
export function stageBadgeText(stageName: string, phaseName: string | null): string {
  if (!phaseName || stageName.toLowerCase() === phaseName.toLowerCase()) return stageName;
  return `${stageName} · ${phaseName}`;
}
