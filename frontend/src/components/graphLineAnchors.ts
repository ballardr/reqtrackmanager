/**
 * Module: components/graphLineAnchors
 *
 * Where every line of a drawing meets its boxes so that no two lines draw over each other. Pure functions, no React, so the
 * canvas, a consumer's selection panel and the tests all use the one rule.
 *
 * Responsibilities:
 * - Choose, for each line between two boxes, the attach point at each end (`graphAttachPoints` gives the points and the rule
 *   for one line on its own) while looking at every other line of the drawing.
 * - Spread lines that still share both ends sideways in parallel lanes (`shift`).
 * - Give each loop (a line from a box back to itself) a slot, so several loops on one box take different corners.
 * - Say which point an end would take if a person left it automatic (`automaticEnds`), for a selection card.
 *
 * Design decisions:
 * - **One rule, two implementations.** The server draws the same lines with `diagram_line_anchors.py`;
 *   `graphLineAnchorCases.json` holds the cases both are tested against, so a change to the rule is made in both. Only +, -, *,
 *   / and square roots are used so both agree to the last bit.
 * - **A person's choice is never moved.** An end a person fixed keeps its point, and a line with vertices is the person's own
 *   drawing: its ends follow the vertices and it is never spread. Both still count as using their points, so an automatic line
 *   keeps clear of them whatever the order of the lines.
 * - **Automatic lines are placed in the order given**, each choosing the pair of free points nearest each other (the facing
 *   sides first, as for a single line). A point that is already the end of another line is used only when no free pair is
 *   left, and then the least used pair is taken. Callers pass the lines in the order they were created, so adding a line
 *   moves no earlier line (except to keep clear of an end a person fixed).
 * - **Lanes are the last resort.** Two lines that end on the same two points are shifted sideways in parallel, `LANE_GAP`
 *   units apart, along the normal of the direction from the lower-ordered end to the other, so a line in each direction is
 *   shifted to its own side.
 */

import type { GraphCanvasEdge, GraphCanvasNode } from "./GraphCanvas";
import { ATTACH_POINTS, SIDE_POINTS, pointXY, routeAttachPoints, type AttachPoint, type BoxGeometry } from "./graphAttachPoints";
import type { LinePoint } from "./graphLinePath";

/** The size of a node that gives none, in canvas units. */
export const DEFAULT_BOX_WIDTH = 160;
export const DEFAULT_BOX_HEIGHT = 64;

/** The distance between two parallel lanes, in canvas units. */
export const LANE_GAP = 16;

/** A distance must be smaller than the best so far by more than this to win, so equal distances keep the earlier pair. */
const TOLERANCE = 1e-6;

/** A line to place: its id, its two boxes, the points a person fixed (null or undefined for automatic) and its vertices. */
export interface AnchorLine {
  id: string;
  source: string;
  target: string;
  sourcePoint?: AttachPoint | null;
  targetPoint?: AttachPoint | null;
  points?: readonly LinePoint[];
}

/** Where one line meets its boxes. A loop has a `loopSlot` (0 is the top right corner) and no meaningful points or shift. */
export interface LineAnchor {
  source: AttachPoint;
  target: AttachPoint;
  /** The sideways shift of the line's lane, applied to both ends. */
  shift: LinePoint;
  loopSlot?: number;
}

const squared = (a: LinePoint, b: LinePoint): number => (a.x - b.x) ** 2 + (a.y - b.y) ** 2;

/**
 * Places every line of a drawing.
 *
 * @param boxes Every box by id (`points` narrows what an automatic end may choose).
 * @param lines The lines in the order they were created (the order decides who keeps a point when the choice is a tie).
 * @returns The anchor of each line by id (a line whose box is missing is not in the result).
 */
