/**
 * Module: modules/traceability/LifecycleRequiredModal
 *
 * The dialog that sets which optional states a governance profile requires of one record type: one checkbox per
 * optional state of the type, saved together from the dialog's header.
 *
 * Responsibilities: hold the ticked states while the dialog is open, report a failed save beside the actions, and hand
 * the chosen keys to `onSave`; an empty set removes the requirement.
 *
 * Design decisions: only the optional states are listed, because a gated or path-end state cannot be required; the group
 * carries one `(?)` for the whole choice, so each box is self-explanatory.
 */
import { useState } from "react";

import { FieldCaption } from "../../components/FieldHelp";
import { FormActions } from "../../components/FormActions";
import { CheckboxField } from "../../components/FormFields";
import { Modal } from "../../components/Modal";
import { toErrorMessage } from "../../context/ToastContext";
import { GOVERNANCE_HELP } from "./help";
import type { LifecycleStateOption } from "./types";

/**
 * @param typeLabel The record type's singular name, for the title.
 * @param states The type's optional states, in path order.
 * @param initial The keys of the states required now.
 * @param onSave Saves the chosen keys; rejects to report a failure, which stays in the dialog.
 * @param onClose Closes the dialog.
 */
export function LifecycleRequiredModal({
  typeLabel, states, initial, onSave, onClose,
}: {
  typeLabel: string;
  states: LifecycleStateOption[];
  initial: string[];
  onSave: (required: string[]) => Promise<void>;
  onClose: () => void;
}) {
  const [chosen, setChosen] = useState<Set<string>>(() => new Set(initial));
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  function toggle(key: string, on: boolean) {
    const next = new Set(chosen);
    if (on) next.add(key);
    else next.delete(key);
    setChosen(next);
  }

  async function save() {
    setSaving(true);
    setError(null);
    try {
      await onSave(states.map((s) => s.key).filter((k) => chosen.has(k)));
    } catch (err) {
      setError(toErrorMessage(err, "The required states could not be saved."));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title={`Required states: ${typeLabel}`} onClose={onClose}>
      <div className="stack">
        <FormActions error={error} onCancel={onClose} onSave={() => void save()} saveDisabled={saving} />
        <div role="group" aria-label="Required states" className="stack" style={{ gap: "var(--space-2)" }}>
          <FieldCaption label="Required states" help={GOVERNANCE_HELP.lifecycleRequired} />
          {states.map((state) => (
            <CheckboxField key={state.key} helpNotNeeded label={state.label} checked={chosen.has(state.key)} onChange={(on) => toggle(state.key, on)} />
          ))}
        </div>
      </div>
    </Modal>
  );
}
