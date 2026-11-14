/**
 * Module: modules/architecture/stateMachineComments
 *
 * How a state machine diagram's comment pins map between the record keys the server stores and the ids the canvas draws.
 * The canvas ids are the record ids themselves (a state's id, a transition's id), so a stored key is a canvas id when the
 * state or transition is still on the diagram.
 *
 * Responsibilities:
 * - `statePinAnchorOf`: the node or line a stored pin is anchored to, or `undefined` when it is free or gone.
 * - `statePinPlaceOf`: the place a click or a dropped pin becomes: anchored to the state or transition it landed on.
 * - `statePinDescriber`: the names the Comments tab uses for the anchors (codes shown by the record-code display rule).
 */
import type { PinAnchorKind, PlaceInput } from "../../api/recordComments";
import type { GraphPointAnchor } from "../../components/GraphCanvas";
import type { PinDescriber } from "./diagramComments";
import type { StateMachineLayout } from "./stateMachineModel";
import type { StateLabels } from "./useStateLabel";
import type { StateMachineModel } from "./types";

/**
 * @param place The stored pin's anchor.
 * @param model The model as read.
 * @returns The canvas node or line the pin follows, or `undefined` when it is free or its state or transition is gone.
 */
export function statePinAnchorOf(
  place: { anchor_kind: PinAnchorKind; anchor_key: string | null }, model: StateMachineModel,
): { kind: "node" | "edge"; id: string } | undefined {
  const key = place.anchor_key;
  if (!key) return undefined;
  if (place.anchor_kind === "node") return model.states.some((s) => s.id === key) ? { kind: "node", id: key } : undefined;
  if (place.anchor_kind === "edge") return model.transitions.some((t) => t.id === key) ? { kind: "edge", id: key } : undefined;
  return undefined;
}

/**
 * @param position The canvas position of the click or drop.
 * @param anchor What it landed on (canvas ids).
 * @param model The model as read.
 * @param layout The drawing, for a state's corner.
 * @returns The place to store: anchored to a state (at its top right corner) or a transition, else free.
 */
export function statePinPlaceOf(
  position: { x: number; y: number }, anchor: GraphPointAnchor, model: StateMachineModel, layout: StateMachineLayout,
): PlaceInput {
  const free: PlaceInput = { anchor_kind: "none", anchor_key: null, x: Math.round(position.x), y: Math.round(position.y) };
  if (anchor.kind === "node") {
    const box = layout.boxes.find((b) => b.id === anchor.id);
    return box && model.states.some((s) => s.id === anchor.id)
      ? { anchor_kind: "node", anchor_key: anchor.id, x: Math.round(box.x + box.width), y: Math.round(box.y) }
      : free;
  }
  if (anchor.kind === "edge") {
    return model.transitions.some((t) => t.id === anchor.id) ? { anchor_kind: "edge", anchor_key: anchor.id, x: free.x, y: free.y } : free;
  }
  return free;
}

/** @returns The state machine editor's describer: a state is named by its code and name, a transition by its two state codes. */
export function statePinDescriber(model: StateMachineModel, labels: StateLabels): PinDescriber {
  return {
    drawn: (place) => statePinAnchorOf(place, model) !== undefined,
    boxName: (key) => {
      const state = model.states.find((s) => s.id === key);
      return state ? labels.label(state) : "";
    },
    lineName: (key) => {
      const t = model.transitions.find((x) => x.id === key);
      const from = model.states.find((s) => s.id === t?.source_state_id);
      const to = model.states.find((s) => s.id === t?.target_state_id);
      return t ? `${from ? labels.code(from) : t.source_state_code} → ${to ? labels.code(to) : t.target_state_code}` : "";
    },
  };
}
