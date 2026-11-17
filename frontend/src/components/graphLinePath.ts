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
 *   them (straight with none); Curved is that same curve through the waypoints when there are any and, with none, one arc bowed to
 *   the left of the line's direction (`bowSpan`). A line stores its own shape or none, which follows its diagram's default.
 * - The server draws the same line with a Python copy (`diagram_line_path.py`); `graphLinePathCases.json` holds the cases
 *   both are tested against, so a change to the rule is made in both.
 */

/** The most waypoints one line may have. */
export const MAX_WAYPOINTS = 16;

/** How a line runs between its ends: segments through its vertices, a bowed arc or a curve through the vertices. */
export type LineShape = "straight" | "curved" | "spline";

/** Every shape in the order a choice lists them. */
export const LINE_SHAPES: readonly LineShape[] = ["straight", "curved", "spline"];

/** How far a Curved line with no vertices bows from its chord, as a fraction of the chord's length, and the most it may bow. */
export const BOW_RATIO = 0.25;
export const BOW_LIMIT = 60;

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

/**
 * The one span of a Curved line that has no vertices: an arc bowed to the left of the direction of travel. The control points
 * are a third and two thirds of the way along the chord, each moved sideways by the bow, so the curve leaves the chord by three
 * quarters of it at its middle.
 *
 * @returns The span, or null when the two points coincide (nothing to bow).
 */
export function bowSpan(start: LinePoint, end: LinePoint): CurveSpan | null {
  const dx = end.x - start.x;
  const dy = end.y - start.y;
  const length = Math.sqrt(dx * dx + dy * dy);
  if (length === 0) return null;
  const bow = Math.min(length * BOW_RATIO, BOW_LIMIT);
  const nx = (dy / length) * bow;
  const ny = (-dx / length) * bow;
  return [
    start,
    { x: start.x + dx / 3 + nx, y: start.y + dy / 3 + ny },
    { x: start.x + (dx * 2) / 3 + nx, y: start.y + (dy * 2) / 3 + ny },
    end,
  ];
}

/**
 * The cubic spans a line of `shape` is drawn with, or none when it is drawn as straight segments: Spline gives the Catmull-Rom
 * spans through the vertices (none without vertices); Curved gives the same spans, or the single bowed arc without vertices.
 */
export function shapeSpans(start: LinePoint, points: readonly LinePoint[], end: LinePoint, shape: LineShape): CurveSpan[] {
  if (shape === "straight") return [];
  if (points.length > 0) return curveSpans(start, points, end);
  if (shape === "curved") {
    const arc = bowSpan(start, end);
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
 * @returns `M … L …` for straight segments (and for a line that has nothing to curve), `M … C …` for a curved one.
 */
export function linePath(start: LinePoint, points: readonly LinePoint[], end: LinePoint, shape: LineShape = "straight"): string {
  const spans = shapeSpans(start, points, end, shape);
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
export function lineMiddle(start: LinePoint, points: readonly LinePoint[], end: LinePoint, shape: LineShape = "straight"): LinePoint {
  if (shape === "curved" && points.length === 0) {
    const arc = bowSpan(start, end);
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
 * no vertices has one, on its arc, so the handle sits on the line that is drawn.
 */
export function segmentMiddles(start: LinePoint, points: readonly LinePoint[], end: LinePoint, shape: LineShape = "straight"): LinePoint[] {
  if (shape === "curved" && points.length === 0) {
    const arc = bowSpan(start, end);
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
