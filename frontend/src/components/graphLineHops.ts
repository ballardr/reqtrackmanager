/**
 * Module: components/graphLineHops
 *
 * Where one drawn line crosses another and which of the two draws a small arc over the other (a hop), so a crossing reads as
 * a crossing and not as a junction. Pure functions, no React, so the canvas and the tests use the one rule.
 *
 * Responsibilities:
 * - Flatten each line (curves included) to segments, find where segments of different lines cross, and decide which crossings
 *   are drawn as a hop.
 * - Give the SVG path of each line that hops, with the arcs in place.
 *
 * Design decisions:
 * - One rule for every line: connections, transitions and leaders are all lines of one set; a line never hops over itself, and
 *   a loop on one box is not in the set.
 * - The later line hops: of two lines that cross, the one whose id sorts later is drawn with the arc, so the same crossing looks
 *   the same on every screen and in every export.
 * - No hop where it would not read: none within `HOP_CLEARANCE` canvas units (along the line) of either line's end, between two
 *   lines that share an end point, where the arc would not fit inside one segment or one curve span of the hopping line, or
 *   closer than one arc's width to the previous hop of that line.
 * - Arcs are semicircles that bulge up for a line running left to right and right for one running top to bottom.
 * - The server draws the same hops with a Python copy (`diagram_line_hops.py`); `graphLineHopCases.json` holds the cases both
 *   are tested against, so a change to the rule is made in both. Only +, -, *, / and square roots are used so both agree.
 * - Not quadratic in the number of lines: segments are put in a grid of cells and only segments sharing a cell are compared; a
 *   segment that covers more than `MAX_CELLS` cells is compared with every other segment instead.
 */

import { curveSpans, formatPoint, type LinePoint } from "./graphLinePath";

/** Radius of a hop in canvas units (the arc is a semicircle, so it is twice this wide). */
export const HOP_RADIUS = 6;
/** A hop is not drawn within this distance, along a line, of either line's end. */
export const HOP_CLEARANCE = 12;
/** Straight pieces a curve span is cut into. */
const CURVE_STEPS = 16;
/** Width and height of a cell of the grid the segments are put in. */
const CELL = 64;
/** Two end points this close (canvas units) are the same end. */
const SHARED_END = 1;
/** A segment that covers more cells than this is compared with every other segment, not put in the grid. */
const MAX_CELLS = 256;

/** One line of the drawing: its id (the order of hopping) and the geometry `linePath` draws. */
export interface HopLine {
  id: string;
  start: LinePoint;
  points: readonly LinePoint[];
  end: LinePoint;
  smooth: boolean;
}

/** A line cut into segments: its points, the length along it at each, and the index range of each piece a hop must fit inside. */
interface Flat {
  poly: LinePoint[];
  cum: number[];
  pieces: [number, number][];
}

/** The line as straight segments, with a curve cut into `CURVE_STEPS` pieces per span. */
function flatten(line: HopLine): Flat {
  const nodes = [line.start, ...line.points, line.end];
  const poly: LinePoint[] = [nodes[0]];
  const pieces: [number, number][] = [];
  if (!line.smooth || line.points.length === 0) {
    for (let i = 1; i < nodes.length; i += 1) {
      pieces.push([i - 1, i]);
      poly.push(nodes[i]);
    }
  } else {
    for (const [p1, c1, c2, p2] of curveSpans(line.start, line.points, line.end)) {
      const first = poly.length - 1;
      for (let step = 1; step <= CURVE_STEPS; step += 1) {
        const t = step / CURVE_STEPS;
        const mt = 1 - t;
        const a = mt * mt * mt;
        const b = 3 * mt * mt * t;
        const c = 3 * mt * t * t;
        const d = t * t * t;
        poly.push({ x: a * p1.x + b * c1.x + c * c2.x + d * p2.x, y: a * p1.y + b * c1.y + c * c2.y + d * p2.y });
      }
      pieces.push([first, poly.length - 1]);
    }
  }
  const cum = [0];
  for (let i = 1; i < poly.length; i += 1) {
    const dx = poly[i].x - poly[i - 1].x;
    const dy = poly[i].y - poly[i - 1].y;
    cum.push(cum[cum.length - 1] + Math.sqrt(dx * dx + dy * dy));
  }
  return { poly, cum, pieces };
}

/**
 * Where segment `a`-`b` crosses segment `c`-`d`: the fraction of each at the crossing, or null for a pair that is parallel or
 * does not cross. A crossing at the very start of a segment counts for that segment, so one at a shared vertex is found once.
 */
function crossing(a: LinePoint, b: LinePoint, c: LinePoint, d: LinePoint): [number, number] | null {
  const rx = b.x - a.x;
  const ry = b.y - a.y;
  const sx = d.x - c.x;
  const sy = d.y - c.y;
  const denominator = rx * sy - ry * sx;
  if (denominator === 0) return null;
  const qx = c.x - a.x;
  const qy = c.y - a.y;
  const t = (qx * sy - qy * sx) / denominator;
  const u = (qx * ry - qy * rx) / denominator;
  if (t < 0 || t >= 1 || u < 0 || u >= 1) return null;
  return [t, u];
}

function near(a: LinePoint, b: LinePoint): boolean {
  const dx = a.x - b.x;
  const dy = a.y - b.y;
  return dx * dx + dy * dy <= SHARED_END * SHARED_END;
}

/** The point at length `s` along the line. */
function pointAt(flat: Flat, s: number): LinePoint {
  const { cum, poly } = flat;
  let k = 0;
  while (k < poly.length - 2 && cum[k + 1] < s) k += 1;
  const length = cum[k + 1] - cum[k];
  const t = length === 0 ? 0 : (s - cum[k]) / length;
  const a = poly[k];
  const b = poly[k + 1];
  return { x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t };
}

