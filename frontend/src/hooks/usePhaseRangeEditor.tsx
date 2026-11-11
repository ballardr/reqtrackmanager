/**
 * Module: hooks/usePhaseRangeEditor
 *
 * Setting the expected range of one phase of a stage, or of a component's track within it: opens `PhaseRangeEditor` and
 * saves with `PUT .../stages/{id}/phase-plan`. Shared by the phase schedule in project administration and the delivery plan
 * page, so the call, its error message and its reload are written once.
 *
 * Time shape: the two dates are calendar dates in the planner's own day; the server stores them as plain dates.
 */
import { useState, type ReactNode } from "react";

import { api } from "../api/client";
import { PhaseRangeEditor } from "../components/PhaseRangeEditor";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage } from "../context/ToastContext";

/** The phase being scheduled and what it holds now. */
export interface PhaseRangeTarget {
  stageId: string;
  /** Null for the stage's own phase. */
  componentId: string | null;
  phaseId: string;
  /** The dialog title (the stage and the phase). */
  title: string;
  expectedFrom: string | null;
  expectedTo: string | null;
}

/**
 * @param base The project's API base (`/api/v1/projects/{id}`).
 * @param onSaved Called after a successful save, so the host reloads.
 * @returns `open` to start editing a phase and `dialog`, the editor element to render once.
 */
export function usePhaseRangeEditor(base: string, onSaved: () => void): { open: (target: PhaseRangeTarget) => void; dialog: ReactNode } {
  const strings = useStrings();
  const [target, setTarget] = useState<PhaseRangeTarget | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function save(expectedFrom: string | null, expectedTo: string | null) {
    if (!target) return;
    setError(null);
    try {
      await api.put(`${base}/stages/${target.stageId}/phase-plan`, {
        phase_id: target.phaseId, component_id: target.componentId, expected_from: expectedFrom, expected_to: expectedTo,
      });
    } catch (err) {
      setError(toErrorMessage(err, strings.mutation.failure("save", strings.phaseSchedule.nounPlan)));
      return;
    }
    setTarget(null);
    onSaved();
  }

  const dialog = target && (
    <PhaseRangeEditor
      title={target.title} expectedFrom={target.expectedFrom} expectedTo={target.expectedTo}
      error={error} onCancel={() => setTarget(null)} onSave={(from, to) => void save(from, to)}
    />
  );
  return { open: (next) => { setError(null); setTarget(next); }, dialog };
}
