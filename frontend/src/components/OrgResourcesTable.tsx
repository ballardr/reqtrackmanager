/**
 * Module: components/OrgResourcesTable
 *
 * The table of an organisation's shared resources on its Files page.
 *
 * Responsibilities:
 * - List each resource with a preview and download link, the uploader, the upload time (shown in local time), the size
 *   and the number of {requirements} that link it.
 * - Offer Delete on a row only when `canManage` (the server's answer), behind a confirmation that names the links
 *   removed with the file; a resource with links asks for its file name to be typed (Tier 2), one without asks plainly.
 *
 * Design decisions: read-only for everyone else, so a member sees the same list without the Actions column.
 * External dependencies: `FileThumbnail`, `FileDetailsToggle`, `ConfirmDialog`.
 */
import { Trash2 } from "lucide-react";
import { useState } from "react";

import { fileUrl } from "../api/client";
import type { OrgResource } from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { formatFileSize } from "../utils/formatFileSize";
import { ConfirmDialog } from "./ConfirmDialog";
import { FileDetailsToggle } from "./FileDetailsPanel";
import { FileThumbnail } from "./FileThumbnail";

/**
 * @param resources The rows to draw.
 * @param canManage Whether the person may delete (the server decides).
 * @param onDelete Deletes one resource by file id; resolves when the list has reloaded.
 */
export function OrgResourcesTable({
  resources, canManage, onDelete,
}: {
  resources: OrgResource[];
  canManage: boolean;
  onDelete: (fileId: string) => Promise<void>;
}) {
  const strings = useStrings();
  const [pending, setPending] = useState<OrgResource | null>(null);

  return (
    <div className="card" style={{ overflowX: "auto" }}>
      <table>
        <thead>
          <tr>
            <th>{strings.files.columnFilename}</th>
            <th>{strings.files.columnUploadedBy}</th>
            <th>{strings.files.columnUploadedAt}</th>
            <th>{strings.files.columnSize}</th>
            <th>{strings.files.resources.columnLinked}</th>
            {canManage && <th><span className="sr-only">{strings.files.resources.columnActions}</span></th>}
          </tr>
        </thead>
        <tbody>
          {resources.map((r) => (
            <tr key={r.id}>
              <td>
                <span className="row" style={{ gap: "var(--space-2)", flexWrap: "nowrap" }}>
                  <FileThumbnail file={r} />
                  <a href={fileUrl(r.id)} target="_blank" rel="noreferrer" style={{ overflowWrap: "anywhere" }}>{r.filename}</a>
                  <FileDetailsToggle file={r} />
                </span>
              </td>
              <td className="text-muted">{r.uploaded_by_display_name}</td>
              <td className="text-muted">{new Date(r.created_at).toLocaleString()}</td>
              <td className="text-muted">{formatFileSize(r.size_bytes)}</td>
              <td className="text-muted">{r.link_count}</td>
              {canManage && (
                <td>
                  <button
                    type="button"
                    className="btn btn-danger"
                    title={strings.files.resources.deleteLabel(r.filename)}
                    aria-label={strings.files.resources.deleteLabel(r.filename)}
                    onClick={() => setPending(r)}
                  >
                    <Trash2 size={14} />
                  </button>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
      {pending && (
        <ConfirmDialog
          title={strings.files.resources.deleteTitle(pending.filename)}
          message={strings.files.resources.deleteMessage(pending.link_count)}
          confirmLabel={strings.files.resources.deleteConfirm}
          requireTypedText={pending.link_count > 0 ? pending.filename : undefined}
          onCancel={() => setPending(null)}
          onConfirm={() => {
            const target = pending;
            setPending(null);
            void onDelete(target.id);
          }}
        />
      )}
    </div>
  );
}
