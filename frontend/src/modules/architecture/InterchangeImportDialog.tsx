/**
 * Module: modules/architecture/InterchangeImportDialog
 *
 * The dialog that imports a System Architecture JSON file into the project: choose the file, read what it would add (a
 * preview that stores nothing), then import.
 *
 * Responsibilities:
 * - Read the chosen file in the browser and send it for a preview; show the rows it would add by kind and anything it
 *   could not resolve (a connection whose end is not available, a symbol that is not found).
 * - Import only after a preview, and say so in a toast; the server's refusal (a wrong version, too large, no permission) is
 *   shown in the dialog and keeps it open.
 *
 * Design decisions:
 * - The preview runs by itself once a file is chosen, so the person never imports a file they have not seen described.
 * - The file is parsed here only to be sent; the server validates it again, so a hand-edited file is judged in one place.
 */
import { useState } from "react";

import { FormActions } from "../../components/FormActions";
import { FileField } from "../../components/FormFields";
import { InlineMessage } from "../../components/InlineMessage";
import { Modal } from "../../components/Modal";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { projectInterchangeApi } from "./api";
import { ARCHITECTURE_HELP } from "./help";
import { INTERCHANGE_KIND_LABEL, type InterchangeReport } from "./types";

/** The rows of a report that are not zero, as `[label, count]` in the order of `INTERCHANGE_KIND_LABEL`. */
function countedRows(report: InterchangeReport): [string, number][] {
  return Object.entries(INTERCHANGE_KIND_LABEL)
    .map(([kind, label]): [string, number] => [label, report.created[kind] ?? 0])
    .filter(([, count]) => count > 0);
}

/**
 * @param projectId The project the file is imported into.
 * @param onClose Called when the dialog is cancelled.
 * @param onImported Called after the import has been applied.
 */
export function InterchangeImportDialog({
  projectId, onClose, onImported,
}: { projectId: string; onClose: () => void; onImported: () => void }) {
  const { showToast } = useToast();
  const calls = projectInterchangeApi(projectId);
  const [document, setDocument] = useState<unknown>(null);
  const [preview, setPreview] = useState<InterchangeReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function choose(file: File | null) {
    setPreview(null);
    setDocument(null);
    setError(null);
    if (!file) return;
    setBusy(true);
    try {
      const parsed: unknown = JSON.parse(await file.text());
      setDocument(parsed);
      setPreview(await calls.preview(parsed));
    } catch (err) {
      setError(err instanceof SyntaxError ? "The file is not valid JSON." : toErrorMessage(err, "The file could not be read."));
    } finally {
      setBusy(false);
    }
  }

  async function run() {
    if (document === null) return;
    setBusy(true);
    setError(null);
    try {
      const done = await calls.apply(document);
      const total = Object.values(done.created).reduce((sum, n) => sum + n, 0);
      showToast(`Imported ${total} record${total === 1 ? "" : "s"}${done.warnings.length ? `, with ${done.warnings.length} warning${done.warnings.length === 1 ? "" : "s"}` : ""}.`);
      onImported();
    } catch (err) {
      setError(toErrorMessage(err, "The import failed."));
    } finally {
      setBusy(false);
    }
  }

  const rows = preview ? countedRows(preview) : [];
  return (
    <Modal title="Import JSON file" onClose={onClose} size="lg">
      <div className="stack">
        <FileField
          required label="File" accept=".json,application/json" help={ARCHITECTURE_HELP.interchangeFile}
          onChange={(file) => void choose(file)}
        />
        {preview && (
          <div className="stack" aria-label="Import preview">
            {rows.length === 0 ? <p>The file adds nothing.</p> : (
              <table className="table">
                <thead><tr><th>Will be added</th><th>Count</th></tr></thead>
                <tbody>{rows.map(([label, count]) => <tr key={label}><td>{label}</td><td>{count}</td></tr>)}</tbody>
              </table>
            )}
            {preview.warnings.length > 0 && (
              <InlineMessage tone="warning">
                <ul>{preview.warnings.map((w) => <li key={w}>{w}</li>)}</ul>
              </InlineMessage>
            )}
          </div>
        )}
        <FormActions
          error={error} onCancel={onClose} onSave={() => void run()} saveLabel="Import"
          saveDisabled={busy || preview === null || rows.length === 0}
        />
      </div>
    </Modal>
  );
}
