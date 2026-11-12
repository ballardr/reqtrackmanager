/**
 * Module: modules/architecture/ArchitectureStatusControls
 *
 * The status buttons of an element or a connection, shown beside its status in the record header: Activate a draft,
 * Retire an active record, Reactivate a retired one. There is no approval step, so any person who may manage the record
 * may move it; the server answers a refusal (for example retiring an element that still has active children), which the
 * page shows. Status is shown through `ARCHITECTURE_STATUS_LABEL`.
 */
import type { ArchitectureRecordStatus } from "./types";

/** The one move each status offers, and the button text. */
const NEXT: Record<ArchitectureRecordStatus, { status: ArchitectureRecordStatus; label: string; primary: boolean }> = {
  draft: { status: "active", label: "Activate", primary: true },
  active: { status: "retired", label: "Retire", primary: false },
  retired: { status: "active", label: "Reactivate", primary: false },
};

/**
 * @param status The record's current status.
 * @param onMove Called with the status to move to; the page saves it and reports a refusal.
 */
export function ArchitectureStatusControls({
  status, onMove,
}: { status: ArchitectureRecordStatus; onMove: (next: ArchitectureRecordStatus) => void | Promise<void> }) {
  const next = NEXT[status];
  return (
    <button className={next.primary ? "btn btn-primary" : "btn"} onClick={() => void onMove(next.status)}>
      {next.label}
    </button>
  );
}
