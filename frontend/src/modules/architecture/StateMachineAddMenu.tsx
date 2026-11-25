/**
 * Module: modules/architecture/StateMachineAddMenu
 *
 * The state machine editor's "Add to diagram" menu button: one entry per state kind (State, Initial state, Final state,
 * Choice). Choosing one adds it at once at the next free position; dragging one onto the canvas places it where it is dropped
 * (inside the frame of a composite state it lands on); "Add note" places a note at the next free position. Dragging is
 * only one way in: every entry is a menu item, so the menu is usable from the keyboard. How to build a machine is the button's tooltip, never text in the layout.
 */
import { GRAPH_DROP_MIME } from "../../components/GraphCanvas";
import { MenuButton } from "../../components/MenuButton";
import type { ActionMenuItem } from "../../components/ActionMenu";
import { ARCHITECTURE_HELP } from "./help";
import { PALETTE_KIND_PREFIX } from "./stateMachineModel";
import { STATE_KIND_LABEL, type StateKind } from "./types";

/** The kinds in menu order. */
const KINDS: StateKind[] = ["state", "initial", "final", "choice"];

/**
 * @param disabled True when the diagram cannot be edited (read-only) or a change is being stored.
 * @param onAdd Called with the kind when an entry is chosen.
 * @param onAddNote Called by "Add note".
 */
export function StateMachineAddMenu({ disabled, onAdd, onAddNote }: { disabled: boolean; onAdd: (kind: StateKind) => void; onAddNote: () => void }) {
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
  items.push({ label: "Add note", key: "note", onSelect: onAddNote });
  return <MenuButton label="Add to diagram" menuLabel="Add to diagram" size="sm" help={ARCHITECTURE_HELP.stateAdd} disabled={disabled} items={items} />;
}
