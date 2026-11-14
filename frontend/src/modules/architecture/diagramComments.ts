/**
 * Module: modules/architecture/diagramComments
 *
 * How a diagram's comment pins map between the record keys the server stores and the ids the canvas draws.
 *
 * Responsibilities:
 * - `pinAnchorOf`: the canvas node or line a stored pin is anchored to (a box by its element id, a line by one of the
 *   connections it stands for), or `undefined` when it is not drawn (a switched-off box, a rolled-up line that no longer
 *   exists), so the canvas keeps the pin at its last place.
 * - `pinPlaceOf`: the place a click or a dropped pin becomes: anchored to the box or line it landed on, otherwise free.
 *
 * Design decisions:
 * - Keys are record ids (an element id, a connection id), never canvas ids: a drawn line may be rolled up or bridged and
 *   its id changes with the switches, whereas its connections do not, so a pin stays true when the drawing changes.
 * - A note or a boundary box is not a record on the diagram, so a click on one places a free pin.
 *
 * Dependencies: `diagramEditorModel`, `api/recordComments`, `types`.
 */
import type { PinAnchorKind, PlaceInput } from "../../api/recordComments";
import type { GraphPointAnchor } from "../../components/GraphCanvas";
import type { EditorBox } from "./diagramEditorModel";
import type { DiagramViewEdge } from "./types";

/**
 * @param place The stored pin's anchor.
 * @param boxes The boxes on the diagram.
 * @param edges The drawn lines (resolved for the current switches).
 * @returns The canvas node or line the pin follows, or `undefined` when it is free or its anchor is not drawn.
 */
export function pinAnchorOf(
  place: { anchor_kind: PinAnchorKind; anchor_key: string | null },
  boxes: readonly EditorBox[],
  edges: readonly DiagramViewEdge[],
): { kind: "node" | "edge"; id: string } | undefined {
  const key = place.anchor_key;
  if (!key) return undefined;
  if (place.anchor_kind === "node") return boxes.some((b) => b.elementId === key) ? { kind: "node", id: key } : undefined;
  if (place.anchor_kind === "edge") {
    const line = edges.find((e) => e.connections.some((c) => c.id === key));
    return line ? { kind: "edge", id: line.id } : undefined;
  }
  return undefined;
}

/**
 * @param position The canvas position of the click or drop.
 * @param anchor What it landed on (canvas ids).
 * @param boxes The boxes on the diagram.
 * @param edges The drawn lines.
 * @returns The place to store: anchored to a box (its element id) or a line (its first connection's id), else free.
 */
export function pinPlaceOf(
  position: { x: number; y: number }, anchor: GraphPointAnchor, boxes: readonly EditorBox[], edges: readonly DiagramViewEdge[],
): PlaceInput {
  const free: PlaceInput = { anchor_kind: "none", anchor_key: null, x: Math.round(position.x), y: Math.round(position.y) };
  if (anchor.kind === "node") {
    const box = boxes.find((b) => b.elementId === anchor.id);
    return box ? { anchor_kind: "node", anchor_key: box.elementId, x: Math.round(box.x + box.width), y: Math.round(box.y) } : free;
  }
  if (anchor.kind === "edge") {
    const connection = edges.find((e) => e.id === anchor.id)?.connections[0];
    return connection ? { anchor_kind: "edge", anchor_key: connection.id, x: free.x, y: free.y } : free;
  }
  return free;
}
