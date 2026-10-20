/**
 * Module: components/RecordLifecycleControls
 *
 * The Activate / Retire (Reactivate) *transition* buttons and their confirm dialog,
 * for every record kind with the approval-free `draft -> active -> retired` lifecycle
 * (Persona, Stakeholder, Stakeholder Need). The buttons go in `RecordHeader`'s
 * `transitions` slot; Archive and Delete are object actions and live in its menu
 * (`useArchiveAction`). Activate and Retire take an optional comment.
 *
 * Every button always renders regardless of role: the backend enforces the owner
 * role and a 403 surfaces as a toast through the caller's handlers.
 *
 * External dependencies: `ConfirmDialog` (style guide, "confirmation, in two tiers").
 */
import { useState, type ReactNode } from "react";

import { ConfirmDialog } from "./ConfirmDialog";
import { TextAreaField } from "./FormFields";

export type LifecycleAction = "activate" | "retire";

/**
 * @param noun Singular noun for dialog titles, e.g. "Persona".
 * @param status Current lifecycle state.
 * @param activateBody Explains what activating does.
 * @param retireBody Explains what retiring does.
 * @param onTransition Performs the transition with the optional comment.
 */
export function RecordLifecycleControls({
  noun,
  status,
  activateBody,
  retireBody,
  onTransition,
}: {
  noun: string;
  status: "draft" | "active" | "retired";
  activateBody: string;
  retireBody: string;
  onTransition: (action: LifecycleAction, comment: string) => Promise<void>;
}) {
  const [action, setAction] = useState<LifecycleAction | null>(null);
  const [comment, setComment] = useState("");

  const copy: Record<LifecycleAction, { title: string; body: ReactNode; confirmLabel: string }> = {
    activate: { title: `Activate this ${noun}?`, body: activateBody, confirmLabel: "Activate" },
    retire: { title: `Retire this ${noun}?`, body: retireBody, confirmLabel: "Retire" },
  };

  return (
    <>
      {status !== "active" && (
        <button className="btn btn-primary" onClick={() => setAction("activate")}>
          {status === "retired" ? "Reactivate" : "Activate"}
        </button>
      )}
      {status !== "retired" && <button className="btn btn-danger" onClick={() => setAction("retire")}>Retire</button>}

      {action && (
        <ConfirmDialog
          title={copy[action].title}
          message={
            <span className="stack" style={{ gap: "0.5rem" }}>
              <span>{copy[action].body}</span>
              <TextAreaField helpNotNeeded
                label="Comment"
                ariaLabel="Transition comment"
                value={comment}
                onChange={setComment}
                rows={2}
              />
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
    </>
  );
}
