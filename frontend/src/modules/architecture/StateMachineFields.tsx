/**
 * Module: modules/architecture/StateMachineFields
 *
 * The field group of a state machine diagram, shared by the create form (inside `DiagramFormModal`) and the edit form
 * (`StateMachineFormModal`) so a field added later reaches both: the name, the description and the element it describes
 * (required; one the person can read and that is in use).
 */
import { TextAreaField, TextField } from "../../components/FormFields";
import { FormGridFull } from "../../components/FormGrid";
import { LabeledSelect } from "../../components/LabeledSelect";
import { useRecordCode } from "../../hooks/useRecordCode";
import { ARCHITECTURE_HELP } from "./help";
import { isOutOfUse, type ArchitectureElement, type StateMachineFieldValues } from "./types";

/**
 * @param values The form's values.
 * @param onChange Called with one changed field.
 * @param elements The elements that may be chosen (this project's own and those shared with it).
 * @param currentElementId The element the diagram already describes, kept in the list even when it is out of use.
 */
export function StateMachineFields({
  values, onChange, elements, currentElementId,
}: {
  values: StateMachineFieldValues;
  onChange: <K extends keyof StateMachineFieldValues>(key: K, value: StateMachineFieldValues[K]) => void;
  elements: ArchitectureElement[];
  currentElementId?: string;
}) {
  const formatCode = useRecordCode();
  const options = elements
    .filter((e) => !isOutOfUse(e.status) || e.id === currentElementId)
    .map((e) => ({ value: e.id, label: `${formatCode.code(e.unique_code, e.from_project_code)} ${e.name}` }));
  return (
    <>
      <FormGridFull>
        <TextField helpNotNeeded required label="Name" value={values.name} onChange={(value) => onChange("name", value)} />
      </FormGridFull>
      <FormGridFull>
        <LabeledSelect
          required help={ARCHITECTURE_HELP.stateMachineElement} label="Element" value={values.element_id}
          placeholder="Choose an element" options={options} onChange={(next) => onChange("element_id", next)}
        />
      </FormGridFull>
      <FormGridFull>
        <TextAreaField helpNotNeeded label="Description" value={values.description} onChange={(value) => onChange("description", value)} />
      </FormGridFull>
    </>
  );
}
