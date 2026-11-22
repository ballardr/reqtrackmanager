/**
 * Module: modules/architecture/SymbolUploadDialog
 *
 * The dialog that uploads symbols to the library: one or more files at once, filed in a chosen folder (the one open on the
 * page by default).
 *
 * Responsibilities:
 * - Send the chosen files one after another through the same upload call as a single file, so each goes through the server's
 *   sanitiser alone and a refusal is shown beside its own file name; the others still upload.
 * - Show each file's outcome (uploaded or the server's refusal) and say in one toast how many were added.
 *
 * Design decisions:
 * - Files upload as soon as they are chosen, like the single-file control it replaces; the folder is chosen first.
 * - One request per file, not one request for all: a refusal, a name clash or a storage limit is then specific to a file, and a
 *   long upload can be followed file by file.
 * - A ZIP of an icon pack is not accepted (each file is checked on its own).
 */
import { useState } from "react";

import { FormActions } from "../../components/FormActions";
import { FormGrid } from "../../components/FormGrid";
import { UploadField } from "../../components/FormFields";
import { Modal } from "../../components/Modal";
import { TreeSelectField } from "../../components/TreeSelectField";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { symbolApi } from "./api";
import type { TypesScope } from "./ArchitectureTypesPanel";
import { folderSelectNodes } from "./folderTree";
import { ARCHITECTURE_HELP } from "./help";
import type { ArchitectureFolder } from "./types";

/** The outcome of one file. */
interface Outcome {
  file: string;
  /** `null` while pending or after success; the server's reason when refused. */
  refusal: string | null;
  done: boolean;
}

/**
 * @param scope The project or organisation whose library receives the files.
 * @param folders The owner's symbol folders to choose from.
 * @param defaultFolderId The folder open on the page, chosen to start with (or `null` for the top level).
 * @param converterAvailable Whether an EPS or PDF file is accepted (adds those to the file picker).
 * @param onClose Called when the dialog is closed; `uploaded` is how many symbols were added, so the page can read the list again.
 */
export function SymbolUploadDialog({
  scope, folders, defaultFolderId, converterAvailable, onClose,
}: {
  scope: TypesScope;
  folders: ArchitectureFolder[];
  defaultFolderId: string | null;
  converterAvailable: boolean;
  onClose: (uploaded: number) => void;
}) {
  const { showToast } = useToast();
  const [folderId, setFolderId] = useState<string | null>(defaultFolderId);
  const [outcomes, setOutcomes] = useState<Outcome[]>([]);
  const [busy, setBusy] = useState(false);
  const added = outcomes.filter((o) => o.done && o.refusal === null).length;

  async function upload(files: File[]) {
    setBusy(true);
    setOutcomes(files.map((f) => ({ file: f.name, refusal: null, done: false })));
    let stored = 0;
    for (const [index, file] of files.entries()) {
      let refusal: string | null = null;
      try {
        await (scope.kind === "project"
          ? symbolApi.projectUpload(scope.projectId, file, undefined, folderId)
          : symbolApi.orgUpload(scope.organizationId, file, undefined, folderId));
        stored += 1;
      } catch (err) {
        refusal = toErrorMessage(err, "Could not upload the symbol.");
      }
      setOutcomes((current) => current.map((o, i) => (i === index ? { ...o, refusal, done: true } : o)));
    }
    setBusy(false);
    showToast(stored === files.length
      ? `${stored === 1 ? "Symbol" : `${stored} symbols`} uploaded.`
      : `${stored} of ${files.length} symbols uploaded. The others were refused.`, stored === 0 ? "error" : undefined);
  }

  return (
    <Modal title="Upload symbols" onClose={() => onClose(added)} size="lg" dirty={false}>
      <div className="stack">
        <FormGrid minColumn="18rem">
          <TreeSelectField
            help={ARCHITECTURE_HELP.symbolUploadFolder} single searchable label="Folder" nodes={folderSelectNodes(folders)}
            value={folderId ? [folderId] : []} emptyLabel="Top level (no folder)" clearLabel="Top level (no folder)"
            onChange={([next]) => setFolderId(next ?? null)}
          />
          <UploadField
            id="architecture-symbol-upload" label="Files" help={ARCHITECTURE_HELP.symbolUploadFiles} disabled={busy}
            accept={converterAvailable ? ".svg,image/svg+xml,.eps,.pdf" : ".svg,image/svg+xml"}
            onSelect={(file) => void upload([file])} onSelectMany={(files) => void upload(files)}
          >
            Choose files
          </UploadField>
        </FormGrid>
        {outcomes.length > 0 && (
          <ul aria-label="Upload results" style={{ listStyle: "none", margin: 0, padding: 0 }} className="stack">
            {outcomes.map((o, index) => (
              <li key={`${o.file}:${index}`} style={{ overflowWrap: "anywhere" }}>
                <strong>{o.file}</strong>{" "}
                {!o.done ? <span className="text-muted">Uploading…</span>
                  : o.refusal === null ? <span>Uploaded.</span>
                    : <span role="alert" style={{ color: "var(--color-danger)" }}>{o.refusal}</span>}
              </li>
            ))}
          </ul>
        )}
        <FormActions onCancel={() => onClose(added)} onSave={() => onClose(added)} saveLabel="Done" saveDisabled={busy} cancelDisabled={busy} />
      </div>
    </Modal>
  );
}
