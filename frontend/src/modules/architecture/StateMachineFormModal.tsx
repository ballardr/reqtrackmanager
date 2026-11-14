/**
 * Module: modules/architecture/StateMachineFormModal
 *
 * The edit dialog of a state machine diagram (name, description, the element it describes), on the shared field group
 * `StateMachineFields`. Creation is the Diagrams list's `DiagramFormModal`, whose Type choice shows the same fields.
 */
import { useState } from "react";

import { FormActions } from "../../components/FormActions";
import { FormGrid } from "../../components/FormGrid";
import { Modal } from "../../components/Modal";
import { StateMachineFields } from "./StateMachineFields";
import { valuesFromStateMachine } from "./stateMachineFieldValues";
import type { ArchitectureElement, StateMachineDiagram, StateMachineFieldValues } from "./types";

/**
 * @param initial The diagram being edited.
 * @param elements The elements that may be chosen.
 * @param error A save error to show.
 * @param onSave Called with the values.
 */
export function StateMachineFormModal({
  initial, elements, error, onCancel, onSave,
}: {
  initial: StateMachineDiagram;
  elements: ArchitectureElement[];
  error?: string | null;
  onCancel: () => void;
  onSave: (values: StateMachineFieldValues) => void;
}) {
  const [values, setValues] = useState<StateMachineFieldValues>(() => valuesFromStateMachine(initial));
  const valid = values.name.trim() !== "" && values.element_id !== "";
  return (
    <Modal title={`Edit ${initial.name}`} onClose={onCancel} size="lg">
      <div className="stack">
        <FormGrid minColumn="18rem">
          <StateMachineFields
            values={values} elements={elements} currentElementId={initial.element_id}
            onChange={(key, value) => setValues((prev) => ({ ...prev, [key]: value }))}
          />
        </FormGrid>
        <FormActions error={error} onCancel={onCancel} onSave={() => onSave({ ...values, name: values.name.trim() })} saveDisabled={!valid} />
      </div>
    </Modal>
  );
}
