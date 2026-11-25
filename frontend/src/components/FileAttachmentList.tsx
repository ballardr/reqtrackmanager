/**
 * Module: components/FileAttachmentList
 *
 * Shared "list of files + upload/remove controls" block for requirement and action attachments (C-M-02). It is
 * fully prop-driven, like `CommentThread`: it knows neither the entity nor the API path; the caller supplies
 * `onUpload`/`onRemove`.
 *
 * `disabled` covers the requirement lock "approved, use a change request instead" (C-G-12). When `disabled` and
 * `emptyHint` are both given, the hint replaces the upload control so the reason is explained.
 *
 * A picture's row also has an info button for its details (`FileDetailsToggle`) and a lock button marking it
 * confidential, which keeps it out of reports only. The list makes the call itself and remembers the answer for
 * its rows; the server decides who may change it and a refusal appears as a toast.
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
