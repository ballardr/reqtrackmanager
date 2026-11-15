/**
 * Module: modules/architecture/TransitionFieldGroup
 *
 * The field group of a transition of a state machine diagram, shared by the Selection card (edited in place) and the edit dialog
 * (`TransitionFormModal`, opened by double-clicking a line), so a field added later reaches both: the two ends (required), the
 * event, the guard and the action (plain text a person reads, never run) and a description. A transition is added to a diagram
 * with no form (drawing a line or the card's "Add transition to" creates it with empty values), so this group has no creation variant.
 * A transition has no record code, so it takes no quick links or tags.
 */
import { TextAreaField, TextField } from "../../components/FormFields";
import { FormGridFull } from "../../components/FormGrid";
import { LabeledSelect } from "../../components/LabeledSelect";
import { ARCHITECTURE_HELP } from "./help";
import { useStateLabel } from "./useStateLabel";
import { STATE_KIND_LABEL, type ArchitectureState, type TransitionFieldValues } from "./types";

/** The field of a transition that takes the cursor when the group first appears (a transition just added). */
export type TransitionFocusField = "event" | "guard";

/**
 * @param states The diagram's states, for the two end pickers.
 * @param values The form's values.
 * @param onChange Called with one changed field.
 * @param autoFocus The field to put the cursor in when the group first appears; none when omitted.
 */
export function TransitionFieldGroup({
  states, values, onChange, autoFocus,
}: {
  states: ArchitectureState[];
  values: TransitionFieldValues;
  onChange: <K extends keyof TransitionFieldValues>(key: K, value: TransitionFieldValues[K]) => void;
  autoFocus?: TransitionFocusField;
}) {
  const stateName = useStateLabel().label;
  const options = states.map((s) => ({ value: s.id, label: `${stateName(s)}${s.kind === "state" ? "" : ` (${STATE_KIND_LABEL[s.kind]})`}` }));
  const focus = (field: TransitionFocusField) => (autoFocus === field ? { autoFocus: true } : undefined);
  return (
    <>
      <LabeledSelect
        required help={ARCHITECTURE_HELP.transitionEnds} label="From" value={values.source_state_id} placeholder="Choose a state"
        options={options} onChange={(next) => onChange("source_state_id", next)}
      />
      <LabeledSelect
        required helpNotNeeded label="To" value={values.target_state_id} placeholder="Choose a state"
        options={options} onChange={(next) => onChange("target_state_id", next)}
      />
      <TextField help={ARCHITECTURE_HELP.transitionEvent} label="Event" value={values.event} inputProps={focus("event")} onChange={(value) => onChange("event", value)} />
      <TextField help={ARCHITECTURE_HELP.transitionGuard} label="Guard" value={values.guard} inputProps={focus("guard")} onChange={(value) => onChange("guard", value)} />
      <FormGridFull>
        <TextField help={ARCHITECTURE_HELP.transitionAction} label="Action" value={values.action} onChange={(value) => onChange("action", value)} />
      </FormGridFull>
      <FormGridFull>
        <TextAreaField helpNotNeeded label="Description" value={values.description} onChange={(value) => onChange("description", value)} />
      </FormGridFull>
    </>
  );
}
