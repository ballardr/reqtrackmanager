/**
 * Module: components/graphLinePath
 *
 * The shape of a drawn line that has waypoints on the shared graph canvas. Pure functions, no React, so the canvas, the
 * editors and the tests use the one rule.
 *
 * Responsibilities:
 * - Turn a line's two end points, its ordered waypoints and its shape (Straight, Curved or Spline) into an SVG path.
 * - Give the middle of the line, where a label and a comment pin sit, and the middle of each segment (where a drag adds a vertex).
 * - Resolve a line's own shape against its diagram's default.
 * - Offer the edits a route allows: insert, move and remove a waypoint, within the cap.
 *
 * Design decisions:
 * - Coordinates are absolute canvas units, so a box nested in another and the snap grid behave the same.
 * - Straight is segments through the waypoints; Spline is a Catmull-Rom curve (tension one half) written as cubic Beziers through
 *   them (straight with none) with free ends. Curved leaves each box along its outward direction (`graphAttachPoints`'
 *   `outwardDirection`, passed as `LineDirections`): with no vertices it is one cubic whose control points lie that direction from
 *   each end (`outwardSpan`), so boxes facing each other give a straight line and a line bends only as much as the boxes need; with
 *   vertices it is the Spline through them with its two end tangents set to those directions. Without directions a Curved line
 *   with no vertices is straight. A line stores its own shape or none, which follows its diagram's default.
 * - The server draws the same line with a Python copy (`diagram_line_path.py`); `graphLinePathCases.json` holds the cases
 *   both are tested against, so a change to the rule is made in both.
 */

/** The most waypoints one line may have. */
export const MAX_WAYPOINTS = 16;

/** How a line runs between its ends: segments through its vertices, a curve leaving each box outward, or a curve through the vertices with free ends. */
export type LineShape = "straight" | "curved" | "spline";

/** Every shape in the order a choice lists them. */
export const LINE_SHAPES: readonly LineShape[] = ["straight", "curved", "spline"];

/**
 * How far a Curved line's control points sit from its ends along the outward directions: this fraction of the chord, kept between
 * the minimum and the maximum (canvas units), so a short line still has room to turn and a long one does not swing wide.
 */
export const HANDLE_RATIO = 0.4;
export const HANDLE_MIN = 24;
export const HANDLE_MAX = 120;

/**
 * The shape a line is drawn in: its own when it has one, else its diagram's default.
 *
 * @param own The line's stored shape, or null/undefined to follow the diagram.
 * @param fallback The diagram's default shape.
 */
export function effectiveShape(own: LineShape | null | undefined, fallback: LineShape): LineShape {
  return own ?? fallback;
}

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

/** A point as the two numbers of an SVG path command, written by the one rounding rule. */
export function formatPoint(point: LinePoint): string {
  return p(point);
}

/** One cubic Bezier span of a curved line: where it starts, its two control points and where it ends. */
export type CurveSpan = readonly [LinePoint, LinePoint, LinePoint, LinePoint];

/** The directions a line leaves its two ends in (unit vectors out of each box); an end with none is left to the line itself. */
export interface LineDirections {
  start?: LinePoint | null;
  end?: LinePoint | null;
}

/**
 * The one span of a Curved line that has no vertices: a cubic leaving `start` along its outward direction and arriving at `end`
 * along its own, the control points `handle` from each end. An end with no direction leaves or arrives along the chord, so a line
 * with one known end still bends only at that end; with neither it is straight.
 *
 * @returns The span, or null when the two points coincide or no end has a direction (a straight line).
 */
export function outwardSpan(start: LinePoint, end: LinePoint, directions?: LineDirections): CurveSpan | null {
  const dx = end.x - start.x;
  const dy = end.y - start.y;
  const length = Math.sqrt(dx * dx + dy * dy);
  const from = directions?.start ?? null;
  const to = directions?.end ?? null;
  if (length === 0 || (!from && !to)) return null;
  const ux = dx / length;
  const uy = dy / length;
  const out = from ?? { x: ux, y: uy };
  const back = to ?? { x: -ux, y: -uy };
  const handle = Math.min(Math.max(length * HANDLE_RATIO, HANDLE_MIN), HANDLE_MAX);
  return [
    start,
    { x: start.x + out.x * handle, y: start.y + out.y * handle },
    { x: end.x + back.x * handle, y: end.y + back.y * handle },
    end,
  ];
}

