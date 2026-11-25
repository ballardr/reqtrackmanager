/**
 * Module: modules/architecture/architectureLifecycle
 *
 * The lifecycle of an element, a connection or a diagram as the pieces `RecordHeader` draws: the track (Draft,
 * Proposed and Active on the main path; Retired or Rejected as the one branch end state shown while it is current),
 * the forward move as Promote, and every other move as a row of the record's actions menu.
 *
 * Design decisions: the moves a record may make are the `allowed_status_moves` the server returns, so the page offers
 * exactly what the server accepts and a later status needs only a label and a description in `types.ts`. There is no
 * approval step, so any person who may manage the record may make any listed move; the server answers a refusal (for
 * example retiring an element whose children are in use), which the page shows. Promote is the next main-path
 * step; a move that is not Promote (Reject, Retire, Reactivate, Return to draft, Reopen as draft, Activate directly)
 * is a menu row, destructive moves with the danger style, and absent when the server does not allow it.
 *
 * External dependencies: `lifecycleSteps`, the architecture status maps.
 */
import type { ActionMenuItem } from "../../components/ActionMenu";
import type { LifecycleTrackProps } from "../../components/LifecycleTrack";
import { lifecycleSteps } from "../../components/lifecycleSteps";
import { ARCHITECTURE_STATUS_DESCRIPTION, ARCHITECTURE_STATUS_LABEL, type ArchitectureRecordStatus } from "./types";

const MAIN_PATH: ArchitectureRecordStatus[] = ["draft", "proposed", "active"];

/** The menu row for the move `from` -> `to`; the label names what the move does in that direction. */
function moveRow(from: ArchitectureRecordStatus, to: ArchitectureRecordStatus): Pick<ActionMenuItem, "label" | "danger"> {
  if (to === "retired") return { label: "Retire", danger: true };
  if (to === "rejected") return { label: "Reject", danger: true };
  if (to === "draft") return { label: from === "rejected" ? "Reopen as draft" : "Return to draft" };
  return { label: from === "retired" ? "Reactivate" : "Activate directly" };
}

/**
 * @param status The record's current status.
 * @param moves The statuses the record may move to (`allowed_status_moves`).
 * @param onMove Moves the record to a status; the page saves it and reports a refusal.
 * @param hidden True when the person may not change the status from this page (a shared element): the track shows the state with no move.
 * @returns `lifecycle` for `RecordHeader` and `menuRows` for its `actions`.
 */
export function architectureLifecycle(
  status: ArchitectureRecordStatus,
  moves: ArchitectureRecordStatus[],
  onMove: (next: ArchitectureRecordStatus) => void | Promise<void>,
  hidden = false,
): { lifecycle: LifecycleTrackProps; menuRows: ActionMenuItem[] } {
  const allowed = hidden ? [] : moves;
  const index = MAIN_PATH.indexOf(status);
  const promoteTo = index >= 0 ? MAIN_PATH[index + 1] : undefined;
  const promotable = promoteTo !== undefined && allowed.includes(promoteTo) ? promoteTo : undefined;
  const offKey: ArchitectureRecordStatus = status === "rejected" ? "rejected" : "retired";

  const lifecycle: LifecycleTrackProps = {
    steps: lifecycleSteps(MAIN_PATH, ARCHITECTURE_STATUS_LABEL, { descriptions: ARCHITECTURE_STATUS_DESCRIPTION }),
    current: status,
    offPath: {
      key: offKey, label: ARCHITECTURE_STATUS_LABEL[offKey], description: ARCHITECTURE_STATUS_DESCRIPTION[offKey],
      after: offKey === "retired" ? "active" : undefined,
    },
    promote: promotable ? { to: promotable, onPromote: () => void onMove(promotable) } : undefined,
  };

  const menuRows: ActionMenuItem[] = allowed
    .filter((to) => to !== promotable)
    .map((to) => ({ ...moveRow(status, to), onSelect: () => void onMove(to) }));
  return { lifecycle, menuRows };
}
