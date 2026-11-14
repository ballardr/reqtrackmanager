/**
 * Module: modules/architecture/StateMachineAddMenu
 *
 * The state machine editor's "Add to diagram" menu button: one entry per state kind (State, Initial state, Final state,
 * Choice). Choosing one opens the state form with the item placed at the next free position; dragging one onto the canvas
 * places it where it is dropped (inside the frame of a composite state it lands on). Dragging is only one way in: every entry
 * is a menu item, so the menu is usable from the keyboard.
 */
import { GRAPH_DROP_MIME } from "../../components/GraphCanvas";
import { MenuButton } from "../../components/MenuButton";
import type { ActionMenuItem } from "../../components/ActionMenu";
import { PALETTE_KIND_PREFIX } from "./stateMachineModel";
import { STATE_KIND_LABEL, type StateKind } from "./types";

/** The kinds in menu order. */
const KINDS: StateKind[] = ["state", "initial", "final", "choice"];

/**
 * @param disabled True when the diagram cannot be edited (read-only).
 * @param onAdd Called with the kind when an entry is chosen.
 */
export function StateMachineAddMenu({ disabled, onAdd }: { disabled: boolean; onAdd: (kind: StateKind) => void }) {
  const items = KINDS.map((kind): ActionMenuItem => ({
    label: STATE_KIND_LABEL[kind],
    key: `kind:${kind}`,
    group: "New",
    onSelect: () => onAdd(kind),
    onDragStart: (event) => {
      event.dataTransfer.setData(GRAPH_DROP_MIME, PALETTE_KIND_PREFIX + kind);
      event.dataTransfer.effectAllowed = "copy";
    },
  }));
  return <MenuButton label="Add to diagram" menuLabel="Add to diagram" size="sm" disabled={disabled} items={items} />;
}
