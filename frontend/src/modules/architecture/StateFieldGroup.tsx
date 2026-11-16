/**
 * Module: modules/architecture/StateFieldGroup
 *
 * The field group of a state of a state machine diagram, shared by the Selection card (edited in place) and the edit dialog
 * (`StateFormModal`, opened by double-clicking a state), so a field added later reaches both: the name (required), the kind,
 * and, for an ordinary state, the description and the entry, exit and activity lines. A marker (initial state, final state,
 * choice) is a shape with no inside, so it takes a name, a symbol label (up to 256 characters) and where the label is drawn:
 * inside the symbol (which grows to hold it, and a word too long for the largest symbol is warned about) or beside it. A state is added to a diagram with no form (its kind is chosen
 * in the Add to diagram menu), so this group has no creation variant.
 */
import { TextAreaField, TextField } from "../../components/FormFields";
import { FormGridFull } from "../../components/FormGrid";
import { LabeledSelect } from "../../components/LabeledSelect";
import { labelOptions } from "../../utils/labelOptions";
import { ARCHITECTURE_HELP } from "./help";
import { isMarkerKind } from "./stateMachineModel";
import { fitLabel } from "./symbolLabelLayout";
import { LABEL_POSITION_LABEL, STATE_KIND_LABEL, SYMBOL_LABEL_MAX, type LabelPosition, type StateFieldValues, type StateKind } from "./types";

/** The characters from which the label field shows how many remain (a limit that matters only near it). */
const LABEL_COUNT_FROM = 200;

/**
 * The note under the symbol label field: a warning when a word is longer than the largest symbol can hold (it is drawn whole on
 * one line and extends past the symbol; the text beside a symbol has no such limit), and the length once it nears the limit.
 * Shown only while it applies.
 *
 * @param values The form's values.
 * @returns The note, or undefined when there is nothing to say.
 */
function symbolLabelHint(values: StateFieldValues) {
  const layout = isMarkerKind(values.kind) && values.label_position === "inside" ? fitLabel(values.kind, values.label) : null;
  const tooLong = layout !== null && !layout.fits;
  const counted = values.label.length >= LABEL_COUNT_FROM;
  if (!tooLong && !counted) return undefined;
  return (
    <>
      {tooLong && (
        <span role="alert" style={{ color: "var(--color-danger)" }}>
          A word in this label is longer than the largest symbol holds. It is drawn whole on one line and extends past the symbol; shorten it or separate it into words.{" "}
        </span>
      )}
      {counted && <span>{values.label.length} of {SYMBOL_LABEL_MAX} characters.</span>}
    </>
  );
}

/**
 * @param values The form's values.
 * @param onChange Called with one changed field.
 * @param holdsStates True when the state has child states, which a marker cannot have (the kind then offers no marker).
 * @param autoFocusName True to put the cursor in the name field when the group first appears (a state just added).
 */
export function StateFieldGroup({
  values, onChange, holdsStates = false, autoFocusName = false,
}: {
  values: StateFieldValues;
  onChange: <K extends keyof StateFieldValues>(key: K, value: StateFieldValues[K]) => void;
  holdsStates?: boolean;
  autoFocusName?: boolean;
}) {
  const marker = isMarkerKind(values.kind);
  const kinds = labelOptions(STATE_KIND_LABEL).filter((o) => !holdsStates || !isMarkerKind(o.value));
  return (
    <>
      <FormGridFull>
        <TextField
          helpNotNeeded required label={marker ? "Name (Outline and exports)" : "Name"} value={values.name} onChange={(value) => onChange("name", value)}
          inputProps={autoFocusName ? { autoFocus: true, onFocus: (event) => event.currentTarget.select() } : undefined}
        />
      </FormGridFull>
      <LabeledSelect
        help={ARCHITECTURE_HELP.stateKind} label="Kind" value={values.kind} placeholder={null} options={kinds}
        onChange={(next) => onChange("kind", next as StateKind)}
      />
      {marker && (
        <FormGridFull>
          <TextAreaField
            help={ARCHITECTURE_HELP.stateLabel} label="Symbol label" value={values.label} rows={1} hint={symbolLabelHint(values)}
            inputProps={{ maxLength: SYMBOL_LABEL_MAX }} onChange={(value) => onChange("label", value)}
          />
        </FormGridFull>
      )}
      {marker && (
        <LabeledSelect
          help={ARCHITECTURE_HELP.stateLabelPosition} label="Label position" value={values.label_position} placeholder={null}
          options={labelOptions(LABEL_POSITION_LABEL)} onChange={(next) => onChange("label_position", next as LabelPosition)}
        />
      )}
      {!marker && (
        <>
          <FormGridFull>
            <TextAreaField helpNotNeeded label="Description" value={values.description} onChange={(value) => onChange("description", value)} />
          </FormGridFull>
          <TextField help={ARCHITECTURE_HELP.stateEntry} label="Entry action" value={values.entry_action} onChange={(value) => onChange("entry_action", value)} />
          <TextField help={ARCHITECTURE_HELP.stateExit} label="Exit action" value={values.exit_action} onChange={(value) => onChange("exit_action", value)} />
          <FormGridFull>
            <TextField help={ARCHITECTURE_HELP.stateActivity} label="Activity" value={values.activity} onChange={(value) => onChange("activity", value)} />
          </FormGridFull>
        </>
      )}
    </>
  );
}
