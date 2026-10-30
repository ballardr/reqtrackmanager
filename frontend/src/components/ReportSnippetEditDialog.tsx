/**
 * Module: components/ReportSnippetEditDialog
 *
 * The dialog that changes a saved snippet's details (name, description, category) through the same field group as the save
 * dialog. Its blocks are not edited here: changing them means saving a selection again from the designer.
 *
 * Responsibilities: call the API, show the server's refusal (a taken name) in the dialog's header; the caller owns the toast
 * and the reload through `onSaved`.
 */
import { useState } from "react";

import { ApiError } from "../api/client";
import type { ReportSnippetStoreApi, SavedSnippet } from "../api/reportSnippets";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage } from "../context/ToastContext";
import { FormActions } from "./FormActions";
import { Modal } from "./Modal";
import { ReportSnippetFields } from "./ReportSnippetFields";

/**
 * @param api The calls, bound to the snippet's owning scope.
 * @param snippet The snippet being changed.
 * @param categories The categories already in use, offered as suggestions.
 * @param onClose Called by Cancel.
 * @param onSaved Called with the changed snippet.
 */
export function ReportSnippetEditDialog({
  api, snippet, categories, onClose, onSaved,
}: {
  api: ReportSnippetStoreApi;
  snippet: SavedSnippet;
  categories: string[];
  onClose: () => void;
  onSaved: (saved: SavedSnippet) => void;
}) {
  const strings = useStrings();
  const text = strings.reportSnippetsPanel;
  const [name, setName] = useState(snippet.name);
  const [description, setDescription] = useState(snippet.description);
  const [category, setCategory] = useState(snippet.category);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    setBusy(true);
    setError(null);
    try {
      onSaved(await api.update(snippet.id, { name: name.trim(), description: description.trim(), category: category.trim() }));
    } catch (err) {
      setError(err instanceof ApiError && err.status === 409 ? strings.reportSnippetSave.nameTaken : toErrorMessage(err, text.editFailed));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title={text.editTitle(snippet.name)} onClose={onClose}>
      <div className="stack">
        <FormActions error={error} onCancel={onClose} onSave={() => void save()} saveDisabled={busy || name.trim() === ""} cancelDisabled={busy} />
        <ReportSnippetFields
          name={name} description={description} category={category} categories={categories}
          onName={setName} onDescription={setDescription} onCategory={setCategory}
        />
      </div>
    </Modal>
  );
}
