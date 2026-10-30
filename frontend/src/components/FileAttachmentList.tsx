/**
 * Module: components/FileAttachmentList
 *
 * Shared "list of files + upload/remove controls" block, extracted from the
 * pattern that used to live inline in `RequirementDetailPage.tsx`'s
 * Attachments card (C-M-02) so `ActionDetailPage.tsx` can reuse it for an
 * action's own direct file attachments without duplicating the markup.
 * Fully prop-driven, like `CommentThread` — no knowledge of which entity
 * (requirement, action, ...) it's attached to, or of the API path used to
 * upload/remove a file; the caller supplies those via `onUpload`/`onRemove`.
 *
 * `disabled` covers the requirement-specific "approved, use a change
 * request instead" lock (C-G-12) — actions have no such lock concept, so
 * callers there simply never pass it. When `disabled` is true and
 * `emptyHint` is provided, the hint is shown in place of the upload control
 * so the reason attachments can't be added right now is explained rather
 * than the control silently disappearing.
 *
 * A picture's row also carries an info button that shows its details (`FileDetailsToggle`) and a lock button that marks it
 * confidential, which keeps it out of reports (and nothing else). The list makes the call itself and remembers the answer
 * for the rows it shows, so every page that lists attachments has the mark without wiring; the server decides who may
 * change it and a refusal appears as a toast.
 */
import { Lock, Paperclip, Trash2 } from "lucide-react";
import { useState } from "react";

import { isPictureFile } from "../api/fileDetails";
import { setFileConfidential } from "../api/fileConfidential";
import { fileUrl } from "../api/client";
import type { FileAsset } from "../api/types";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { useStrings } from "../context/TerminologyContext";
import { Badge } from "./Badge";
import { FileDetailsToggle } from "./FileDetailsPanel";
import { FileUploadTrigger } from "./FileUploadTrigger";

export function FileAttachmentList({
  files,
  onUpload,
  onRemove,
  disabled = false,
  emptyHint,
  setConfidential = setFileConfidential,
}: {
  files: FileAsset[];
  onUpload?: (file: File) => Promise<void>;
  onRemove?: (fileId: string) => Promise<void>;
  disabled?: boolean;
  emptyHint?: string;
  /** Sets or clears a file's confidential mark (the live call by default). */
  setConfidential?: (fileId: string, confidential: boolean) => Promise<FileAsset>;
}) {
  const text = useStrings().fileConfidential;
  const { showToast } = useToast();
  const [marks, setMarks] = useState<Record<string, boolean>>({});
  const confidential = (f: FileAsset) => marks[f.id] ?? f.confidential;

  async function toggle(f: FileAsset) {
    const next = !confidential(f);
    try {
      const saved = await setConfidential(f.id, next);
      setMarks((prev) => ({ ...prev, [f.id]: saved.confidential }));
      showToast(saved.confidential ? text.marked(f.filename) : text.cleared(f.filename));
    } catch (err) {
      showToast(toErrorMessage(err, text.failed), "error");
    }
  }

  return (
    <div className="stack">
      {files.map((f) => (
        <div key={f.id} className="row" style={{ justifyContent: "space-between" }}>
          <span className="row" style={{ gap: "var(--space-2)", minWidth: 0 }}>
            <a href={fileUrl(f.id)} target="_blank" rel="noreferrer" style={{ overflowWrap: "anywhere" }}>
              {f.filename}
            </a>
            {confidential(f) && <Badge tone="warning" icon={<Lock size={12} aria-hidden="true" />}>{text.badge}</Badge>}
          </span>
          <div className="row" style={{ gap: "var(--space-1)" }}>
            <FileDetailsToggle file={f} />
            {isPictureFile(f) && (
              <button
                type="button" className="btn btn-sm btn-icon" aria-pressed={confidential(f)} onClick={() => void toggle(f)}
                aria-label={confidential(f) ? text.clear(f.filename) : text.mark(f.filename)}
                title={confidential(f) ? text.clear(f.filename) : text.mark(f.filename)}
              >
                <Lock aria-hidden="true" />
              </button>
            )}
            {onRemove && !disabled && (
              <button
                className="btn btn-danger"
                title={`Remove ${f.filename}`}
                aria-label={`Remove ${f.filename}`}
                onClick={() => onRemove(f.id)}
              >
                <Trash2 />
              </button>
            )}
          </div>
        </div>
      ))}
      {files.some(isPictureFile) && (
        <p className="text-muted" style={{ margin: 0, fontSize: "0.85rem" }}>
          {text.explain}
        </p>
      )}
      {disabled ? (
        emptyHint && (
          <p className="text-muted" style={{ margin: 0, fontSize: "0.85rem" }}>
            {emptyHint}
          </p>
        )
      ) : (
        onUpload && (
          <FileUploadTrigger onSelect={onUpload} title="Attach a file" aria-label="Attach a file">
            <Paperclip size={14} /> Attach a file
          </FileUploadTrigger>
        )
      )}
    </div>
  );
}
