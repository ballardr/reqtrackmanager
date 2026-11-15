/**
 * Module: modules/architecture/TransitionFormModal
 *
 * Edit dialog for a transition between two states of a state machine diagram, opened by double-clicking its line: the shared
 * field group (`TransitionFieldGroup`) with Cancel and Save in the header. A transition is added with no dialog (drawing a line
 * creates it and its fields are set in the Selection card), so this dialog has no creation variant.
 */
import { useState } from "react";

import { FormActions } from "../../components/FormActions";
import { FormGrid } from "../../components/FormGrid";
import { Modal } from "../../components/Modal";
import { TransitionFieldGroup } from "./TransitionFieldGroup";
import { valuesFromTransition } from "./transitionFields";
import type { ArchitectureState, StateTransition, TransitionFieldValues } from "./types";

/**
 * @param states The diagram's states, for the two end pickers.
 * @param initial The transition being edited.
 * @param error A save error to show.
 * @param onSave Called with the values.
 */
export function TransitionFormModal({
  states, initial, error, onCancel, onSave,
}: {
  states: ArchitectureState[];
  initial: StateTransition;
  error?: string | null;
  onCancel: () => void;
  onSave: (values: TransitionFieldValues) => void;
}) {
  const [values, setValues] = useState<TransitionFieldValues>(() => valuesFromTransition(initial));
  const set = <K extends keyof TransitionFieldValues>(key: K, value: TransitionFieldValues[K]) => setValues((prev) => ({ ...prev, [key]: value }));
  const valid = values.source_state_id !== "" && values.target_state_id !== "";
  return (
    <Modal title="Edit transition" onClose={onCancel} size="lg">
      <div className="stack">
        <FormGrid minColumn="18rem">
          <TransitionFieldGroup states={states} values={values} onChange={set} />
        </FormGrid>
        <FormActions error={error} onCancel={onCancel} onSave={() => onSave(values)} saveDisabled={!valid} />
      </div>
    </Modal>
  );
}