/** Whether the arc around length `s` lies inside one straight segment or one curve span. */
function fitsInAPiece(flat: Flat, s: number): boolean {
  for (const [first, last] of flat.pieces) {
    if (s <= flat.cum[last]) return s - HOP_RADIUS >= flat.cum[first] && s + HOP_RADIUS <= flat.cum[last];
  }
  return false;
}

/** The line's path with an arc at each length in `hops` (ascending). */
function hopPath(flat: Flat, hops: number[]): string {
  const { poly, cum } = flat;
  const out = [`M ${formatPoint(poly[0])}`];
  let k = 1;
  for (const s of hops) {
    const before = s - HOP_RADIUS;
    const after = s + HOP_RADIUS;
    while (k < poly.length && cum[k] <= before) {
      out.push(`L ${formatPoint(poly[k])}`);
      k += 1;
    }
    const start = pointAt(flat, before);
    const end = pointAt(flat, after);
    const dx = end.x - start.x;
    const dy = end.y - start.y;
    const sweep = dx > 0 || (dx === 0 && dy > 0) ? 1 : 0;
    out.push(`L ${formatPoint(start)} A ${formatPoint({ x: HOP_RADIUS, y: HOP_RADIUS })} 0 0 ${sweep} ${formatPoint(end)}`);
    while (k < poly.length && cum[k] <= after) k += 1;
  }
  while (k < poly.length) {
    out.push(`L ${formatPoint(poly[k])}`);
    k += 1;
  }
  return out.join(" ");
}

/**
 * The paths of the lines that hop over another line.
 *
 * @param lines Every line of the drawing (ids are unique).
 * @returns The SVG path (`M … L … A …`, the line flattened to segments) of each line that has at least one hop, by id. A line
 *   with no hop is absent and is drawn as `linePath` draws it.
 */
export function lineHops(lines: readonly HopLine[]): Map<string, string> {
  const flats = lines.map(flatten);
  const segments: [number, number][] = [];
  const grid = new Map<string, number[]>();
  const longSegments: number[] = [];
  flats.forEach((flat, i) => {
    if (flat.cum[flat.cum.length - 1] === 0) return;
    for (let k = 0; k < flat.poly.length - 1; k += 1) {
      const a = flat.poly[k];
      const b = flat.poly[k + 1];
      const index = segments.length;
      segments.push([i, k]);
      const x0 = Math.floor(Math.min(a.x, b.x) / CELL);
      const x1 = Math.floor(Math.max(a.x, b.x) / CELL);
      const y0 = Math.floor(Math.min(a.y, b.y) / CELL);
      const y1 = Math.floor(Math.max(a.y, b.y) / CELL);
      if ((x1 - x0 + 1) * (y1 - y0 + 1) > MAX_CELLS) {
        longSegments.push(index);
        continue;
      }
      for (let cx = x0; cx <= x1; cx += 1) {
        for (let cy = y0; cy <= y1; cy += 1) {
          const key = `${cx},${cy}`;
          const members = grid.get(key);
          if (members) members.push(index);
          else grid.set(key, [index]);
        }
      }
    }
  });

  const count = segments.length;
  const pairs = new Set<number>();
  const add = (g: number, h: number) => pairs.add(g < h ? g * count + h : h * count + g);
  for (const members of grid.values()) {
    for (let p = 0; p < members.length; p += 1) for (let q = p + 1; q < members.length; q += 1) add(members[p], members[q]);
  }
  for (const g of longSegments) for (let other = 0; other < count; other += 1) if (other !== g) add(g, other);

  const sharesEnd = new Map<number, boolean>();
  const hops = new Map<number, number[]>();
  for (const code of pairs) {
    const [i, k] = segments[Math.floor(code / count)];
    const [j, m] = segments[code % count];
    if (i === j) continue;
    const fi = flats[i];
    const fj = flats[j];
    const found = crossing(fi.poly[k], fi.poly[k + 1], fj.poly[m], fj.poly[m + 1]);
    if (found === null) continue;
    const key = i < j ? i * lines.length + j : j * lines.length + i;
    let shared = sharesEnd.get(key);
    if (shared === undefined) {
      const endsI = [lines[i].start, lines[i].end];
      const endsJ = [lines[j].start, lines[j].end];
      shared = endsI.some((a) => endsJ.some((b) => near(a, b)));
      sharesEnd.set(key, shared);
    }
    if (shared) continue;
    const sI = fi.cum[k] + found[0] * (fi.cum[k + 1] - fi.cum[k]);
    const sJ = fj.cum[m] + found[1] * (fj.cum[m + 1] - fj.cum[m]);
    const clear = (s: number, f: Flat) => HOP_CLEARANCE <= s && s <= f.cum[f.cum.length - 1] - HOP_CLEARANCE;
    if (!clear(sI, fi) || !clear(sJ, fj)) continue;
    const [hopper, s] = lines[i].id > lines[j].id ? [i, sI] : [j, sJ];
    if (!fitsInAPiece(flats[hopper], s)) continue;
    const list = hops.get(hopper);
    if (list) list.push(s);
    else hops.set(hopper, [s]);
  }

  const paths = new Map<string, string>();
  for (const [i, foundAt] of hops) {
    const kept: number[] = [];
    for (const s of [...foundAt].sort((a, b) => a - b)) {
      if (kept.length === 0 || s - kept[kept.length - 1] >= 2 * HOP_RADIUS) kept.push(s);
    }
    paths.set(lines[i].id, hopPath(flats[i], kept));
  }
  return paths;
}
