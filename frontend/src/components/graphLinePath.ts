/**
 * Module: components/graphLinePath
 *
 * The shape of a drawn line that has waypoints on the shared graph canvas. Pure functions, no React, so the canvas, the
 * editors and the tests use the one rule.
 *
 * Responsibilities:
 * - Turn a line's two end points and its ordered waypoints into an SVG path: straight between the points, or smooth (a curve
 *   through every point).
 * - Give the middle of the line, where a label and a comment pin sit, and the middle of each segment (where a drag adds a vertex).
 * - Offer the edits a route allows: insert, move and remove a waypoint, within the cap.
 *
 * Design decisions:
 * - Coordinates are absolute canvas units, so a box nested in another and the snap grid behave the same.
 * - Smooth is a Catmull-Rom curve (tension one half) written as cubic Beziers; a line with no waypoints is always straight.
 * - The server draws the same line with a Python copy (`diagram_line_path.py`); `graphLinePathCases.json` holds the cases
 *   both are tested against, so a change to the rule is made in both.
 */

/** The most waypoints one line may have. */
export const MAX_WAYPOINTS = 16;

/** A position in canvas units. */
export interface LinePoint {
  x: number;
  y: number;
}

/** A number rounded to two decimals with no trailing zeros (`-0` is written `0`), as the server writes it. */
function n(value: number): string {
  const text = String(Math.round(value * 100) / 100);
  return text === "-0" ? "0" : text;
}

function p(point: LinePoint): string {
  return `${n(point.x)} ${n(point.y)}`;
}

/**
 * The SVG path of a line from `start` to `end` through `points`.
 *
 * @param start The point on the source box.
 * @param points The waypoints in order from the source to the target (may be empty).
 * @param end The point on the target box.
 * @param smooth True for a curve through every point, false for straight segments.
 * @returns `M … L …` for straight segments (and for a line with no waypoints), `M … C …` for a smooth line.
 */
export function linePath(start: LinePoint, points: readonly LinePoint[], end: LinePoint, smooth: boolean): string {
  const nodes = [start, ...points, end];
  if (!smooth || points.length === 0) return `M ${nodes.map(p).join(" L ")}`;
  const parts = [`M ${p(nodes[0])}`];
  for (let i = 0; i < nodes.length - 1; i += 1) {
    const p0 = i > 0 ? nodes[i - 1] : nodes[i];
    const p1 = nodes[i];
    const p2 = nodes[i + 1];
    const p3 = i + 2 < nodes.length ? nodes[i + 2] : nodes[i + 1];
    const c1 = { x: p1.x + (p2.x - p0.x) / 6, y: p1.y + (p2.y - p0.y) / 6 };
    const c2 = { x: p2.x - (p3.x - p1.x) / 6, y: p2.y - (p3.y - p1.y) / 6 };
    parts.push(`C ${p(c1)} ${p(c2)} ${p(p2)}`);
  }
  return parts.join(" ");
}

/**
 * The point half way along the straight segments from `start` through `points` to `end` (the label position).
 *
 * @returns The start when the line has no length.
 */
export function lineMiddle(start: LinePoint, points: readonly LinePoint[], end: LinePoint): LinePoint {
  const nodes = [start, ...points, end];
  const lengths = nodes.slice(0, -1).map((a, i) => Math.hypot(nodes[i + 1].x - a.x, nodes[i + 1].y - a.y));
  const total = lengths.reduce((sum, length) => sum + length, 0);
  if (total === 0) return start;
  let remaining = total / 2;
  for (let i = 0; i < lengths.length; i += 1) {
    if (remaining <= lengths[i] || i === lengths.length - 1) {
      const t = lengths[i] === 0 ? 0 : Math.min(remaining / lengths[i], 1);
      const a = nodes[i];
      const b = nodes[i + 1];
      return { x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t };
    }
    remaining -= lengths[i];
  }
  return end;
}

/** The middle of each segment of a line, in order (`points.length + 1` of them): where a drag inserts a vertex. */
export function segmentMiddles(start: LinePoint, points: readonly LinePoint[], end: LinePoint): LinePoint[] {
  const nodes = [start, ...points, end];
  return nodes.slice(0, -1).map((a, i) => ({ x: (a.x + nodes[i + 1].x) / 2, y: (a.y + nodes[i + 1].y) / 2 }));
}

/**
 * A route with a waypoint added at `index` (0 is before the first).
 *
 * @returns The same route when it already has `MAX_WAYPOINTS`.
 */
export function insertWaypoint(points: readonly LinePoint[], index: number, point: LinePoint): LinePoint[] {
  if (points.length >= MAX_WAYPOINTS) return [...points];
  const at = Math.max(0, Math.min(index, points.length));
  return [...points.slice(0, at), point, ...points.slice(at)];
}

/** A route with the waypoint at `index` moved to `point`. */
export function moveWaypoint(points: readonly LinePoint[], index: number, point: LinePoint): LinePoint[] {
  return points.map((existing, i) => (i === index ? point : existing));
}

/** A route with the waypoint at `index` removed. */
export function removeWaypoint(points: readonly LinePoint[], index: number): LinePoint[] {
  return points.filter((_, i) => i !== index);
}

/** How far below the middle of a segment an added vertex is placed, so the new vertex can be seen and picked up. */
export const NEW_WAYPOINT_DROP = 40;

/**
 * Where a vertex added without a pointer goes: the middle of the line's last segment, dropped by `NEW_WAYPOINT_DROP`
 * (the end the line is drawn toward is where a next vertex is most often wanted), on whole units.
 */
export function suggestWaypoint(start: LinePoint, points: readonly LinePoint[], end: LinePoint): LinePoint {
  const [last] = segmentMiddles(points.length > 0 ? points[points.length - 1] : start, [], end);
  return { x: Math.round(last.x), y: Math.round(last.y) + NEW_WAYPOINT_DROP };
}

/** The route reversed, for a line stored the other way round (a stored route runs from its stored source to its target). */
export function reverseRoute(points: readonly LinePoint[]): LinePoint[] {
  return [...points].reverse();
}
