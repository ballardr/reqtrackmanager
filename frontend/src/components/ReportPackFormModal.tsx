/**
 * Module: components/ReportPackFormModal
 *
 * The create and edit dialog of a report pack: its name, description and folder, through the one `ReportPackFields` group
 * so a field added later reaches both. Creating starts the pack with no reports; the editor is where they are
 * chosen.
 *
 * Responsibilities: validate the name locally, call the API, show the server's refusal (a taken name) in the dialog.
 * The caller owns the toast, the reload and any navigation, through `onSaved`.
 */
import { useState } from "react";

import { emptyPackDefinition, type ReportPackApi, type ReportPackSummary } from "../api/reportPacks";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage } from "../context/ToastContext";
import { useFolderSuggestions } from "../hooks/useFolderSuggestions";
import { folderProblem, tidyFolder } from "../utils/reportFolders";
import { FormActions } from "./FormActions";
import { TextAreaField, TextField } from "./FormFields";
import { Modal } from "./Modal";
import { ReportFolderField } from "./ReportFolderField";

/** The fields a pack's create and edit forms share, so a field added later reaches both. */
export function ReportPackFields({
  name, description, folder, folders, onName, onDescription, onFolder,
}: {
  name: string; description: string; folder: string; folders: string[];
  onName: (value: string) => void; onDescription: (value: string) => void; onFolder: (value: string) => void;
}) {
  const text = useStrings().reportPacks;
  return (
    <>
      <TextField helpNotNeeded required
        label={text.nameLabel} value={name} onChange={onName} inputProps={{ maxLength: 200, autoFocus: true }}
      />
      <TextAreaField helpNotNeeded label={text.descriptionLabel} value={description} onChange={onDescription} />
      <ReportFolderField value={folder} onChange={onFolder} suggestions={folders} />
    </>
  );
}

/**
 * @param api The calls bound to the scope the pack belongs to.
 * @param pack The pack to edit; omit it to create one.
 * @param onClose Called by Cancel and after a save.
 * @param onSaved Called with the saved pack after a create or edit (before `onClose`).
 */
export function ReportPackFormModal({
  api, pack, onClose, onSaved,
}: {
  api: ReportPackApi;
  pack?: ReportPackSummary;
  onClose: () => void;
  onSaved: (saved: ReportPackSummary, created: boolean) => void;
}) {
  const strings = useStrings();
  const text = strings.reportPacks;
  const [name, setName] = useState(pack?.name ?? "");
  const [description, setDescription] = useState(pack?.description ?? "");
  const [folder, setFolder] = useState(pack?.folder ?? "");
  const folders = useFolderSuggestions(api.list);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function save() {
    setBusy(true);
    setError(null);
    try {
      const saved = pack
        ? await api.update(pack.id, { name: name.trim(), description, folder: tidyFolder(folder) })
        : await api.create({ name: name.trim(), description, folder: tidyFolder(folder), definition: emptyPackDefinition() });
      onSaved(saved, !pack);
      onClose();
    } catch (err) {
      setError(toErrorMessage(err, strings.common.error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title={pack ? text.editTitle : text.createTitle} onClose={onClose}>
      <div className="stack">
        <ReportPackFields
          name={name} description={description} folder={folder} folders={folders}
          onName={setName} onDescription={setDescription} onFolder={setFolder}
        />
        <FormActions
          error={error}
          onCancel={onClose}
          onSave={() => void save()}
          saveLabel={pack ? strings.common.save : text.createButton}
          saveDisabled={busy || name.trim() === "" || folderProblem(folder) !== null}
          cancelDisabled={busy}
        />
      </div>
    </Modal>
  );
}
