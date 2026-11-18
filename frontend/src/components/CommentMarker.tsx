/**
 * Module: components/CommentMarker
 *
 * The round pin a comment thread leaves on a canvas, with the pop-over that opens from it.
 *
 * Responsibilities:
 * - Draw a marker showing the author's initials and, once a thread has replies, a count; a resolved thread is outlined and
 *   muted, and a thread whose box or line has left the drawing carries a note.
 * - Open the shared `Popover` from the marker (an existing thread's body, or the composer for a new comment), anchored to it.
 *
 * Design decisions:
 * - Escape closes the open pop-over wherever focus is, because focus can leave it when a control disables itself.
 * - The marker is a real button (focusable, named with its author, count and state), so the canvas's comments are reachable
 *   without a pointer. The canvas keeps it one screen size at any zoom.
 * - Both pop-overs are the shared `Popover`; nothing here knows what record the comments belong to.
 */
import { useEffect, useRef, type ReactNode } from "react";

import { useStrings } from "../context/TerminologyContext";
import { initialsOf } from "../utils/initials";
import { Popover } from "./Popover";

/**
 * @param author The thread's first author, for the initials and the accessible name.
 * @param count How many comments the thread holds; a count shows only above one.
 * @param resolved Whether the thread is resolved.
 * @param detached Whether the thread's box or line is no longer on the drawing.
 * @param isNew True for the marker of a comment being written (no thread yet).
 * @param open Whether the pop-over is open.
 * @param title The pop-over's accessible title.
 * @param onToggle Opens or closes the pop-over (a click, Enter or Space).
 * @param onClose Closes the pop-over (Escape, a click outside).
 * @param children The pop-over body: a thread, or the composer.
 */
export function CommentMarker({
  author, count, resolved, detached, isNew = false, open, title, onToggle, onClose, children,
}: {
  author: string;
  count: number;
  resolved: boolean;
  detached: boolean;
  isNew?: boolean;
  open: boolean;
  title: string;
  onToggle: () => void;
  onClose: () => void;
  children: ReactNode;
}) {
  const text = useStrings().canvasComments;
  const anchor = useRef<HTMLButtonElement>(null);
  // Focus can leave the pop-over (a button disables itself after it is used), so Escape closes it from anywhere on the page.
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  const classes = ["comment-marker", resolved ? "comment-marker-resolved" : "", detached ? "comment-marker-detached" : "", isNew ? "comment-marker-new" : ""]
    .filter(Boolean).join(" ");
  return (
    <>
      <button
        ref={anchor} type="button" className={classes} aria-expanded={open}
        aria-label={isNew ? text.newMarkerAria : text.markerAria(author, count, resolved)}
        title={detached ? text.detached : undefined}
        onClick={onToggle}
      >
        <span aria-hidden="true">{isNew ? "+" : initialsOf(author)}</span>
        {count > 1 && <span className="comment-marker-count" aria-hidden="true">{count}</span>}
      </button>
      {open && (
        <Popover anchorRef={anchor} onClose={onClose} title={title} placement="side">
          {detached && <p className="text-muted" style={{ margin: 0 }}>{text.detached}</p>}
          {children}
        </Popover>
      )}
    </>
  );
}
