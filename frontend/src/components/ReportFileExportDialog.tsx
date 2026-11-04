/**
 * Module: components/ReportFileExportDialog
 *
 * The dialog that exports the chosen layouts and packs as a `.zip` report file: two switches (earlier versions, the
 * layouts a pack uses) and a Download action.
 *
 * Responsibilities:
 * - Send the choice to the server and save the file under the name the server gives it.
 * - Say what the file holds and that it can be imported elsewhere; the packs switch shows only when a pack is chosen.
 *
 * Design decisions: the server builds the file (one serialiser shared with the bundles and the copy), the dialog only
 * asks and saves. Follows the form header pattern (`FormActions` in the dialog header) and the field help pattern.
 */
import { useState } from "react";

import type { ReportFileApi } from "../api/reportFile";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { downloadBlob } from "../utils/download";
import { CheckboxField } from "./FormFields";
import { FormActions } from "./FormActions";
import { Modal } from "./Modal";

/**
 * @param api The calls, bound to the organisation or project the person is working in.
 * @param layoutIds The layouts to export.
 * @param packIds The packs to export.
 * @param onClose Called by Cancel and once the file is saved.
 */
export function ReportFileExportDialog({
  api, layoutIds, packIds, onClose,
}: { api: ReportFileApi; layoutIds: string[]; packIds: string[]; onClose: () => void }) {
  const text = useStrings().reportFile;
  const { showToast } = useToast();
  const [history, setHistory] = useState(false);
  const [packLayouts, setPackLayouts] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const total = layoutIds.length + packIds.length;

  async function download() {
    setBusy(true);
    setError(null);
    try {
      const file = await api.exportFile({
        layout_ids: layoutIds, pack_ids: packIds, include_history: history, include_pack_layouts: packLayouts,
      });
      const name = file instanceof File && file.name ? file.name : "reports.zip";
      downloadBlob(file, name);
      showToast(text.exported(name));
      onClose();
    } catch (err) {
      setError(toErrorMessage(err, text.exportFailed));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title={text.exportTitle(total)} onClose={onClose}>
      <div className="stack">
        <FormActions
          error={error} onCancel={onClose} onSave={() => void download()} saveLabel={busy ? text.exporting : text.exportButton}
          saveDisabled={busy || total === 0} cancelDisabled={busy}
        />
        <p className="text-muted" style={{ margin: 0 }}>{text.exportNote}</p>
        <CheckboxField label={text.historyLabel} hint={text.historyHint} helpNotNeeded checked={history} onChange={setHistory} />
        {packIds.length > 0 && (
          <CheckboxField
            label={text.packLayoutsLabel} hint={text.packLayoutsHint} helpNotNeeded checked={packLayouts} onChange={setPackLayouts}
          />
        )}
      </div>
    </Modal>
  );
}