export function assignLineAnchors(boxes: ReadonlyMap<string, BoxGeometry>, lines: readonly AnchorLine[]): Map<string, LineAnchor> {
  const used = new Map<string, number>();
  const key = (boxId: string, point: AttachPoint) => `${boxId}\u0000${point}`;
  const claim = (boxId: string, point: AttachPoint) => used.set(key(boxId, point), (used.get(key(boxId, point)) ?? 0) + 1);
  const placed = new Map<string, [AttachPoint, AttachPoint]>();
  const result = new Map<string, LineAnchor>();
  const loopsOn = new Map<string, number>();
  const pending: AnchorLine[] = [];

  for (const line of lines) {
    const a = boxes.get(line.source);
    const b = boxes.get(line.target);
    if (!a || !b) continue;
    const via = line.points ?? [];
    if (line.source === line.target) {
      const slot = loopsOn.get(line.source) ?? 0;
      loopsOn.set(line.source, slot + 1);
      result.set(line.id, { source: "top", target: "top", shift: { x: 0, y: 0 }, loopSlot: slot });
    } else if (via.length > 0) {
      const ends = routeAttachPoints(a, b, line.sourcePoint, line.targetPoint, via);
      placed.set(line.id, ends);
      claim(line.source, ends[0]);
      claim(line.target, ends[1]);
    } else if (line.sourcePoint && line.targetPoint) {
      placed.set(line.id, [line.sourcePoint, line.targetPoint]);
      claim(line.source, line.sourcePoint);
      claim(line.target, line.targetPoint);
    } else {
      if (line.sourcePoint) claim(line.source, line.sourcePoint);
      if (line.targetPoint) claim(line.target, line.targetPoint);
      pending.push(line);
    }
  }

  for (const line of pending) {
    const a = boxes.get(line.source) as BoxGeometry;
    const b = boxes.get(line.target) as BoxGeometry;
    const sources = line.sourcePoint ? [line.sourcePoint] : a.points ?? ATTACH_POINTS;
    const targets = line.targetPoint ? [line.targetPoint] : b.points ?? ATTACH_POINTS;
    let best: { total: number; distance: number } | null = null;
    let chosen: [AttachPoint, AttachPoint] = [sources[0], targets[0]];
    for (const pa of sources) {
      const usedA = line.sourcePoint ? 0 : used.get(key(line.source, pa)) ?? 0;
      const xyA = pointXY(a, pa);
      for (const pb of targets) {
        const total = usedA + (line.targetPoint ? 0 : used.get(key(line.target, pb)) ?? 0);
        const distance = squared(xyA, pointXY(b, pb));
        if (best === null || total < best.total || (total === best.total && distance < best.distance - TOLERANCE)) {
          best = { total, distance };
          chosen = [pa, pb];
        }
      }
    }
    placed.set(line.id, chosen);
    if (!line.sourcePoint) claim(line.source, chosen[0]);
    if (!line.targetPoint) claim(line.target, chosen[1]);
  }

  // Lines left on the same two points are spread into lanes, in the order they were given.
  type End = { box: string; point: AttachPoint };
  const groups = new Map<string, AnchorLine[]>();
  const endsOf = new Map<string, [End, End]>();
  const before = (x: End, y: End) => (x.box !== y.box ? x.box < y.box : x.point < y.point);
  for (const line of lines) {
    const ends = placed.get(line.id);
    if (!ends || (line.points ?? []).length > 0 || line.source === line.target) continue;
    const one: End = { box: line.source, point: ends[0] };
    const two: End = { box: line.target, point: ends[1] };
    const ordered: [End, End] = before(two, one) ? [two, one] : [one, two];
    endsOf.set(line.id, ordered);
    const groupKey = `${ordered[0].box}\u0000${ordered[0].point}\u0000${ordered[1].box}\u0000${ordered[1].point}`;
    groups.set(groupKey, [...(groups.get(groupKey) ?? []), line]);
  }
  for (const members of groups.values()) {
    const [first, second] = endsOf.get(members[0].id) as [End, End];
    const p1 = pointXY(boxes.get(first.box) as BoxGeometry, first.point);
    const p2 = pointXY(boxes.get(second.box) as BoxGeometry, second.point);
    const length = Math.sqrt((p2.x - p1.x) * (p2.x - p1.x) + (p2.y - p1.y) * (p2.y - p1.y)) || 1;
    members.forEach((line, rank) => {
      const offset = (rank - (members.length - 1) / 2) * LANE_GAP;
      const shift = offset === 0 ? { x: 0, y: 0 } : { x: (-(p2.y - p1.y) / length) * offset + 0, y: ((p2.x - p1.x) / length) * offset + 0 };
      const [a, b] = placed.get(line.id) as [AttachPoint, AttachPoint];
      result.set(line.id, { source: a, target: b, shift });
    });
  }
  for (const line of lines) {
    const ends = placed.get(line.id);
    if (ends && !result.has(line.id)) result.set(line.id, { source: ends[0], target: ends[1], shift: { x: 0, y: 0 } });
  }
  return result;
}

