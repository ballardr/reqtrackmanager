/**
 * Module: components/ArtefactCommentsSection
 *
 * The shared comment thread for module artefacts whose comments have no reaction mechanism (Strategy, Future
 * State, Pain Point, Decision, Persona ...). Not `CommentThread`, whose mandatory `onToggleReaction` assumes
 * heart reactions these tables lack.
 *
 * Generic over the comment shape: any row structurally satisfying `ArtefactComment` works. Attachment upload,
 * remove and edit are opt-in through callbacks; edit only on the current user's own comments. `renderMeta` adds a
 * caller line under a comment's header; `onPost` may resolve to nothing when the caller reloads its own list.
 *
 * It is one `DetailCard` ("Comments"); each comment is a flat row (`.comment-row`), because cards never nest.
 */
import { Paperclip, Pencil } from "lucide-react";
import { useState, type ReactNode } from "react";

import { FileDetailsToggle } from "./FileDetailsPanel";
import { fileUrl } from "../api/client";
import type { FileAsset } from "../api/types";
import { DetailCard } from "./DetailCard";
import { FileUploadTrigger } from "./FileUploadTrigger";
import { ItemRow } from "./ItemRow";
import { MarkdownEditor } from "./MarkdownEditor";
import { MarkdownView } from "./MarkdownView";
import { RemovableChip } from "./RemovableChip";
import { withDetailRank } from "./detailCardOrder";

/** The structural shape of a comment this thread can render. */
export interface ArtefactComment {
  id: string;
  author_id: string | null;
  author_display_name: string;
  body: string;
  created_at: string;
  edited_at: string | null;
  attachments: FileAsset[];
}

export function ArtefactCommentsSection<T extends ArtefactComment>({
  comments,
  onPost,
  onUploadAttachment,
  onRemoveAttachment,
  onEdit,
  currentUserId,
  renderMeta,
}: {
  comments: T[];
  onPost: (body: string) => Promise<T | void>;
  onUploadAttachment?: (commentId: string, file: File) => Promise<void>;
  onRemoveAttachment?: (commentId: string, fileId: string) => Promise<void>;
  onEdit?: (commentId: string, body: string) => Promise<void>;
  currentUserId?: string;
  /** Extra content under each comment's header (chips, actions); nothing by default. */
  renderMeta?: (comment: T) => ReactNode;
}) {
  const [newComment, setNewComment] = useState("");
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);
  const [posting, setPosting] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editBody, setEditBody] = useState("");
  const [savingEdit, setSavingEdit] = useState(false);

  async function submit() {
    if (!newComment.trim()) return;
    setPosting(true);
    try {
      const comment = await onPost(newComment);
      for (const file of pendingFiles) {
        if (onUploadAttachment && comment) await onUploadAttachment(comment.id, file);
      }
      setNewComment("");
      setPendingFiles([]);
    } finally {
      setPosting(false);
    }
  }

  function startEdit(comment: T) {
    setEditingId(comment.id);
    setEditBody(comment.body);
  }

  async function saveEdit(commentId: string) {
    if (!editBody.trim()) return;
    setSavingEdit(true);
    try {
      if (onEdit) await onEdit(commentId, editBody);
      setEditingId(null);
      setEditBody("");
    } finally {
      setSavingEdit(false);
    }
  }

  return (
    <DetailCard heading="Comments">
      {comments.length === 0 && <p className="text-muted" style={{ margin: 0 }}>No comments yet.</p>}
      {comments.map((c) => {
        const isEditing = editingId === c.id;
        return (
          <div key={c.id} className="comment-row stack" style={{ gap: "var(--space-2)" }}>
            <div className="row" style={{ justifyContent: "space-between" }}>
              <span style={{ fontWeight: 600 }}>{c.author_display_name}</span>
              <span className="text-muted" style={{ fontSize: "0.8rem" }}>
                {new Date(c.created_at).toLocaleString()}
                {c.edited_at && " (edited)"}
              </span>
            </div>
            {renderMeta?.(c)}
            {isEditing ? (
              <div className="stack" style={{ gap: "var(--space-2)" }}>
                <MarkdownEditor simple value={editBody} onChange={setEditBody} ariaLabel="Edit comment" />
                {c.attachments.length > 0 && (
                  <div className="row" style={{ gap: "0.6rem", flexWrap: "wrap" }}>
                    {c.attachments.map((a) => (
                      <RemovableChip key={a.id} label={a.filename} removeLabel={`Remove ${a.filename}`} onRemove={onRemoveAttachment && (() => onRemoveAttachment(c.id, a.id))} />
                    ))}
                  </div>
                )}
                <div className="row">
                  <button className="btn btn-primary" disabled={savingEdit || !editBody.trim()} onClick={() => saveEdit(c.id)}>
                    Save
                  </button>
                  <button className="btn" onClick={() => setEditingId(null)}>Cancel</button>
                </div>
              </div>
            ) : (
              <>
                <MarkdownView text={c.body} />
                {c.attachments.length > 0 && (
                  <div className="row" style={{ gap: "0.6rem", flexWrap: "wrap" }}>
                    {c.attachments.map((a) => (
                      <span key={a.id} className="row" style={{ gap: "var(--space-1)" }}>
                        <a href={fileUrl(a.id)} target="_blank" rel="noreferrer" className="row" style={{ gap: "var(--space-1)" }}>
                          <Paperclip size={12} /> {a.filename}
                        </a>
                        <FileDetailsToggle file={a} />
                      </span>
                    ))}
                  </div>
                )}
                {onEdit && currentUserId === c.author_id && (
                  <button className="btn" title="Edit comment" aria-label="Edit comment" onClick={() => startEdit(c)}>
                    <Pencil />
                  </button>
                )}
              </>
            )}
          </div>
        );
      })}
      <div className="stack">
        <ItemRow
          actions={
            <>
              {onUploadAttachment && (
                <FileUploadTrigger
                  title="Attach a file"
                  aria-label="Attach a file"
                  onSelect={(file) => setPendingFiles((files) => [...files, file])}
                >
                  <Paperclip size={14} />
                </FileUploadTrigger>
              )}
              <button className="btn" disabled={posting || !newComment.trim()} onClick={submit}>Add comment</button>
            </>
          }
        >
          <MarkdownEditor
            simple rows={1} value={newComment} onChange={setNewComment} ariaLabel="Add a comment"
            textareaProps={{ placeholder: "Add a comment…" }}
          />
        </ItemRow>
        {pendingFiles.length > 0 && (
          <div className="row" style={{ gap: "0.6rem", flexWrap: "wrap" }}>
            {pendingFiles.map((f, idx) => (
              <RemovableChip key={idx} label={f.name} removeLabel={`Remove ${f.name}`} onRemove={() => setPendingFiles((files) => files.filter((_, i) => i !== idx))} />
            ))}
          </div>
        )}
      </div>
    </DetailCard>
  );
}

withDetailRank(ArtefactCommentsSection, "discussion");
