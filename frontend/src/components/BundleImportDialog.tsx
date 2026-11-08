/**
 * Module: components/BundleImportDialog
 *
 * The dialog that imports an exported bundle (.zip) as a new project or organisation. It is the second door
 * beside a create dialog (`SplitButtonTrigger`), so a bundle import never hides fields of the create form.
 *
 * Responsibilities: hold the chosen file, call the caller's import, show its error in the dialog header and
 * disable Import while it runs or no file is chosen. The caller supplies the fields that go with the file (the
 * name, the organisation) as children and performs the request, so each import keeps its own endpoint and
 * result handling.
 */
import { useState, type ReactNode } from "react";

import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage } from "../context/ToastContext";
import { FormActions } from "./FormActions";
import { FileField } from "./FormFields";
import { FormGrid, FormGridFull } from "./FormGrid";
import { Modal } from "./Modal";

/**
 * @param title Dialog title.
 * @param fileLabel Label of the file field.
 * @param fileHelp Help text of the file field.
 * @param onClose Called when the dialog is closed, and after a successful import.
 * @param onImport Performs the import with the chosen file; a thrown error is shown in the dialog and keeps it open.
 * @param canImport False while a field the import needs (the name, the organisation) is missing.
 * @param children The fields beside the file, laid out in the dialog's grid.
 */
export function BundleImportDialog({
  title, fileLabel, fileHelp, onClose, onImport, canImport = true, children,
}: {
  title: string;
  fileLabel: string;
  fileHelp: string;
  onClose: () => void;
  onImport: (file: File) => Promise<void>;
  canImport?: boolean;
  children: ReactNode;
}) {
  const strings = useStrings();
  const [file, setFile] = useState<File | null>(null);
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    if (!file) return;
    setImporting(true);
    setError(null);
    try {
      await onImport(file);
    } catch (err) {
      setError(toErrorMessage(err, strings.common.error));
    } finally {
      setImporting(false);
    }
  }

  return (
    <Modal title={title} onClose={onClose} size="lg">
      <div className="stack">
        <FormGrid minColumn="18rem">
          {children}
          <FormGridFull>
            <FileField required help={fileHelp} label={fileLabel} accept=".zip,application/zip" onChange={setFile} />
          </FormGridFull>
        </FormGrid>
        <FormActions
          error={error}
          onCancel={onClose}
          onSave={run}
          saveLabel={strings.common.import}
          saveDisabled={!file || !canImport || importing}
        />
      </div>
    </Modal>
  );
}