/**
 * The points each end of a line would take if it were left automatic, with every other line as it is.
 *
 * @param boxes Every box by id.
 * @param lines Every line, in creation order.
 * @param id The line asked about.
 * @returns `[source point, target point]`, or null when the line is a loop, has no box or is not in `lines`.
 */
export function automaticEnds(boxes: ReadonlyMap<string, BoxGeometry>, lines: readonly AnchorLine[], id: string): [AttachPoint, AttachPoint] | null {
  const index = lines.findIndex((l) => l.id === id);
  if (index < 0) return null;
  const line = lines[index];
  const with_ = (change: Partial<AnchorLine>) => assignLineAnchors(boxes, lines.map((l, i) => (i === index ? { ...line, ...change } : l))).get(id);
  const source = with_({ sourcePoint: null });
  const target = with_({ targetPoint: null });
  if (!source || !target || source.loopSlot !== undefined) return null;
  return [source.source, target.target];
}

/** @returns The boxes of the canvas nodes by id, as the canvas draws them (a marker offers only the middle of each side). */
export function canvasBoxes(nodes: readonly Pick<GraphCanvasNode, "id" | "x" | "y" | "width" | "height" | "marker" | "attachPoints">[]): Map<string, BoxGeometry> {
  return new Map(nodes.map((n) => [n.id, {
    x: n.x, y: n.y, width: n.width ?? DEFAULT_BOX_WIDTH, height: n.height ?? DEFAULT_BOX_HEIGHT,
    points: n.attachPoints ?? (n.marker ? SIDE_POINTS : undefined),
  }]));
}

/** @returns The canvas lines as lines to place, in the order given. */
export function canvasLines(edges: readonly GraphCanvasEdge[]): AnchorLine[] {
  return edges.map((e) => ({ id: e.id, source: e.source, target: e.target, sourcePoint: e.sourcePoint, targetPoint: e.targetPoint, points: e.points }));
}

/** The points a line's ends use now and the points they would take if left automatic. */
export interface LineEnds {
  current: [AttachPoint, AttachPoint];
  automatic: [AttachPoint, AttachPoint];
}

/**
 * The points each end of a canvas line uses and would use if it were left automatic: what a selection card's Automatic choice
 * shows. Built once for a set of nodes and lines.
 *
 * @returns A function from a line's id to its ends (null for a loop or an unknown line).
 */
export function lineEndsOf(
  nodes: readonly Pick<GraphCanvasNode, "id" | "x" | "y" | "width" | "height" | "marker" | "attachPoints">[], edges: readonly GraphCanvasEdge[],
): (id: string) => LineEnds | null {
  const boxes = canvasBoxes(nodes);
  const lines = canvasLines(edges);
  const placed = assignLineAnchors(boxes, lines);
  return (id) => {
    const now = placed.get(id);
    const automatic = automaticEnds(boxes, lines, id);
    return now && automatic && now.loopSlot === undefined ? { current: [now.source, now.target], automatic } : null;
  };
}
