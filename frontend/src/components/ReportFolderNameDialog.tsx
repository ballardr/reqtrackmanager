/**
 * Module: components/ReportFolderNameDialog
 *
 * The small form that names a folder in the Report setup list: a new folder (at the top level or inside another) or the
 * new name of an existing one. It is the list's own way to make and rename folders; `ReportFolderChooser` keeps the same
 * three folder actions for the Move dialog.
 *
 * Responsibilities: validate the typed name against the depth and length limits (`folderProblem`), call `onSubmit` with
 * the full path, and show the server's refusal (a duplicate, too deep) in the form without closing it.
 */
import { useState } from "react";

import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage } from "../context/ToastContext";
import { MAX_FOLDER_LEVEL_CHARS } from "../utils/reportFolders";
import { FormActions } from "./FormActions";
import { TextField } from "./FormFields";
import { Modal } from "./Modal";

/**
 * @param mode "add" makes a folder inside `parent`; "rename" renames the last level of `parent`.
 * @param parent The folder the action is on (`""` = the top level, for an add).
 * @param initialName The name to start from (a rename starts with the current name).
 * @param onSubmit Called with the trimmed name; rejecting shows the error and keeps the form open.
 * @param onClose Called by Cancel and after a successful submit.
 */
export function ReportFolderNameDialog({
  mode, parent, initialName = "", onSubmit, onClose,
}: {
  mode: "add" | "rename"; parent: string; initialName?: string; onSubmit: (name: string) => Promise<void>; onClose: () => void;
}) {
  const strings = useStrings();
  const text = strings.reportFolders;
  const [name, setName] = useState(initialName);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      await onSubmit(name.trim());
      onClose();
    } catch (err) {
      setError(toErrorMessage(err, strings.common.error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title={mode === "add" ? (parent === "" ? text.newFolder : text.newInside) : text.rename} onClose={onClose}>
      <div className="stack">
        <TextField
          helpNotNeeded required label={mode === "add" ? text.nameLabel(parent) : text.renameLabel(parent)} value={name} onChange={setName}
          inputProps={{
            maxLength: MAX_FOLDER_LEVEL_CHARS, autoFocus: true,
            onKeyDown: (e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                if (name.trim() !== "" && !busy) void submit();
              }
            },
          }}
        />
        <FormActions
          error={error} onCancel={onClose} onSave={() => void submit()} saveLabel={mode === "add" ? text.add : text.renameApply}
          saveDisabled={busy || name.trim() === ""} cancelDisabled={busy}
        />
      </div>
    </Modal>
  );
}
