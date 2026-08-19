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
 */
import { Trash2 } from "lucide-react";

import { fileUrl } from "../api/client";
import type { FileAsset } from "../api/types";

export function FileAttachmentList({
  files,
  onUpload,
  onRemove,
  disabled = false,
  emptyHint,
}: {
  files: FileAsset[];
  onUpload?: (file: File) => Promise<void>;
  onRemove?: (fileId: string) => Promise<void>;
  disabled?: boolean;
  emptyHint?: string;
}) {
  return (
    <div className="stack">
      {files.map((f) => (
        <div key={f.id} className="row" style={{ justifyContent: "space-between" }}>
          <a href={fileUrl(f.id)} target="_blank" rel="noreferrer">
            {f.filename}
          </a>
          {onRemove && !disabled && (
            <button
              className="btn btn-danger"
              title={`Remove ${f.filename}`}
              aria-label={`Remove ${f.filename}`}
              onClick={() => onRemove(f.id)}
            >
              <Trash2 size={14} />
            </button>
          )}
        </div>
      ))}
      {disabled ? (
        emptyHint && (
          <p className="text-muted" style={{ margin: 0, fontSize: "0.85rem" }}>
            {emptyHint}
          </p>
        )
      ) : (
        onUpload && (
          <input type="file" onChange={(e) => e.target.files?.[0] && onUpload(e.target.files[0])} />
        )
      )}
    </div>
  );
}
