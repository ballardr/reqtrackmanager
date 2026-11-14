/**
 * Module: components/CommentThreadView
 *
 * The body of a pinned comment thread (the marker's pop-over, and the Comments list's expanded thread): the comments in
 * order, a reply box, Resolve or Reopen, editing and deleting one's own comment, and deleting the whole thread.
 *
 * Responsibilities:
 * - Render one thread from plain data (`RecordComment[]`, `RecordCommentPin`) and report each action through callbacks; it
 *   stores nothing and calls no API, so a story or a page supplies the behaviour.
 * - Offer an action only where the server says it is allowed (`can_edit`, `can_delete`, the pin's `can_delete`).
 *
 * Design decisions:
 * - Deleting a comment or a thread goes through the shared two-tier `ConfirmDialog` (tier one: recoverable only by
 *   writing it again), as every destructive action does.
 * - Text is rendered as text, never markup. Resolve and Reopen are open to anyone who can comment, as on the server.
 * - Actions are small icon buttons, each with an `aria-label` and a tooltip of the same text, so they do not crowd a
 *   pop-over. A comment's Edit and Delete appear on row hover or focus (`ItemRow revealActions`); the thread's own
 *   Resolve and Delete stay visible beside Reply. Save and Cancel keep their text: they commit or discard an edit.
 */
import { Check, Pencil, Trash2, Undo2 } from "lucide-react";
import { useState, type ReactNode } from "react";

import type { RecordComment, RecordCommentPin } from "../api/recordComments";
import { useStrings } from "../context/TerminologyContext";
import { AutoGrowTextarea } from "./AutoGrowTextarea";
import { ConfirmDialog } from "./ConfirmDialog";
import { ItemRow } from "./ItemRow";
import { Tooltip } from "./Tooltip";

/**
 * @param pin The thread's pin (its resolved state and what the viewer may do with it).
 * @param comments The thread's comments, oldest first.
 * @param canReply Whether the viewer may add to the thread (false for a read-only view).
 * @param onReply Adds a reply; resolves to true when it was stored.
 * @param onEdit Changes the viewer's own comment; resolves to true when stored.
 * @param onRemove Deletes one comment.
 * @param onResolve Resolves (true) or reopens (false) the thread.
 * @param onRemoveThread Deletes the whole thread.
 * @param error A message from the last failed change, shown above the reply box.
 */
