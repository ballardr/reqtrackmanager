/**
 * Module: utils/phaseOptions
 *
 * The choices of a phase picker for a stage or a component's track.
 *
 * Responsibilities: list the phases of the holder's workflow, marking unavailable (shown but not choosable, with the
 * reason in the label, as `InlineSelect` does for any unavailable candidate) the phases the project's lifecycle does not
 * allow the holder to move to (`unavailable_phases` from the server) and, for a stage, the locked phases a caller who may
 * not lock cannot enter or leave.
 *
 * Design decision: the server's answer is the one rule (`apply_phase_move` checks the same lifecycle), so the picker
 * never recomputes which kinds may follow which.
 */
import type { StagePhaseKind, UnavailablePhase } from "../api/types";
import type { InlineSelectOption } from "../components/LabeledSelect";
import type { Strings } from "../i18n/strings";

interface PhaseChoice {
  id: string;
  name: string;
  kind: StagePhaseKind;
}

/** The wording a picker needs (`strings.stageWorkflows`, from `useStrings()`). */
export type PhaseOptionLabels = Pick<Strings["stageWorkflows"], "lockedNeedsManager" | "phaseTurnedOff" | "phaseNotReachable">;

interface PhaseHolder {
  phase_id: string;
  phase_kind: StagePhaseKind;
  unavailable_phases?: UnavailablePhase[];
}

/**
 * @param labels The wording for an unavailable phase (`strings.stageWorkflows`).
 * @param phases The phases of the holder's workflow, in order.
 * @param holder The stage or track: its current phase and the phases it cannot move to.
 * @param canLock Whether the caller may enter or leave a locked phase; a track's mover passes `true`.
 * @returns The picker options; the current phase is always choosable.
 */
export function phaseOptions(
  labels: PhaseOptionLabels, phases: PhaseChoice[], holder: PhaseHolder, canLock = true,
): InlineSelectOption[] {
  const unavailable = new Map((holder.unavailable_phases ?? []).map((u) => [u.phase_id, u]));
  return phases.map((p) => {
    if (p.id === holder.phase_id) return { value: p.id, label: p.name };
    const blocked = unavailable.get(p.id);
    if (blocked) {
      const label = blocked.turned_off ? labels.phaseTurnedOff(p.name) : labels.phaseNotReachable(p.name);
      return { value: p.id, label, disabled: true };
    }
    const locked = !canLock && (p.kind === "locked" || holder.phase_kind === "locked");
    return { value: p.id, label: locked ? labels.lockedNeedsManager(p.name) : p.name, disabled: locked };
  });
}
