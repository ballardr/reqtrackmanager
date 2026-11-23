/**
 * Module: components/useLifecycleTransition
 *
 * The lifecycle of every record kind with the approval-free `draft -> active -> retired` states (Persona,
 * Stakeholder, Stakeholder Need), as the pieces `RecordHeader` draws: the lifecycle track (Draft and Active on the
 * main path, Retired as the branch end state), Activate as its Promote move, and Retire / Reactivate as rows of the
 * record's actions menu. Activate and Retire open a comment confirmation (`CommentConfirmDialog`); the comment is
 * optional. Archive and Delete are object actions (`useArchiveAction`).
 *
 * Design decisions: the moves always offer themselves whatever the role, because the backend enforces the owner role
 * and a 403 surfaces as a toast through the caller's handlers; `hidden` removes the moves for a record that cannot be
 * changed from the current page (an organisation record opened inside a project).
 *
 * External dependencies: `CommentConfirmDialog`, `lifecycleSteps`.
 */
import { useState, type ReactNode } from "react";

import type { ActionMenuItem } from "./ActionMenu";
import { CommentConfirmDialog } from "./CommentConfirmDialog";
import type { LifecycleTrackProps } from "./LifecycleTrack";
import { lifecycleSteps } from "./lifecycleSteps";

export type LifecycleAction = "activate" | "retire";
export type ApprovalFreeStatus = "draft" | "active" | "retired";

/**
 * @param noun Singular noun for dialog titles, e.g. "Persona".
 * @param status Current lifecycle state.
 * @param labels The type's `*_STATUS_LABEL` map.
 * @param descriptions The type's `*_STATUS_DESCRIPTION` map.
 * @param activateBody Explains what activating does.
 * @param retireBody Explains what retiring does.
 * @param onTransition Performs the transition with the optional comment.
 * @param hidden True when the record cannot be changed from this page: the track shows its state with no move.
 * @returns `lifecycle` for `RecordHeader`, `menuRows` for its `actions` and `dialog`, which the page renders anywhere
 *   inside its tree.
 */
export function useLifecycleTransition({
  noun, status, labels, descriptions, activateBody, retireBody, onTransition, hidden = false,
}: {
  noun: string;
  status: ApprovalFreeStatus;
  labels: Record<ApprovalFreeStatus, string>;
  descriptions: Record<ApprovalFreeStatus, string>;
  activateBody: string;
  retireBody: string;
  onTransition: (action: LifecycleAction, comment: string) => Promise<void>;
  hidden?: boolean;
}): { lifecycle: LifecycleTrackProps; menuRows: ActionMenuItem[]; dialog: ReactNode } {
  const [action, setAction] = useState<LifecycleAction | null>(null);

  const copy: Record<LifecycleAction, { title: string; body: string; confirmLabel: string }> = {
    activate: { title: `Activate this ${noun}?`, body: activateBody, confirmLabel: "Activate" },
    retire: { title: `Retire this ${noun}?`, body: retireBody, confirmLabel: "Retire" },
  };

  const lifecycle: LifecycleTrackProps = {
    steps: lifecycleSteps(["draft", "active"], labels, { descriptions }),
    current: status,
    offPath: { key: "retired", label: labels.retired, description: descriptions.retired },
    promote: !hidden && status === "draft" ? { to: "active", onPromote: () => setAction("activate") } : undefined,
  };

  const menuRows: ActionMenuItem[] = [];
  if (!hidden && status === "retired") menuRows.push({ label: "Reactivate", onSelect: () => setAction("activate") });
  if (!hidden && status !== "retired") menuRows.push({ label: "Retire", danger: true, onSelect: () => setAction("retire") });

  const dialog = action ? (
    <CommentConfirmDialog
      title={copy[action].title}
      intro={copy[action].body}
      ariaLabel="Transition comment"
      confirmLabel={copy[action].confirmLabel}
      onConfirm={async (comment) => {
        setAction(null);
        await onTransition(action, comment);
      }}
      onCancel={() => setAction(null)}
    />
  ) : null;

  return { lifecycle, menuRows, dialog };
}
