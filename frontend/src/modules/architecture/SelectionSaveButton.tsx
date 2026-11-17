/**
 * Module: modules/architecture/SelectionSaveButton
 *
 * The Save button of a Selection card that edits a record in place (element, connection, state, transition). It is drawn on the
 * card's heading line, beside the title, through `CardHeaderAction`, so it stays in view however long the card is and sits where an edit
 * dialog's Save does. It is always present and disabled while nothing has changed, so the header does not change size as the person types.
 * The accessible name says what is stored ("Save element"); the visible text is "Save".
 */
import { CardHeaderAction } from "../../components/CardHeaderAction";

/**
 * @param label The accessible name, e.g. "Save element".
 * @param disabled True while nothing differs from what is stored.
 * @param onSave Stores the changes.
 */
export function SelectionSaveButton({ label, disabled, onSave }: { label: string; disabled: boolean; onSave: () => void }) {
  return (
    <CardHeaderAction>
      <button type="button" className="btn btn-sm btn-primary" disabled={disabled} onClick={onSave} aria-label={label}>
        Save
      </button>
    </CardHeaderAction>
  );
}
