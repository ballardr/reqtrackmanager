/**
 * Module: modules/architecture/StateFormModal
 *
 * Edit dialog for a state of a state machine diagram, opened by double-clicking the state on the canvas. It shows the same
 * field group as the Selection card (`StateFieldGroup`). A state is added with no form (the Add to diagram menu names its kind and
 * the Selection card takes the rest), so there is no creation variant.
 */
import { useState } from "react";

import { FormActions } from "../../components/FormActions";
import { FormGrid } from "../../components/FormGrid";
import { Modal } from "../../components/Modal";
import { StateFieldGroup } from "./StateFieldGroup";
import { valuesFromState } from "./stateFields";
import type { ArchitectureState, StateFieldValues } from "./types";

/**
 * @param initial The state being edited.
 * @param holdsStates True when the state has child states, which a marker cannot have (the kind is then fixed).
 * @param error A save error to show.
 * @param onSave Called with the edited values.
 */
export function StateFormModal({
  initial, holdsStates = false, error, onCancel, onSave,
}: {
  initial: ArchitectureState;
  holdsStates?: boolean;
  error?: string | null;
  onCancel: () => void;
  onSave: (values: StateFieldValues) => void;
}) {
  const [values, setValues] = useState<StateFieldValues>(() => valuesFromState(initial));
  const set = <K extends keyof StateFieldValues>(key: K, value: StateFieldValues[K]) => setValues((prev) => ({ ...prev, [key]: value }));
  return (
    <Modal title={`Edit ${initial.name}`} onClose={onCancel} size="lg">
      <div className="stack">
        <FormGrid minColumn="18rem">
          <StateFieldGroup values={values} onChange={set} holdsStates={holdsStates} />
        </FormGrid>
        <FormActions
          error={error} onCancel={onCancel} saveDisabled={values.name.trim() === ""}
          onSave={() => onSave({ ...values, name: values.name.trim() })}
        />
      </div>
    </Modal>
  );
}
