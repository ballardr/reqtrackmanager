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
 *   other end, and with both open the pair of points nearest each other. A box may offer fewer points (`points`): a marker
 *   (a dot or a diamond) offers only the middle of each side, since its corners are not on its outline.
 * - Give the direction a line leaves a box at an attach point (`outwardDirection`), which a Curved line starts its curve along.
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

/** The four points at the middle of a side: all a round or diamond marker offers (its corners are not on its outline). */
export const SIDE_POINTS: readonly AttachPoint[] = ["top", "right", "bottom", "left"];

/** A box: its top-left corner and size. */
export interface BoxGeometry {
  x: number;
  y: number;
  width: number;
  height: number;
  /** The points an open end may choose (in `ATTACH_POINTS` order); all eight when omitted. A fixed end is used as given. */
  points?: readonly AttachPoint[];
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
  const points = box.points ?? ATTACH_POINTS;
  let best = Number.POSITIVE_INFINITY;
  let chosen: AttachPoint = points[0];
  for (const a of points) {
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
  const sourcePoints = source.points ?? ATTACH_POINTS;
  const targetPoints = target.points ?? ATTACH_POINTS;
  let best = Number.POSITIVE_INFINITY;
  let chosen: [AttachPoint, AttachPoint] = [sourcePoints[0], targetPoints[0]];
  for (const a of sourcePoints) {
    const pa = pointXY(source, a);
    for (const b of targetPoints) {
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

/** A unit vector: the direction a line leaves a box. */
export interface Direction {
  x: number;
  y: number;
}

/** Two directions are told apart only when their dot products differ by more than this, so a tie keeps the earlier candidate. */
const DIRECTION_TOLERANCE = 1e-9;

/** The side normals a corner lies on (the vertical one first), and the signs of its centre-to-corner diagonal. */
const CORNER_NORMALS: Partial<Record<AttachPoint, { vertical: Direction; horizontal: Direction; sx: number; sy: number }>> = {
  top_right: { vertical: { x: 0, y: -1 }, horizontal: { x: 1, y: 0 }, sx: 1, sy: -1 },
  bottom_right: { vertical: { x: 0, y: 1 }, horizontal: { x: 1, y: 0 }, sx: 1, sy: 1 },
  bottom_left: { vertical: { x: 0, y: 1 }, horizontal: { x: -1, y: 0 }, sx: -1, sy: 1 },
  top_left: { vertical: { x: 0, y: -1 }, horizontal: { x: -1, y: 0 }, sx: -1, sy: -1 },
};

/**
 * The direction a line leaves `box` at `point`: the way from the box's centre through the point. A side point has one (its side's
 * normal); a corner has three candidates (the centre-to-corner diagonal and the two side normals it lies on) and takes the one
 * with the smallest angle to the straight line toward `toward`, so a corner bends no more than the boxes' positions need. A tie
 * goes to the diagonal, then to the vertical side.
 *
 * @param box The box the line meets.
 * @param point The attach point on it.
 * @param toward Where the line is heading from the point (the other end, or the nearest vertex); null chooses the diagonal.
 * @returns A unit vector pointing out of the box.
 */
export function outwardDirection(box: BoxGeometry, point: AttachPoint, toward: { x: number; y: number } | null): Direction {
  switch (point) {
    case "top": return { x: 0, y: -1 };
    case "right": return { x: 1, y: 0 };
    case "bottom": return { x: 0, y: 1 };
    case "left": return { x: -1, y: 0 };
    default: break;
  }
  const corner = CORNER_NORMALS[point];
  if (!corner) return { x: 0, y: -1 };
  const dx = (corner.sx * box.width) / 2;
  const dy = (corner.sy * box.height) / 2;
  const norm = Math.sqrt(dx * dx + dy * dy);
  const diagonal = norm === 0 ? corner.vertical : { x: dx / norm, y: dy / norm };
  if (!toward) return diagonal;
  const at = pointXY(box, point);
  const lx = toward.x - at.x;
  const ly = toward.y - at.y;
  const length = Math.sqrt(lx * lx + ly * ly);
  if (length === 0) return diagonal;
  const ux = lx / length;
  const uy = ly / length;
  let best = diagonal;
  let bestDot = diagonal.x * ux + diagonal.y * uy;
  for (const candidate of [corner.vertical, corner.horizontal]) {
    const dot = candidate.x * ux + candidate.y * uy;
    if (dot > bestDot + DIRECTION_TOLERANCE) {
      best = candidate;
      bestDot = dot;
    }
  }
  return best;
}

/**
 * The directions a line leaves its two boxes in: each end's outward direction toward the line's next point (the nearest vertex,
 * else the other end's attach point).
 *
 * @param source The source box.
 * @param target The target box.
 * @param sourcePoint The attach point used on the source box.
 * @param targetPoint The attach point used on the target box.
 * @param via The vertices in order from the source to the target.
 * @returns `[source direction, target direction]`.
 */
export function lineDirections(
  source: BoxGeometry, target: BoxGeometry, sourcePoint: AttachPoint, targetPoint: AttachPoint, via: readonly { x: number; y: number }[],
): [Direction, Direction] {
  const sourceToward = via.length > 0 ? via[0] : pointXY(target, targetPoint);
  const targetToward = via.length > 0 ? via[via.length - 1] : pointXY(source, sourcePoint);
  return [outwardDirection(source, sourcePoint, sourceToward), outwardDirection(target, targetPoint, targetToward)];
}

/**
 * The two points a line with vertices uses: an open end is the point of its box nearest the vertex next to it (the first for
 * the source, the last for the target), not the other box. With no vertices this is `lineAttachPoints`.
 *
 * @param source The source box.
 * @param target The target box.
 * @param sourcePoint The point fixed on the source box, or null/undefined for automatic.
 * @param targetPoint The point fixed on the target box, or null/undefined for automatic.
 * @param via The vertices in order from the source to the target.
 * @returns `[source point, target point]`.
 */
export function routeAttachPoints(
  source: BoxGeometry, target: BoxGeometry, sourcePoint: AttachPoint | null | undefined, targetPoint: AttachPoint | null | undefined,
  via: readonly { x: number; y: number }[],
): [AttachPoint, AttachPoint] {
  if (via.length === 0) return lineAttachPoints(source, target, sourcePoint, targetPoint);
  return [sourcePoint ?? nearestPoint(source, via[0]), targetPoint ?? nearestPoint(target, via[via.length - 1])];
}
