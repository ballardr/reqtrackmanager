/**
 * Module: components/graphSelfLoop
 *
 * The shape of a line that leaves a box and returns to the same box (a self loop on the shared graph canvas). Pure
 * functions, no React, so the canvas and the tests share one rule.
 *
 * Responsibilities: give the cubic curve of a loop on a box (where it leaves and returns, its two control points and the
 * label point) and turn it into an SVG path string.
 *
 * Design decisions:
 * - The loop is fixed standard geometry: in the first slot it leaves the top side three quarters across, bulges outward
 *   past the top right corner by `SELF_LOOP_REACH` and returns to the right side a quarter down, so its arrowhead points
 *   into the box. A consumer cannot fix its attach points; several loops on one box take the other corners in turn
 *   (`slot`, from `graphLineAnchors`), so none draws over another.
 * - A marker (a dot, a ring, a diamond) has no outline at its corners, so its loop runs between the middles of a top or
 *   bottom side and a left or right side (`sides`, the points the marker offers; a corner is used only when both its
 *   sides are offered, so a label on one side is not crossed).
 * - The server draws the same loop with `state_shapes.py`; `graphSelfLoopCases.json` holds the cases both are tested
 *   against, so a change is made in both.
 */

/** How far the curve reaches beyond the box, in canvas units. */
export const SELF_LOOP_REACH = 36;

/** The four sides a loop on a marker may use. */
export type LoopSide = "top" | "right" | "bottom" | "left";

/** The two sides each corner slot of a marker's loop uses: the top right first, then the bottom right, bottom left and top left. */
const CORNER_SIDES: readonly (readonly [LoopSide, LoopSide])[] = [["top", "right"], ["bottom", "right"], ["bottom", "left"], ["top", "left"]];

/** A position in canvas units. */
export interface LoopPoint {
  x: number;
  y: number;
}

/**
 * The cubic curve of a self loop and the label anchor: the middle of the curve. `align` says which side of the anchor the text
 * runs: `start` for a loop on a right corner (the text begins at the anchor, rising above it), `end` for one on a left corner
 * (the text ends at the anchor).
 */
export interface SelfLoop {
  start: LoopPoint;
  control1: LoopPoint;
  control2: LoopPoint;
  end: LoopPoint;
  label: LoopPoint;
  align: "start" | "end";
}

/**
 * The loop of a box.
 *
 * @param box The box's top-left corner and size.
 * @param slot Which corner the loop takes: 0 the top right (the default), then 1 the bottom right, 2 the bottom left and 3 the
 *   top left; from 4 the loops go round again, reaching further out each time.
 * @param sides For a marker: the sides it offers. The loop then runs between the middles of two of them (the slot picks among the
 *   corners whose two sides are both offered, or among all four when none is), instead of between points of the bounding box.
 * @returns The curve leaving the top (or bottom) side and returning to the right (or left) side, with the label position at the
 *   curve's middle.
 */
export function selfLoop(box: { x: number; y: number; width: number; height: number }, slot = 0, sides?: readonly string[]): SelfLoop {
  const { x, y, width: w, height: h } = box;
  const usable = sides ? CORNER_SIDES.map((pair, index) => ({ pair, index })).filter(({ pair }) => pair.every((side) => sides.includes(side))) : [];
  const corners = usable.length > 0 ? usable.map(({ index }) => index) : [0, 1, 2, 3];
  const corner = corners[slot % corners.length];
  const reach = SELF_LOOP_REACH * (1 + Math.floor(slot / corners.length));
  const right = corner === 0 || corner === 1;
  const bottom = corner === 1 || corner === 2;
  const across = sides ? 0.5 : right ? 0.75 : 0.25;
  const down = sides ? 0.5 : bottom ? 0.75 : 0.25;
  const sideY = bottom ? y + h : y;
  const sideX = right ? x + w : x;
  const start = { x: x + across * w, y: sideY };
  const control1 = { x: x + across * w, y: bottom ? sideY + reach : sideY - reach };
  const control2 = { x: right ? sideX + reach : sideX - reach, y: y + down * h };
  const end = { x: sideX, y: y + down * h };
  // The point at t = 0.5 of a cubic Bezier is (P0 + 3 P1 + 3 P2 + P3) / 8.
  const label = {
    x: (start.x + 3 * control1.x + 3 * control2.x + end.x) / 8,
    y: (start.y + 3 * control1.y + 3 * control2.y + end.y) / 8,
  };
  return { start, control1, control2, end, label, align: right ? "start" : "end" };
}

/** @returns The SVG path (`M … C …`) of a loop, numbers rounded to two decimals. */
export function selfLoopPath(loop: SelfLoop): string {
  const n = (v: number) => String(Math.round(v * 100) / 100);
  const p = (pt: LoopPoint) => `${n(pt.x)} ${n(pt.y)}`;
  return `M ${p(loop.start)} C ${p(loop.control1)} ${p(loop.control2)} ${p(loop.end)}`;
}
