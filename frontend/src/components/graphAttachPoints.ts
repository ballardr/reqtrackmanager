/**
 * Module: components/graphAttachPoints
 *
 * The eight places a line can meet a box on the shared graph canvas (the middle of each side and the four corners) and
 * the rule that picks the two a line uses. Pure functions, no React, so the canvas, a consumer's selection panel and the
 * tests all use the one rule.
 *
 * Responsibilities:
 * - Give the position of each attach point of a box.
 * - Choose the points of one line: an end the consumer fixed stays as given, an end left open is the point nearest the
 *   other end, and with both open the pair of points nearest each other.
 *
 * Design decisions:
 * - The same rule runs on the server for the architecture SVG (`diagram_points.py`); `graphAttachPointCases.json` holds
 *   the cases both are tested against, so a change to the rule is made in both.
 * - Nearest means least squared distance (no square root), compared with a small tolerance and decided in the fixed order
 *   of `ATTACH_POINTS`, so a tie (two boxes side by side: the facing corners are as close as the facing sides) gives the
 *   sides in both languages.
 */

/** One of the eight attach points of a box. */
export type AttachPoint =
  | "top" | "right" | "bottom" | "left" | "top_right" | "bottom_right" | "bottom_left" | "top_left";

/** The points in tie-break order: the middle of each side, then the corners. */
export const ATTACH_POINTS: readonly AttachPoint[] = [
  "top", "right", "bottom", "left", "top_right", "bottom_right", "bottom_left", "top_left",
];

/** What a person sees for each point. */
export const ATTACH_POINT_LABEL: Record<AttachPoint, string> = {
  top: "Top", right: "Right", bottom: "Bottom", left: "Left",
  top_right: "Top right", bottom_right: "Bottom right", bottom_left: "Bottom left", top_left: "Top left",
};

/** A box: its top-left corner and size. */
export interface BoxGeometry {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** A distance must beat the best so far by more than this to win, so equal distances keep the earlier point. */
const TOLERANCE = 1e-6;

/** @returns Where `point` of `box` is. */
export function pointXY(box: BoxGeometry, point: AttachPoint): { x: number; y: number } {
  const { x, y, width: w, height: h } = box;
  switch (point) {
    case "top": return { x: x + w / 2, y };
    case "right": return { x: x + w, y: y + h / 2 };
    case "bottom": return { x: x + w / 2, y: y + h };
    case "left": return { x, y: y + h / 2 };
    case "top_right": return { x: x + w, y };
    case "bottom_right": return { x: x + w, y: y + h };
    case "bottom_left": return { x, y: y + h };
    case "top_left": return { x, y };
  }
}

const squared = (a: { x: number; y: number }, b: { x: number; y: number }): number => (a.x - b.x) ** 2 + (a.y - b.y) ** 2;

/** @returns The point of `box` nearest the position `to` (ties go to the sides, then to the order of `ATTACH_POINTS`). */
export function nearestPoint(box: BoxGeometry, to: { x: number; y: number }): AttachPoint {
  let best = Number.POSITIVE_INFINITY;
  let chosen: AttachPoint = ATTACH_POINTS[0];
  for (const a of ATTACH_POINTS) {
    const distance = squared(pointXY(box, a), to);
    if (distance < best - TOLERANCE) {
      best = distance;
      chosen = a;
    }
  }
  return chosen;
}

/** @returns The point of each box that lies nearest each other (ties as in `nearestPoint`). */
export function nearestPair(source: BoxGeometry, target: BoxGeometry): [AttachPoint, AttachPoint] {
  let best = Number.POSITIVE_INFINITY;
  let chosen: [AttachPoint, AttachPoint] = [ATTACH_POINTS[0], ATTACH_POINTS[0]];
  for (const a of ATTACH_POINTS) {
    const pa = pointXY(source, a);
    for (const b of ATTACH_POINTS) {
      const distance = squared(pa, pointXY(target, b));
      if (distance < best - TOLERANCE) {
        best = distance;
        chosen = [a, b];
      }
    }
  }
  return chosen;
}

/**
 * The two points a line between the boxes uses.
 *
 * @param source The source box.
 * @param target The target box.
 * @param sourcePoint The point fixed on the source box, or null/undefined for automatic.
 * @param targetPoint The point fixed on the target box, or null/undefined for automatic.
 * @returns `[source point, target point]`: a fixed end as given, an open end the nearest to the other end.
 */
export function lineAttachPoints(
  source: BoxGeometry, target: BoxGeometry, sourcePoint?: AttachPoint | null, targetPoint?: AttachPoint | null,
): [AttachPoint, AttachPoint] {
  if (sourcePoint && targetPoint) return [sourcePoint, targetPoint];
  if (sourcePoint) return [sourcePoint, nearestPoint(target, pointXY(source, sourcePoint))];
  if (targetPoint) return [nearestPoint(source, pointXY(target, targetPoint)), targetPoint];
  return nearestPair(source, target);
}
