/**
 * Module: components/ArtefactCommentsSection
 *
 * The shared comment thread for module artefacts whose comments carry no
 * reaction mechanism (Strategy, Future State, Pain Point, Guiding Principle,
 * Open Question, Decision, Persona …) — deliberately not
 * `components/CommentThread.tsx`, whose mandatory `onToggleReaction` prop
 * assumes a heart-reaction these module-local comment tables don't have.
 *
 * Generic over the comment shape: any row structurally satisfying
 * `ArtefactComment` works, so a module's own `*Comment` type needs no
 * adapter. Extracted from the previously duplicated
 * `modules/context_strategy/ArtefactCommentsSection.tsx` and
 * `modules/decisions/DecisionCommentsSection.tsx` (docs/ux-style-guide.md's
 * one-component-per-pattern rule) so a third module (Stakeholders &
 * Personas) didn't add a third copy.
 *
 * Attachment upload/remove and edit are each opt-in via their callback; edit
 * is offered only on the current user's own comments.
 */
import { Paperclip, Pencil, Trash2 } from "lucide-react";
import { useState } from "react";

import { fileUrl } from "../api/client";
import type { FileAsset } from "../api/types";
import { FileUploadTrigger } from "./FileUploadTrigger";

/** The structural shape of a comment this thread can render. */
export interface ArtefactComment {
  id: string;
  author_id: string;
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
}: {
  comments: T[];
  onPost: (body: string) => Promise<T>;
  onUploadAttachment?: (commentId: string, file: File) => Promise<void>;
  onRemoveAttachment?: (commentId: string, fileId: string) => Promise<void>;
  onEdit?: (commentId: string, body: string) => Promise<void>;
  currentUserId?: string;
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
        if (onUploadAttachment) await onUploadAttachment(comment.id, file);
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
    <div className="stack">
      <h3 style={{ margin: 0, fontSize: "0.95rem" }}>Comments</h3>
      {comments.length === 0 && <p className="text-muted" style={{ margin: 0 }}>No comments yet.</p>}
      {comments.map((c) => {
        const isEditing = editingId === c.id;
        return (
          <div key={c.id} className="card stack" style={{ gap: "0.35rem" }}>
            <div className="row" style={{ justifyContent: "space-between" }}>
              <span style={{ fontWeight: 600 }}>{c.author_display_name}</span>
              <span className="text-muted" style={{ fontSize: "0.8rem" }}>
                {new Date(c.created_at).toLocaleString()}
                {c.edited_at && " (edited)"}
              </span>
            </div>
            {isEditing ? (
              <div className="stack" style={{ gap: "0.4rem" }}>
                <textarea className="input" rows={2} value={editBody} onChange={(e) => setEditBody(e.target.value)} />
                {c.attachments.length > 0 && (
                  <div className="row" style={{ gap: "0.6rem", flexWrap: "wrap" }}>
                    {c.attachments.map((a) => (
                      <span key={a.id} className="row badge" style={{ gap: "0.25rem" }}>
                        {a.filename}
                        {onRemoveAttachment && (
                          <button
                            className="btn"
                            style={{ padding: "0.1rem", border: "none" }}
                            title={`Remove ${a.filename}`}
                            aria-label={`Remove ${a.filename}`}
                            onClick={() => onRemoveAttachment(c.id, a.id)}
                          >
                            <Trash2 size={12} />
                          </button>
                        )}
                      </span>
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
                <div>{c.body}</div>
                {c.attachments.length > 0 && (
                  <div className="row" style={{ gap: "0.6rem", flexWrap: "wrap" }}>
                    {c.attachments.map((a) => (
                      <a key={a.id} href={fileUrl(a.id)} target="_blank" rel="noreferrer" className="row" style={{ gap: "0.25rem" }}>
                        <Paperclip size={12} /> {a.filename}
                      </a>
                    ))}
                  </div>
                )}
                {onEdit && currentUserId === c.author_id && (
                  <button className="btn" title="Edit comment" aria-label="Edit comment" onClick={() => startEdit(c)}>
                    <Pencil size={14} />
                  </button>
                )}
              </>
            )}
          </div>
        );
      })}
      <div className="stack">
        <div className="row">
          <input
            className="input"
            placeholder="Add a comment…"
            aria-label="Add a comment"
            value={newComment}
            onChange={(e) => setNewComment(e.target.value)}
          />
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
        </div>
        {pendingFiles.length > 0 && (
          <div className="row" style={{ gap: "0.6rem", flexWrap: "wrap" }}>
            {pendingFiles.map((f, idx) => (
              <span key={idx} className="row badge" style={{ gap: "0.25rem" }}>
                {f.name}
                <button
                  className="btn"
                  style={{ padding: "0.1rem", border: "none" }}
                  title={`Remove ${f.name}`}
                  aria-label={`Remove ${f.name}`}
                  onClick={() => setPendingFiles((files) => files.filter((_, i) => i !== idx))}
                >
                  <Trash2 size={12} />
                </button>
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