/** `spans` with the first leaving `start` along `directions.start` and the last arriving along `directions.end`, a third of the span's length from the end. */
function withEndTangents(spans: CurveSpan[], directions?: LineDirections): CurveSpan[] {
  if (!directions || spans.length === 0) return spans;
  const out = spans.map(([a, b, c, d]): [LinePoint, LinePoint, LinePoint, LinePoint] => [a, b, c, d]);
  const length = (a: LinePoint, b: LinePoint) => Math.sqrt((b.x - a.x) ** 2 + (b.y - a.y) ** 2);
  if (directions.start) {
    const span = out[0];
    const third = length(span[0], span[3]) / 3;
    span[1] = { x: span[0].x + directions.start.x * third, y: span[0].y + directions.start.y * third };
  }
  if (directions.end) {
    const span = out[out.length - 1];
    const third = length(span[0], span[3]) / 3;
    span[2] = { x: span[3].x + directions.end.x * third, y: span[3].y + directions.end.y * third };
  }
  return out;
}

/**
 * The cubic spans a line of `shape` is drawn with, or none when it is drawn as straight segments: Spline gives the Catmull-Rom
 * spans through the vertices (none without vertices); Curved gives those spans with the end tangents along `directions`, or the
 * single outward span without vertices.
 */
export function shapeSpans(
  start: LinePoint, points: readonly LinePoint[], end: LinePoint, shape: LineShape, directions?: LineDirections,
): CurveSpan[] {
  if (shape === "straight") return [];
  if (points.length > 0) {
    const spans = curveSpans(start, points, end);
    return shape === "curved" ? withEndTangents(spans, directions) : spans;
  }
  if (shape === "curved") {
    const arc = outwardSpan(start, end, directions);
    return arc ? [arc] : [];
  }
  return [];
}

/**
 * The cubic Bezier spans of a smooth line through `start`, `points` and `end`, one per segment. The ends of a span are the
 * line's own points, so the curve passes through every one.
 */
export function curveSpans(start: LinePoint, points: readonly LinePoint[], end: LinePoint): CurveSpan[] {
  const nodes = [start, ...points, end];
  const spans: CurveSpan[] = [];
  for (let i = 0; i < nodes.length - 1; i += 1) {
    const p0 = i > 0 ? nodes[i - 1] : nodes[i];
    const p1 = nodes[i];
    const p2 = nodes[i + 1];
    const p3 = i + 2 < nodes.length ? nodes[i + 2] : nodes[i + 1];
    const c1 = { x: p1.x + (p2.x - p0.x) / 6, y: p1.y + (p2.y - p0.y) / 6 };
    const c2 = { x: p2.x - (p3.x - p1.x) / 6, y: p2.y - (p3.y - p1.y) / 6 };
    spans.push([p1, c1, c2, p2]);
  }
  return spans;
}

/**
 * The SVG path of a line from `start` to `end` through `points`.
 *
 * @param start The point on the source box.
 * @param points The waypoints in order from the source to the target (may be empty).
 * @param end The point on the target box.
 * @param shape How the line runs between the points.
 * @param directions The directions the line leaves its boxes in, which a Curved line follows.
 * @returns `M … L …` for straight segments (and for a line that has nothing to curve), `M … C …` for a curved one.
 */
export function linePath(
  start: LinePoint, points: readonly LinePoint[], end: LinePoint, shape: LineShape = "straight", directions?: LineDirections,
): string {
  const spans = shapeSpans(start, points, end, shape, directions);
  if (spans.length === 0) return `M ${[start, ...points, end].map(p).join(" L ")}`;
  const parts = [`M ${p(start)}`];
  for (const [, c1, c2, p2] of spans) parts.push(`C ${p(c1)} ${p(c2)} ${p(p2)}`);
  return parts.join(" ");
}

/**
 * The point half way along the straight segments from `start` through `points` to `end` (the label position).
 *
 * A curve through vertices takes its middle on the straight segments too, so the label stays close to it; a Curved line with no
 * vertices has its label on the arc itself (`(start + 3 c1 + 3 c2 + end) / 8`).
 *
 * @returns The start when the line has no length.
 */
export function lineMiddle(
  start: LinePoint, points: readonly LinePoint[], end: LinePoint, shape: LineShape = "straight", directions?: LineDirections,
): LinePoint {
  if (shape === "curved" && points.length === 0) {
    const arc = outwardSpan(start, end, directions);
    if (arc) return arcMiddle(arc);
  }
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

/** The point half way along one cubic span (`t = 1/2`). */
function arcMiddle([a, c1, c2, b]: CurveSpan): LinePoint {
  return { x: (a.x + 3 * c1.x + 3 * c2.x + b.x) / 8, y: (a.y + 3 * c1.y + 3 * c2.y + b.y) / 8 };
}

/**
 * The middle of each segment of a line, in order (`points.length + 1` of them): where a drag inserts a vertex. A Curved line with
 * no vertices has one, on its curve, so the handle sits on the line that is drawn.
 */
export function segmentMiddles(
  start: LinePoint, points: readonly LinePoint[], end: LinePoint, shape: LineShape = "straight", directions?: LineDirections,
): LinePoint[] {
  if (shape === "curved" && points.length === 0) {
    const arc = outwardSpan(start, end, directions);
    if (arc) return [arcMiddle(arc)];
  }
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
