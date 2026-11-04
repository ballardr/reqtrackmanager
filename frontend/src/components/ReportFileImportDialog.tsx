/**
 * Module: components/ReportFileImportDialog
 *
 * The dialog that imports a report file (made by Export as file) as the project's or organisation's own layouts and
 * packs: choose the file and how to settle a name already used, preview what would happen, then import.
 *
 * Responsibilities:
 * - Preview first (a dry run) and list each item with its outcome (import, import under a new name, skip, cannot be
 *   imported), its versions and its warnings, then import for real; changing the file or the name rule discards a
 *   preview, so what is applied is always what was shown.
 * - After the import, say what was created or left out.
 *
 * Design decisions: the server decides everything (names, validity, warnings), the dialog only shows it, so the preview
 * and the import cannot disagree. Nothing can be replaced, so there is no replace option. Follows the form header
 * pattern (`FormActions` in the dialog header) and the field help and required-field patterns.
 */
import { useState } from "react";

import {
  FILE_ACTION_LABEL, FILE_CONFLICT_LABEL, FILE_KIND_LABEL, type FileConflict, type FileImportResult, type FileItemResult, type ReportFileApi,
} from "../api/reportFile";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { Badge } from "./Badge";
import { FileField } from "./FormFields";
import { FormActions } from "./FormActions";
import { ResultActions } from "./ResultActions";
import { LabeledSelect } from "./LabeledSelect";
import { Modal } from "./Modal";

/**
 * @param api The calls, bound to the organisation or project the file is imported into.
 * @param onClose Called by the close mark and OK.
 * @param onImported Called once an import has been applied, so the list behind can reload.
 */
export function ReportFileImportDialog({
  api, onClose, onImported,
}: { api: ReportFileApi; onClose: () => void; onImported?: () => void }) {
  const strings = useStrings();
  const text = strings.reportFile;
  const { showToast } = useToast();
  const [file, setFile] = useState<File | null>(null);
  const [conflict, setConflict] = useState<FileConflict>("rename");
  const [plan, setPlan] = useState<FileImportResult | null>(null);
  const [result, setResult] = useState<FileImportResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const doing = plan?.items.filter((i) => i.action === "create" || i.action === "rename").length ?? 0;

  /** Changing what was previewed throws the preview away, so an import always matches what was shown. */
  const change = <T,>(set: (value: T) => void) => (value: T) => {
    set(value);
    setPlan(null);
    setError(null);
  };

  async function run(dryRun: boolean) {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const done = await api.importFile(file, { onConflict: conflict, dryRun });
      if (dryRun) {
        setPlan(done);
        return;
      }
      const created = done.items.filter((i) => i.action === "create" || i.action === "rename").length;
      setResult(done);
      showToast(text.toast(created));
      onImported?.();
    } catch (err) {
      setError(toErrorMessage(err, text.failed));
    } finally {
      setBusy(false);
    }
  }

  if (result) {
    const created = result.items.filter((i) => i.action === "create" || i.action === "rename").length;
    const left = result.items.length - created;
    return (
      <Modal title={text.importTitle} onClose={onClose}>
        <div className="stack">
          <ResultActions onOk={onClose} />
          <p role="status" style={{ margin: 0 }}>{text.done(created)}{left > 0 && ` ${text.doneLeft(left)}`}</p>
          <ItemList items={result.items} />
          {result.warnings.map((warning) => <p key={warning} className="text-muted" style={{ margin: 0 }}>{warning}</p>)}
        </div>
      </Modal>
    );
  }

  return (
    <Modal title={text.importTitle} onClose={onClose} size="lg">
      <div className="stack">
        <FormActions
          error={error}
          onCancel={onClose}
          onSave={() => void run(plan === null)}
          saveLabel={plan === null ? (busy ? text.previewing : text.previewButton) : text.importButton(doing)}
          saveDisabled={busy || file === null || (plan !== null && doing === 0)}
          cancelDisabled={busy}
        />
        <p className="text-muted" style={{ margin: 0 }}>{text.importNote}</p>
        <FileField required helpNotNeeded label={text.fileLabel} hint={text.fileHint} accept=".zip,application/zip" onChange={change(setFile)} />
        <LabeledSelect
          label={text.conflictLabel} help={strings.help.reportFileConflict} value={conflict} placeholder={null}
          onChange={change((value: string) => setConflict(value as FileConflict))}
          options={(Object.keys(FILE_CONFLICT_LABEL) as FileConflict[]).map((key) => ({ value: key, label: FILE_CONFLICT_LABEL[key] }))}
        />
        {plan && (
          <>
            {plan.items.length === 0 && <p className="text-muted" style={{ margin: 0 }}>{text.nothingToDo}</p>}
            <ItemList items={plan.items} />
            {plan.warnings.map((warning) => <p key={warning} className="text-muted" style={{ margin: 0 }}>{warning}</p>)}
          </>
        )}
      </div>
    </Modal>
  );
}

/** The items of a plan or result, one per line, with the outcome, the versions and any warnings. */
function ItemList({ items }: { items: FileItemResult[] }) {
  const text = useStrings().reportFile;
  return (
    <ul className="stack" style={{ listStyle: "none", margin: 0, padding: 0, gap: "var(--space-2)" }} aria-label={text.headingItems}>
      {items.map((item) => (
        <li key={`${item.kind}:${item.name}`} className="stack" style={{ gap: 0 }}>
          <span className="row" style={{ gap: "var(--space-2)", alignItems: "center" }}>
            <Badge>{FILE_KIND_LABEL[item.kind]}</Badge>
            <strong>{item.action === "rename" ? text.arrow(item.name, item.new_name) : item.name}</strong>
            <span className="text-muted">{FILE_ACTION_LABEL[item.action]}</span>
            <span className="text-muted">{text.versions(item.versions)}</span>
          </span>
          {item.warnings.map((warning) => (
            <span key={warning} className="text-muted" style={{ fontSize: "0.85rem" }}>{warning}</span>
          ))}
        </li>
      ))}
    </ul>
  );
}
