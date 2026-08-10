import { Heart, Paperclip, Pencil, X } from "lucide-react";
import { useState } from "react";

import { fileUrl } from "../api/client";
import type { Comment } from "../api/types";
import { t } from "../i18n/strings";

const strings = t();

/**
 * Discussion thread shared by requirement and change-request detail pages
 * (mockup: author name, timestamp, and a heart reaction count per comment).
 *
 * Attachments are only ever added while composing a new comment or editing
 * your own existing one — never as a standalone action against an
 * already-posted comment — matching the backend's author-only enforcement
 * on the underlying upload/remove endpoints. A comment shows "(edited)"
 * once `edited_at` is set; only the comment's own author sees the Edit
 * control at all (`currentUserId`).
 */
export function CommentThread({
  comments,
  onPost,
  onToggleReaction,
  onUploadAttachment,
  onRemoveAttachment,
  onEdit,
  currentUserId,
}: {
  comments: Comment[];
  onPost: (body: string) => Promise<Comment>;
  onToggleReaction: (commentId: string, reacted: boolean) => Promise<void>;
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
  const [editPendingFiles, setEditPendingFiles] = useState<File[]>([]);
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

  function startEdit(comment: Comment) {
    setEditingId(comment.id);
    setEditBody(comment.body);
    setEditPendingFiles([]);
  }

  function cancelEdit() {
    setEditingId(null);
    setEditBody("");
    setEditPendingFiles([]);
  }

  async function saveEdit(commentId: string) {
    if (!editBody.trim()) return;
    setSavingEdit(true);
    try {
      if (onEdit) await onEdit(commentId, editBody);
      for (const file of editPendingFiles) {
        if (onUploadAttachment) await onUploadAttachment(commentId, file);
      }
      cancelEdit();
    } finally {
      setSavingEdit(false);
    }
  }

  return (
    <div className="stack">
      {comments.map((c) => {
        const isEditing = editingId === c.id;
        return (
          <div key={c.id} className="card stack" style={{ gap: "0.35rem" }}>
            <div className="row" style={{ justifyContent: "space-between" }}>
              <span style={{ fontWeight: 600 }}>{c.author_display_name}</span>
              <span className="text-muted" style={{ fontSize: "0.8rem" }}>
                {new Date(c.created_at).toLocaleString()}
                {c.edited_at && ` ${strings.requirements.editedLabel}`}
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
                        <button
                          className="btn"
                          style={{ padding: "0.1rem", border: "none" }}
                          title={strings.requirements.removeAttachment}
                          aria-label={strings.requirements.removeAttachment}
                          onClick={() => onRemoveAttachment && onRemoveAttachment(c.id, a.id)}
                        >
                          <X size={12} />
                        </button>
                      </span>
                    ))}
                  </div>
                )}
                {editPendingFiles.length > 0 && (
                  <div className="row" style={{ gap: "0.6rem", flexWrap: "wrap" }}>
                    {editPendingFiles.map((f, idx) => (
                      <span key={idx} className="row badge" style={{ gap: "0.25rem" }}>
                        {f.name}
                        <button
                          className="btn"
                          style={{ padding: "0.1rem", border: "none" }}
                          onClick={() => setEditPendingFiles((files) => files.filter((_, i) => i !== idx))}
                        >
                          <X size={12} />
                        </button>
                      </span>
                    ))}
                  </div>
                )}
                <div className="row">
                  {onUploadAttachment && (
                    <label className="btn" style={{ cursor: "pointer" }} title={strings.requirements.attachFile}>
                      <Paperclip size={14} />
                      <input
                        type="file"
                        style={{ display: "none" }}
                        onChange={(e) => {
                          const file = e.target.files?.[0];
                          if (file) setEditPendingFiles((files) => [...files, file]);
                          e.target.value = "";
                        }}
                      />
                    </label>
                  )}
                  <button className="btn btn-primary" disabled={savingEdit || !editBody.trim()} onClick={() => saveEdit(c.id)}>
                    {strings.requirements.saveComment}
                  </button>
                  <button className="btn" onClick={cancelEdit}>
                    {strings.requirements.cancelEdit}
                  </button>
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
                <div className="row">
                  <button
                    className="btn"
                    title={strings.requirements.reactionToggle}
                    aria-label={strings.requirements.reactionToggle}
                    aria-pressed={c.reacted_by_me}
                    onClick={() => onToggleReaction(c.id, c.reacted_by_me)}
                  >
                    <Heart size={14} fill={c.reacted_by_me ? "currentColor" : "none"} />
                    {c.reaction_count > 0 ? c.reaction_count : ""}
                  </button>
                  {onEdit && currentUserId === c.author_id && (
                    <button className="btn" title={strings.requirements.editComment} onClick={() => startEdit(c)}>
                      <Pencil size={14} />
                    </button>
                  )}
                </div>
              </>
            )}
          </div>
        );
      })}
      <div className="stack">
        <div className="row">
          <input
            className="input"
            placeholder={strings.requirements.addComment}
            value={newComment}
            onChange={(e) => setNewComment(e.target.value)}
          />
          {onUploadAttachment && (
            <label className="btn" style={{ cursor: "pointer" }} title={strings.requirements.attachFile}>
              <Paperclip size={14} />
              <input
                type="file"
                style={{ display: "none" }}
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) setPendingFiles((files) => [...files, file]);
                  e.target.value = "";
                }}
              />
            </label>
          )}
          <button className="btn" disabled={posting || !newComment.trim()} onClick={submit}>
            {strings.requirements.addComment}
          </button>
        </div>
        {pendingFiles.length > 0 && (
          <div className="row" style={{ gap: "0.6rem", flexWrap: "wrap" }}>
            {pendingFiles.map((f, idx) => (
              <span key={idx} className="row badge" style={{ gap: "0.25rem" }}>
                {f.name}
                <button
                  className="btn"
                  style={{ padding: "0.1rem", border: "none" }}
                  onClick={() => setPendingFiles((files) => files.filter((_, i) => i !== idx))}
                >
                  <X size={12} />
                </button>
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
