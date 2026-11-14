/**
 * Module: modules/architecture/TakeBaselineModal
 *
 * The "Take baseline" dialog: a name for a manual baseline of the project's architecture (the elements, connections, diagrams and
 * state machine diagrams as they stand). Saving sends the name; the page takes the baseline and reports a refusal in the dialog.
 */
import { useState } from "react";

import { FormActions } from "../../components/FormActions";
import { TextField } from "../../components/FormFields";
import { Modal } from "../../components/Modal";
import { ARCHITECTURE_HELP } from "./help";

/**
 * @param error A save error to show.
 * @param onCancel Called when the dialog is dismissed.
 * @param onSave Called with the trimmed name.
 */
export function TakeBaselineModal({
  error, onCancel, onSave,
}: { error?: string | null; onCancel: () => void; onSave: (label: string) => void }) {
  const [label, setLabel] = useState("");
  return (
    <Modal title="Take baseline" onClose={onCancel}>
      <div className="stack">
        <TextField required label="Name" help={ARCHITECTURE_HELP.baselineTake} value={label} onChange={setLabel} />
        <FormActions error={error} onCancel={onCancel} onSave={() => onSave(label.trim())} saveDisabled={label.trim() === ""} saveLabel="Take baseline" />
      </div>
    </Modal>
  );
}