export function CommentThreadView({
  pin, comments, canReply = true, onReply, onEdit, onRemove, onResolve, onRemoveThread, error,
}: {
  pin: RecordCommentPin;
  comments: RecordComment[];
  canReply?: boolean;
  onReply?: (body: string) => Promise<boolean>;
  onEdit?: (commentId: string, body: string) => Promise<boolean>;
  onRemove?: (commentId: string) => Promise<boolean>;
  onResolve?: (resolved: boolean) => Promise<boolean>;
  onRemoveThread?: () => Promise<boolean>;
  error?: string | null;
}) {
  const text = useStrings().canvasComments;
  const [reply, setReply] = useState("");
  const [editing, setEditing] = useState<{ id: string; body: string } | null>(null);
  const [confirm, setConfirm] = useState<{ kind: "comment"; id: string } | { kind: "thread" } | null>(null);
  const [busy, setBusy] = useState(false);

  async function post() {
    if (!onReply || !reply.trim()) return;
    setBusy(true);
    try {
      if (await onReply(reply)) setReply("");
    } finally {
      setBusy(false);
    }
  }

  async function saveEdit() {
    if (!onEdit || !editing || !editing.body.trim()) return;
    setBusy(true);
    try {
      if (await onEdit(editing.id, editing.body)) setEditing(null);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack" style={{ gap: "var(--space-2)" }}>
      {pin.resolved && (
        <p className="text-muted" style={{ margin: 0 }} role="status">
          {text.resolved}
          {pin.resolved_by_display_name ? ` · ${pin.resolved_by_display_name}` : ""}
        </p>
      )}
      {comments.map((c) => {
        const mayEdit = Boolean(c.can_edit && onEdit);
        const mayDelete = Boolean(c.can_delete && onRemove);
        return (
        <div key={c.id} className="comment-row stack" style={{ gap: "var(--space-1)" }}>
          <ItemRow
            revealActions
            actions={
              editing?.id !== c.id && (mayEdit || mayDelete) ? (
                <>
                  {mayEdit && (
                    <IconAction label={text.edit} onClick={() => setEditing({ id: c.id, body: c.body })}><Pencil /></IconAction>
                  )}
                  {mayDelete && (
                    <IconAction label={text.delete} onClick={() => setConfirm({ kind: "comment", id: c.id })}><Trash2 /></IconAction>
                  )}
                </>
              ) : undefined
            }
          >
            <div className="row" style={{ justifyContent: "space-between", gap: "var(--space-2)" }}>
              <span style={{ fontWeight: 600 }}>{c.author_display_name}</span>
              <span className="text-muted" style={{ fontSize: "0.8rem" }}>
                {new Date(c.created_at).toLocaleString()}
                {c.edited_at ? ` ${text.edited}` : ""}
              </span>
            </div>
          </ItemRow>
          {editing?.id === c.id ? (
            <div className="stack" style={{ gap: "var(--space-1)" }}>
              <AutoGrowTextarea rows={2} value={editing.body} onChange={(body) => setEditing({ id: c.id, body })} aria-label={text.edit} />
              <div className="row">
                <button type="button" className="btn btn-sm btn-primary" disabled={busy || !editing.body.trim()} onClick={() => void saveEdit()}>
                  {text.save}
                </button>
                <button type="button" className="btn btn-sm" onClick={() => setEditing(null)}>{text.cancel}</button>
              </div>
            </div>
          ) : (
            <div style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{c.body}</div>
          )}
        </div>
        );
      })}
      {error && <p role="alert" style={{ color: "var(--color-danger)", margin: 0 }}>{error}</p>}
      {canReply && onReply && (
        <div className="stack" style={{ gap: "var(--space-1)" }}>
          <AutoGrowTextarea rows={2} value={reply} onChange={setReply} placeholder={text.replyPlaceholder} aria-label={text.reply} />
          <div className="row" style={{ gap: "var(--space-2)", flexWrap: "wrap" }}>
            <button type="button" className="btn btn-sm btn-primary" disabled={busy || !reply.trim()} onClick={() => void post()}>
              {text.reply}
            </button>
            {onResolve && (
              <IconAction label={pin.resolved ? text.reopen : text.resolve} disabled={busy} onClick={() => void onResolve(!pin.resolved)}>
                {pin.resolved ? <Undo2 /> : <Check />}
              </IconAction>
            )}
            {pin.can_delete && onRemoveThread && (
              <IconAction label={text.deleteThread} onClick={() => setConfirm({ kind: "thread" })}><Trash2 /></IconAction>
            )}
          </div>
        </div>
      )}
      {confirm && (
        <ConfirmDialog
          title={confirm.kind === "thread" ? text.deleteThread : text.delete}
          message={confirm.kind === "thread" ? "The whole thread and its replies will be deleted." : "This comment will be deleted."}
          confirmLabel={confirm.kind === "thread" ? text.deleteThread : text.delete}
          onCancel={() => setConfirm(null)}
          onConfirm={() => {
            const chosen = confirm;
            setConfirm(null);
            if (chosen.kind === "thread") void onRemoveThread?.();
            else void onRemove?.(chosen.id);
          }}
        />
      )}
    </div>
  );
}

/**
 * A small icon-only button named by its label, which is also its tooltip (style guide "Pattern: help on interactive elements").
 *
 * @param label The action's name: the button's `aria-label` and the tooltip text.
 * @param onClick Called when the button is pressed.
 * @param disabled Whether the button is unavailable.
 * @param children The icon.
 */
function IconAction({ label, onClick, disabled, children }: { label: string; onClick: () => void; disabled?: boolean; children: ReactNode }) {
  return (
    <Tooltip label={label}>
      <button type="button" className="btn btn-sm btn-icon" aria-label={label} disabled={disabled} onClick={onClick}>{children}</button>
    </Tooltip>
  );
}
