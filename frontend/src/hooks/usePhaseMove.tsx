/**
 * Module: hooks/usePhaseMove
 *
 * Moving a stage, or a component's track, to another phase of its workflow, with the one confirmation a closed phase
 * needs ("also mark the approved requirements as completed?"). Shared by the stage and track pickers on the delivery plan
 * page, the track list in project administration and the stage list there, so the rule and the dialog exist once.
 *
 * Responsibilities:
 * - `requestMove` posts `{ phase_id, cascade_to_requirements }` to a transition endpoint through `useMutation` (success
 *   and failure Toasts), calls `onChanged` after a success, and for a closed phase first opens the confirmation.
 * - `dialog` is the confirmation element the host renders once.
 *
 * Design decisions: which phases a person may enter is decided by the server; this hook never gates a move.
 */
import { useState, type ReactNode } from "react";

import { api } from "../api/client";
import type { StagePhaseKind } from "../api/types";
import { CheckboxField } from "../components/FormFields";
import { ConfirmDialog } from "../components/ConfirmDialog";
import type { MutationVerb } from "./useMutation";
import { useMutation } from "./useMutation";

/** One move being requested. */
export interface PhaseMoveRequest {
  /** The transition endpoint of the stage or track. */
  path: string;
  /** The phase being moved to. */
  phase: { id: string; name: string; kind: StagePhaseKind };
  /** The noun in the feedback Toast. */
  noun: string;
}

/**
 * @param labels The closed-phase confirmation: its title, the cascade checkbox label and its help text.
 * @param verb The feedback verb (a track is "saved", a stage "moved").
 * @param onChanged Called after a successful move, so the host reloads.
 * @returns `requestMove` to call from a picker and `dialog`, the confirmation element to render once.
 */
export function usePhaseMove(
  labels: { title: string; cascade: string; cascadeHelp: string }, verb: MutationVerb, onChanged: () => void,
): { requestMove: (request: PhaseMoveRequest) => void; dialog: ReactNode } {
  const run = useMutation();
  const [closing, setClosing] = useState<PhaseMoveRequest | null>(null);
  const [cascade, setCascade] = useState(false);

  async function post(request: PhaseMoveRequest, cascadeToRequirements: boolean) {
    if (await run(() => api.post(request.path, { phase_id: request.phase.id, cascade_to_requirements: cascadeToRequirements }), verb, request.noun)) {
      onChanged();
    }
  }

  function requestMove(request: PhaseMoveRequest) {
    if (request.phase.kind === "closed") {
      setCascade(false);
      setClosing(request);
    } else {
      void post(request, false);
    }
  }

  const dialog = closing && (
    <ConfirmDialog
      title={labels.title}
      message={<CheckboxField help={labels.cascadeHelp} label={labels.cascade} checked={cascade} onChange={setCascade} />}
      confirmLabel={closing.phase.name}
      onConfirm={() => {
        const request = closing;
        setClosing(null);
        void post(request, cascade);
      }}
      onCancel={() => setClosing(null)}
    />
  );
  return { requestMove, dialog };
}
