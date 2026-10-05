/**
 * Module: modules/stakeholders/RecordLifecycleControls
 *
 * The Activate / Retire / Reactivate / Archive buttons and their confirm
 * dialogs, shared by every record kind in this module (all have the same
 * approval-free `draft → active → retired` lifecycle and soft archive).
 * Each action sits behind a tier-1 `ConfirmDialog` (docs/ux-style-guide.md,
 * "confirmation, in two tiers"); activate/retire take an optional comment.
 *
 * Every button always renders regardless of role: the backend enforces the
 * owner role and a 403 surfaces as a toast through the caller's handlers.
 */
import { useState } from "react";

import { ConfirmDialog } from "../../components/ConfirmDialog";

export type LifecycleAction = "activate" | "retire";

export function RecordLifecycleControls({
  noun,
  status,
  isArchived,
  activateBody,
  retireBody,
  archiveBody,
  onTransition,
  onArchiveToggle,
  children,
}: {
  /** Singular noun for dialog titles, e.g. "Persona". */
  noun: string;
  status: "draft" | "active" | "retired";
  isArchived: boolean;
  activateBody: string;
  retireBody: string;
  /** Explains what archiving does; the unarchive text is fixed. */
  archiveBody: string;
  onTransition: (action: LifecycleAction, comment: string) => Promise<void>;
  onArchiveToggle: () => Promise<void>;
  /** Extra buttons to render in the same row (e.g. Delete permanently). */
  children?: React.ReactNode;
}) {
  const [action, setAction] = useState<LifecycleAction | null>(null);
  const [comment, setComment] = useState("");
  const [archiveConfirm, setArchiveConfirm] = useState(false);

  const copy: Record<LifecycleAction, { title: string; body: string; confirmLabel: string }> = {
    activate: { title: `Activate this ${noun}?`, body: activateBody, confirmLabel: "Activate" },
    retire: { title: `Retire this ${noun}?`, body: retireBody, confirmLabel: "Retire" },
  };

  return (
    <>
      <div className="row" style={{ gap: "0.5rem", flexWrap: "wrap" }}>
        {status !== "active" && (
          <button className="btn btn-primary" onClick={() => setAction("activate")}>
            {status === "retired" ? "Reactivate" : "Activate"}
          </button>
        )}
        {status !== "retired" && <button className="btn btn-danger" onClick={() => setAction("retire")}>Retire</button>}
        <button className="btn" onClick={() => setArchiveConfirm(true)}>{isArchived ? "Unarchive" : "Archive"}</button>
        {children}
      </div>

      {action && (
        <ConfirmDialog
          title={copy[action].title}
          message={
            <span className="stack" style={{ gap: "0.5rem" }}>
              <span>{copy[action].body}</span>
              <label className="stack" style={{ gap: "0.25rem" }}>
                Comment
                <textarea
                  className="input" rows={2} aria-label="Transition comment"
                  value={comment} onChange={(e) => setComment(e.target.value)}
                />
              </label>
            </span>
          }
          confirmLabel={copy[action].confirmLabel}
          onConfirm={async () => {
            const chosen = action;
            const text = comment;
            setAction(null);
            setComment("");
            await onTransition(chosen, text);
          }}
          onCancel={() => { setAction(null); setComment(""); }}
        />
      )}

      {archiveConfirm && (
        <ConfirmDialog
          title={isArchived ? `Unarchive this ${noun}?` : `Archive this ${noun}?`}
          message={isArchived ? `This ${noun} will count as active again.` : archiveBody}
          confirmLabel={isArchived ? "Unarchive" : "Archive"}
          onConfirm={async () => {
            setArchiveConfirm(false);
            await onArchiveToggle();
          }}
          onCancel={() => setArchiveConfirm(false)}
        />
      )}
    </>
  );
}
