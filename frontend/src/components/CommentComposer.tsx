/**
 * Module: components/CommentComposer
 *
 * The box for writing a new comment on a canvas (the body of the new-comment marker's pop-over): a growing text area with
 * Comment and Cancel, and the last failure's message. It stores nothing; the caller's `onPost` does.
 */
import { useState } from "react";

import { useStrings } from "../context/TerminologyContext";
import { AutoGrowTextarea } from "./AutoGrowTextarea";

/**
 * @param onPost Stores the comment; resolves to true when it was stored.
 * @param onCancel Closes the composer without storing.
 * @param error The message from the last failed attempt, or null.
 */
export function CommentComposer({ onPost, onCancel, error }: { onPost: (body: string) => Promise<boolean>; onCancel: () => void; error: string | null }) {
  const text = useStrings().canvasComments;
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  async function post() {
    if (!body.trim()) return;
    setBusy(true);
    try {
      await onPost(body);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="stack" style={{ gap: "var(--space-2)" }}>
      <AutoGrowTextarea rows={3} value={body} onChange={setBody} placeholder={text.commentPlaceholder} aria-label={text.composerTitle} autoFocus />
      {error && <p role="alert" style={{ color: "var(--color-danger)", margin: 0 }}>{error}</p>}
      <div className="row">
        <button type="button" className="btn btn-primary" disabled={busy || !body.trim()} onClick={() => void post()}>{text.post}</button>
        <button type="button" className="btn" onClick={onCancel}>{text.cancel}</button>
      </div>
    </div>
  );
}
