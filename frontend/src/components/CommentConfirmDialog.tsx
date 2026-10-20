/**
 * Module: components/CommentConfirmDialog
 *
 * The confirm dialog for a workflow step that carries a comment (approve, reject, send back, activate,
 * retire, withdraw): an explanation, one comment box and a confirm button. The comment is optional unless
 * `commentRequired` is set, in which case the box carries the shared required mark and confirming stays
 * disabled until it holds text. One component replaces the per-page copies, so a step's comment is typed the
 * same way everywhere and reaches the record's activity as `detail.comment`.
 *
 * Owns the comment text, so a caller holds no state for it and a reopened dialog always starts empty.
 *
 * External dependencies: `ConfirmDialog` (style guide, "confirmation, in two tiers"), `TextAreaField`.
 */
import { useState, type ReactNode } from "react";

import { ConfirmDialog } from "./ConfirmDialog";
import { TextAreaField } from "./FormFields";

/**
 * @param title Dialog title, e.g. "Approve this Decision?".
 * @param intro What the step does (shown above the comment box).
 * @param confirmLabel Label of the confirm button.
 * @param commentLabel Caption of the comment box; also its accessible name unless `ariaLabel` is given.
 * @param ariaLabel Accessible name when it must differ from the caption.
 * @param commentRequired True when the step cannot proceed without a comment.
 * @param onConfirm Called with the comment exactly as typed; the dialog does not close itself, the caller
 *   unmounts it (the usual `setOpen(false)` before running the transition).
 * @param onCancel Called when the dialog is dismissed.
 */
export function CommentConfirmDialog({
  title,
  intro,
  confirmLabel,
  commentLabel = "Comment",
  ariaLabel,
  commentRequired = false,
  onConfirm,
  onCancel,
}: {
  title: string;
  intro: ReactNode;
  confirmLabel: string;
  commentLabel?: string;
  ariaLabel?: string;
  commentRequired?: boolean;
  onConfirm: (comment: string) => void | Promise<void>;
  onCancel: () => void;
}) {
  const [comment, setComment] = useState("");
  return (
    <ConfirmDialog
      title={title}
      message={
        <span className="stack" style={{ gap: "0.5rem" }}>
          <span>{intro}</span>
          <TextAreaField
            helpNotNeeded
            required={commentRequired}
            label={commentLabel}
            ariaLabel={ariaLabel}
            value={comment}
            onChange={setComment}
            rows={2}
          />
        </span>
      }
      confirmLabel={confirmLabel}
      confirmDisabled={commentRequired && !comment.trim()}
      onConfirm={() => void onConfirm(comment)}
      onCancel={onCancel}
    />
  );
}
