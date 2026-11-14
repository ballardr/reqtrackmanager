/**
 * Module: modules/architecture/TransitionFormModal
 *
 * Create and edit dialog for a transition between two states of a state machine diagram: the two ends, the event, the guard
 * and the action (plain text a person reads, never run) and a description. The same dialog opens when a line is drawn from
 * one state to another (create, ends preselected) and from the Selection card's Edit (edit). A transition has no record
 * code, so it takes no quick links or tags.
 */
import { useState } from "react";

import { FormActions } from "../../components/FormActions";
import { TextAreaField, TextField } from "../../components/FormFields";
import { FormGrid, FormGridFull } from "../../components/FormGrid";
import { LabeledSelect } from "../../components/LabeledSelect";
import { Modal } from "../../components/Modal";
import { ARCHITECTURE_HELP } from "./help";
import { useStateLabel } from "./useStateLabel";
import { blankTransitionValues, valuesFromTransition } from "./transitionFields";
import { STATE_KIND_LABEL, type ArchitectureState, type StateTransition, type TransitionFieldValues } from "./types";

/**
 * @param states The diagram's states, for the two end pickers.
 * @param initial The transition being edited; omit to create.
 * @param defaultSourceId The state a new transition leaves.
 * @param defaultTargetId The state a new transition enters.
 * @param error A save error to show.
 * @param onSave Called with the values.
 */
export function TransitionFormModal({
  states, initial, defaultSourceId = "", defaultTargetId = "", error, onCancel, onSave,
}: {
  states: ArchitectureState[];
  initial?: StateTransition;
  defaultSourceId?: string;
  defaultTargetId?: string;
  error?: string | null;
  onCancel: () => void;
  onSave: (values: TransitionFieldValues) => void;
}) {
  const [values, setValues] = useState<TransitionFieldValues>(() => (
    initial ? valuesFromTransition(initial) : blankTransitionValues(defaultSourceId, defaultTargetId)
  ));
  const set = <K extends keyof TransitionFieldValues>(key: K, value: TransitionFieldValues[K]) => setValues((prev) => ({ ...prev, [key]: value }));
  const stateName = useStateLabel().label;
  const options = states.map((s) => ({ value: s.id, label: `${stateName(s)}${s.kind === "state" ? "" : ` (${STATE_KIND_LABEL[s.kind]})`}` }));
  const valid = values.source_state_id !== "" && values.target_state_id !== "";
  return (
    <Modal title={initial ? "Edit transition" : "New transition"} onClose={onCancel} size="lg">
      <div className="stack">
        <FormGrid minColumn="18rem">
          <LabeledSelect
            required help={ARCHITECTURE_HELP.transitionEnds} label="From" value={values.source_state_id} placeholder="Choose a state"
            options={options} onChange={(next) => set("source_state_id", next)}
          />
          <LabeledSelect
            required helpNotNeeded label="To" value={values.target_state_id} placeholder="Choose a state"
            options={options} onChange={(next) => set("target_state_id", next)}
          />
          <TextField help={ARCHITECTURE_HELP.transitionEvent} label="Event" value={values.event} onChange={(value) => set("event", value)} />
          <TextField help={ARCHITECTURE_HELP.transitionGuard} label="Guard" value={values.guard} onChange={(value) => set("guard", value)} />
          <FormGridFull>
            <TextField help={ARCHITECTURE_HELP.transitionAction} label="Action" value={values.action} onChange={(value) => set("action", value)} />
          </FormGridFull>
          <FormGridFull>
            <TextAreaField helpNotNeeded label="Description" value={values.description} onChange={(value) => set("description", value)} />
          </FormGridFull>
        </FormGrid>
        <FormActions error={error} onCancel={onCancel} onSave={() => onSave(values)} saveDisabled={!valid} />
      </div>
    </Modal>
  );
}
