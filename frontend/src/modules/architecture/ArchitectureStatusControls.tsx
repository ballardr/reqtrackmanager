/**
 * Module: modules/architecture/ArchitectureStatusControls
 *
 * The "Change status" menu of an element, a connection or a diagram, drawn beside Edit in the record header. Each item
 * names the move from the current status ("Move from Draft to Proposed"); the moves are the `allowed_status_moves` the
 * server returns with the record, so the menu offers exactly what the server accepts and a later status needs only a
 * label here. A (?) help beside the button describes every status. There is no approval step, so any person who may
 * manage the record may use it; the server answers a refusal (for example retiring an element that still has children
 * in use), which the page shows. A record with no moves draws nothing.
 */
import { FieldHelp } from "../../components/FieldHelp";
import { MenuButton } from "../../components/MenuButton";
import { ARCHITECTURE_HELP } from "./help";
import { ARCHITECTURE_STATUS_LABEL, type ArchitectureRecordStatus } from "./types";

/**
 * @param status The record's current status.
 * @param moves The states the record may move to (`allowed_status_moves`), in menu order.
 * @param onMove Called with the status to move to; the page saves it and reports a refusal.
 */
export function ArchitectureStatusControls({
  status, moves, onMove,
}: {
  status: ArchitectureRecordStatus;
  moves: ArchitectureRecordStatus[];
  onMove: (next: ArchitectureRecordStatus) => void | Promise<void>;
}) {
  if (moves.length === 0) return null;
  return (
    <span className="row" style={{ gap: "var(--space-1)", flexWrap: "nowrap" }}>
      <MenuButton
        label="Change status"
        menuLabel="Change status"
        items={moves.map((next) => ({
          label: `Move from ${ARCHITECTURE_STATUS_LABEL[status]} to ${ARCHITECTURE_STATUS_LABEL[next]}`,
          onSelect: () => void onMove(next),
        }))}
      />
      <FieldHelp label="Change status" help={ARCHITECTURE_HELP.statusMenu} />
    </span>
  );
}
