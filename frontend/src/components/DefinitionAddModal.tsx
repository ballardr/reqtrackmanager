/**
 * Module: components/DefinitionAddModal
 *
 * The create dialog of a `DefinitionList`: one labelled field per column of the list, opened by the list's Add
 * button so the list itself shows no empty inputs (docs/ux-style-guide.md, "Pattern: creation controls on demand").
 *
 * Responsibilities:
 * - Collect the values of the list's fields and hand them to the list's `onAdd`; a refusal stays in the dialog
 *   beside Save so the person can correct it, and the dialog closes only once the item exists.
 * - Mark the fields the list requires with `*` (a field is required unless it is `optional`).
 *
 * The caller's `onAdd` shows the success toast, so the dialog does not add a second one.
 */
import { useState } from "react";

import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage } from "../context/ToastContext";
import type { DefinitionListField } from "./DefinitionList";
import { FormActions } from "./FormActions";
import { TextAreaField, TextField } from "./FormFields";
import { Modal } from "./Modal";

/** The part of a `DefinitionListField` the dialog reads: the list's other column settings do not apply to a form. */
export type DefinitionAddField = Omit<DefinitionListField<unknown>, "getValue">;

/** The caption of a field: its column heading, else its placeholder or accessible name. */
function captionOf(field: DefinitionAddField): string {
  return field.label ?? field.placeholder ?? field.ariaLabel ?? field.key;
}

/** One field of the dialog; a field with `help` explains itself in a `(?)`, any other is self-explanatory. */
function AddField({
  field, value, onChange, autoFocus,
}: { field: DefinitionAddField; value: string; onChange: (next: string) => void; autoFocus: boolean }) {
  const required = !field.optional;
  const label = captionOf(field);
  if (field.multiline) {
    return field.help ? (
      <TextAreaField plainText="Configuration text shown in pickers and tooltips" help={field.help} required={required} label={label} value={value} onChange={onChange} />
    ) : (
      <TextAreaField plainText="Configuration text shown in pickers and tooltips" helpNotNeeded required={required} label={label} value={value} onChange={onChange} />
    );
  }
  const inputProps = { type: field.inputType ?? "text", autoFocus };
  return field.help ? (
    <TextField help={field.help} required={required} label={label} value={value} onChange={onChange} inputProps={inputProps} />
  ) : (
    <TextField helpNotNeeded required={required} label={label} value={value} onChange={onChange} inputProps={inputProps} />
  );
}

/**
 * @param title The dialog title (the list's Add label).
 * @param fields The list's fields, one input each, in column order.
 * @param onAdd Creates the item from the typed values (key to text); a rejection is shown in the dialog.
 * @param onClose Closes the dialog; called after a successful add and by the close button.
 */
export function DefinitionAddModal({
  title, fields, onAdd, onClose,
}: {
  title: string;
  fields: DefinitionAddField[];
  onAdd: (values: Record<string, string>) => Promise<void>;
  onClose: () => void;
}) {
  const strings = useStrings();
  const [draft, setDraft] = useState<Record<string, string>>(() => Object.fromEntries(fields.map((f) => [f.key, ""])));
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const valid = fields.every((f) => f.optional || draft[f.key].trim() !== "");

  async function save() {
    if (!valid || busy) return;
    setBusy(true);
    setError(null);
    try {
      await onAdd(draft);
      onClose();
    } catch (err) {
      setError(toErrorMessage(err, strings.common.error));
      setBusy(false);
    }
  }

  return (
    <Modal title={title} onClose={onClose}>
      <form className="stack" onSubmit={(e) => { e.preventDefault(); void save(); }}>
        {fields.map((f, index) => (
          <AddField
            key={f.key} field={f} value={draft[f.key]} autoFocus={index === 0}
            onChange={(next) => setDraft((current) => ({ ...current, [f.key]: next }))}
          />
        ))}
        <FormActions error={error} onCancel={onClose} onSave={() => void save()} saveLabel={strings.common.add} saveDisabled={!valid || busy} />
      </form>
    </Modal>
  );
}
