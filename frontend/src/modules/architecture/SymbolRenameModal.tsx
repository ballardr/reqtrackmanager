/**
 * Module: modules/architecture/SymbolRenameModal
 *
 * The dialog that renames one uploaded symbol. A name is unique among the symbols the owner offers (ignoring case); the
 * server's refusal is shown in the dialog. A built-in symbol is never offered this action (a bundle names it by its key).
 */
import { useState } from "react";

import { FormActions } from "../../components/FormActions";
import { TextField } from "../../components/FormFields";
import { Modal } from "../../components/Modal";
import { toErrorMessage } from "../../context/ToastContext";

/**
 * @param name The symbol's current name.
 * @param onSave Renames the symbol; may throw, and the message is shown in the dialog.
 * @param onClose Called when the dialog is cancelled or after a save.
 */
export function SymbolRenameModal({ name, onSave, onClose }: { name: string; onSave: (name: string) => Promise<void>; onClose: () => void }) {
  const [value, setValue] = useState(name);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function save() {
    setBusy(true);
    setError(null);
    try {
      await onSave(value.trim());
      onClose();
    } catch (err) {
      setError(toErrorMessage(err, "Could not rename the symbol."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title={`Rename ${name}`} onClose={onClose}>
      <div className="stack">
        <TextField required helpNotNeeded label="Name" value={value} onChange={setValue} inputProps={{ maxLength: 100 }} />
        <FormActions error={error} onCancel={onClose} onSave={() => void save()} saveDisabled={busy || value.trim() === "" || value.trim() === name} />
      </div>
    </Modal>
  );
}
