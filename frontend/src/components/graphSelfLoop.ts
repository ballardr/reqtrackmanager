/**
 * Module: components/graphSelfLoop
 *
 * The shape of a line that leaves a box and returns to the same box (a self loop on the shared graph canvas). Pure
 * functions, no React, so the canvas and the tests use the one rule.
 *
 * Responsibilities:
 * - Give the cubic curve of a loop on a box: where it leaves, where it returns, its two control points and the point a label
 *   sits at.
 * - Turn the curve into an SVG path string.
 *
 * Design decisions:
 * - The loop is fixed standard geometry: it leaves the top side three quarters of the way across, bulges outward past the
 *   top right corner by `SELF_LOOP_REACH` and returns to the right side a quarter of the way down, so its arrowhead points
 *   into the box. A consumer cannot fix its attach points (a loop has no choice to make).
 * - The server draws the same loop with a Python copy (`state_shapes.py`); `graphSelfLoopCases.json` holds the cases both are
 *   tested against, so a change to the rule is made in both.
 */

/** How far the curve reaches beyond the box, in canvas units. */
export const SELF_LOOP_REACH = 36;

/** A position in canvas units. */
export interface LoopPoint {
  x: number;
  y: number;
}

/** The cubic curve of a self loop and the label anchor: the middle of the curve, which is the bottom-left corner of the label's text. */
export interface SelfLoop {
  start: LoopPoint;
  control1: LoopPoint;
  control2: LoopPoint;
  end: LoopPoint;
  label: LoopPoint;
}

/**
 * The loop of a box.
 *
 * @param box The box's top-left corner and size.
 * @returns The curve leaving the top side and returning to the right side, with the label position at the curve's middle.
 */
export function selfLoop(box: { x: number; y: number; width: number; height: number }): SelfLoop {
  const { x, y, width: w, height: h } = box;
  const start = { x: x + 0.75 * w, y };
  const control1 = { x: x + 0.75 * w, y: y - SELF_LOOP_REACH };
  const control2 = { x: x + w + SELF_LOOP_REACH, y: y + 0.25 * h };
  const end = { x: x + w, y: y + 0.25 * h };
  // The point at t = 0.5 of a cubic Bezier is (P0 + 3 P1 + 3 P2 + P3) / 8.
  const label = {
    x: (start.x + 3 * control1.x + 3 * control2.x + end.x) / 8,
    y: (start.y + 3 * control1.y + 3 * control2.y + end.y) / 8,
  };
  return { start, control1, control2, end, label };
}

/** @returns The SVG path (`M … C …`) of a loop, numbers rounded to two decimals. */
export function selfLoopPath(loop: SelfLoop): string {
  const n = (v: number) => String(Math.round(v * 100) / 100);
  const p = (pt: LoopPoint) => `${n(pt.x)} ${n(pt.y)}`;
  return `M ${p(loop.start)} C ${p(loop.control1)} ${p(loop.control2)} ${p(loop.end)}`;
}
