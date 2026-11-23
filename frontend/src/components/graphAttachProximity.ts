/**
 * Module: components/graphAttachProximity
 *
 * Decides which boxes of the graph canvas show their attach points because the pointer is near them.
 *
 * Responsibilities: say, for a pointer position and boxes in canvas units, which are near (inside the box or within a
 * margin of its edge, given in screen pixels and converted with the zoom so it does not change as the person zooms); treat
 * a container (a frame holding other boxes) as near only along its edge, so a pointer inside the frame does not show the
 * frame's points.
 *
 * Design decisions: pure and DOM-free (the canvas sets an attribute on each box's element, so a pointer move never
 * re-renders React); the margin is wider than the points' own hit area, so a point does not vanish under the pointer; it
 * works on absolute canvas coordinates like the rest of the canvas geometry.
 *
 * Dependencies: `graphAttachPoints` (the `BoxGeometry` shape).
 */
import type { BoxGeometry } from "./graphAttachPoints";

/** How near, in screen pixels, the pointer must be to a box for its attach points to show. */
export const ATTACH_NEAR_MARGIN_PX = 24;

/** A box and whether it is a container, as the proximity rule needs them. */
export interface ProximityBox extends BoxGeometry {
  container?: boolean;
}

/**
 * Finds the boxes whose attach points should show for a pointer position.
 *
 * @param boxes Each box by id, in absolute canvas units.
 * @param pointer The pointer position in canvas units.
 * @param zoom The canvas zoom (screen pixels per canvas unit); a value that is not positive is treated as 1.
 * @param marginPx The distance from a box's edge, in screen pixels, that still counts as near.
 * @returns The ids of the boxes that are near. A container is near only within the margin of its edge, inside or outside.
 */
export function nearBoxIds(
  boxes: Iterable<[string, ProximityBox]>,
  pointer: { x: number; y: number },
  zoom: number,
  marginPx: number = ATTACH_NEAR_MARGIN_PX,
): Set<string> {
  const margin = marginPx / (zoom > 0 ? zoom : 1);
  const near = new Set<string>();
  for (const [id, box] of boxes) {
    const outside = pointer.x < box.x - margin || pointer.x > box.x + box.width + margin || pointer.y < box.y - margin || pointer.y > box.y + box.height + margin;
    if (outside) continue;
    if (box.container) {
      const deep = pointer.x > box.x + margin && pointer.x < box.x + box.width - margin && pointer.y > box.y + margin && pointer.y < box.y + box.height - margin;
      if (deep) continue;
    }
    near.add(id);
  }
  return near;
}
