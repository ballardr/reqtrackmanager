/**
 * Module: utils/sliceAtPoint
 *
 * Hit-testing for the dashboard donut (`components/StatusPieChart.tsx`): which slice a pointer is over, worked out
 * from the ring's geometry alone.
 */

/** The ring's geometry in px: the box is 120 square, so the centre is at 60,60. */
export const RING_INNER_PX = 35;
export const RING_OUTER_PX = 60;

/**
 * The slice under a point of the ring, from geometry alone (not from Recharts' elements, which it replaces on every
 * render, so their enter/leave events cannot be trusted to pair up).
 *
 * @param dx Pointer distance right of the ring's centre, px.
 * @param dy Pointer distance below the ring's centre, px.
 * @param values Each slice's value, in drawing order (clockwise from the top).
 * @returns The slice's index, or -1 for the hole, outside the ring or a ring with no value.
 */
export function sliceAtPoint(dx: number, dy: number, values: number[]): number {
  const radius = Math.hypot(dx, dy);
  const total = values.reduce((sum, v) => sum + v, 0);
  if (total <= 0 || radius < RING_INNER_PX || radius > RING_OUTER_PX) return -1;
  const turn = (Math.atan2(dx, -dy) + 2 * Math.PI) % (2 * Math.PI) / (2 * Math.PI);
  let upTo = 0;
  for (let i = 0; i < values.length; i += 1) {
    upTo += values[i];
    if (values[i] > 0 && turn * total < upTo) return i;
  }
  return -1;
}
