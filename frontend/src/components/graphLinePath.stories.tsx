import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect } from "storybook/test";

import cases from "./graphLinePathCases.json";
import {
  effectiveShape, HANDLE_MAX, HANDLE_MIN, outwardSpan, insertWaypoint, lineMiddle, linePath, MAX_WAYPOINTS, moveWaypoint, NEW_WAYPOINT_DROP, removeWaypoint, reverseRoute, segmentMiddles, suggestWaypoint, type LineDirections, type LineShape,
} from "./graphLinePath";

/** One shared case: a line and the server's path and middle for it (see `graphLinePathCases.json`). */
interface Case {
  name: string;
  start: [number, number];
  points: [number, number][];
  end: [number, number];
  shape: LineShape;
  start_direction?: [number, number];
  end_direction?: [number, number];
  path: string;
  middle: [number, number];
}

const CASES = cases as unknown as Case[];
const pt = ([x, y]: [number, number]) => ({ x, y });

function Host() {
  return <p>Runs the browser line rule over every case the server's rule produced.</p>;
}

const meta: Meta<typeof Host> = { title: "Components/GraphLinePath", component: Host };
export default meta;

type Story = StoryObj<typeof Host>;

export const MatchesTheServersRuleOnEverySharedCase: Story = {
  play: async () => {
    const failures: string[] = [];
    for (const c of CASES) {
      const points = c.points.map(pt);
      const directions: LineDirections = { start: c.start_direction ? pt(c.start_direction) : null, end: c.end_direction ? pt(c.end_direction) : null };
      const path = linePath(pt(c.start), points, pt(c.end), c.shape, directions);
      if (path !== c.path) failures.push(`${c.name}: path ${path} is not ${c.path}`);
      const middle = lineMiddle(pt(c.start), points, pt(c.end), c.shape, directions);
      if (Math.abs(middle.x - c.middle[0]) > 1e-5 || Math.abs(middle.y - c.middle[1]) > 1e-5) failures.push(`${c.name}: middle`);
    }
    await expect(failures).toEqual([]);
    await expect(CASES.length).toBeGreaterThan(5);
  },
};

export const EditsARouteWithinTheCap: Story = {
  play: async () => {
    const a = { x: 0, y: 0 };
    const b = { x: 10, y: 10 };
    const c = { x: 20, y: 20 };
    await expect(insertWaypoint([a, c], 1, b)).toEqual([a, b, c]);
    await expect(insertWaypoint([a], 99, b)).toEqual([a, b]);
    await expect(moveWaypoint([a, b], 1, c)).toEqual([a, c]);
    await expect(removeWaypoint([a, b, c], 1)).toEqual([a, c]);
    await expect(reverseRoute([a, b, c])).toEqual([c, b, a]);
    const full = Array.from({ length: MAX_WAYPOINTS }, (_, i) => ({ x: i, y: i }));
    await expect(insertWaypoint(full, 0, a)).toEqual(full);
    await expect(segmentMiddles(a, [b], c)).toEqual([{ x: 5, y: 5 }, { x: 15, y: 15 }]);
    // An added vertex goes below the middle of the last segment.
    await expect(suggestWaypoint({ x: 0, y: 0 }, [], { x: 100, y: 0 })).toEqual({ x: 50, y: NEW_WAYPOINT_DROP });
    await expect(suggestWaypoint({ x: 0, y: 0 }, [{ x: 100, y: 0 }], { x: 100, y: 100 })).toEqual({ x: 100, y: 50 + NEW_WAYPOINT_DROP });
  },
};

const RIGHT = { x: 1, y: 0 };
const LEFT = { x: -1, y: 0 };
const UP = { x: 0, y: -1 };

export const ACurvedLineWithNoVerticesLeavesEachEndAlongItsDirection: Story = {
  play: async () => {
    // Boxes facing each other in line give a straight line (the control points lie on the chord), whichever way it is stored.
    const facing = outwardSpan({ x: 160, y: 40 }, { x: 300, y: 40 }, { start: RIGHT, end: LEFT });
    await expect(facing?.[1].y).toBe(40);
    await expect(facing?.[2].y).toBe(40);
    await expect(lineMiddle({ x: 160, y: 40 }, [], { x: 300, y: 40 }, "curved", { start: RIGHT, end: LEFT })).toEqual({ x: 230, y: 40 });
    // Offset boxes give an S that leaves both squarely, and the label and the vertex handle sit on the drawn curve.
    const offset = { start: RIGHT, end: LEFT };
    await expect(segmentMiddles({ x: 160, y: 40 }, [], { x: 300, y: 140 }, "curved", offset)).toEqual([{ x: 230, y: 90 }]);
    await expect(linePath({ x: 160, y: 40 }, [], { x: 300, y: 140 }, "curved", offset).split("C").length - 1).toBe(1);
    // Reversing the stored direction draws the same curve.
    const reversed = linePath({ x: 300, y: 140 }, [], { x: 160, y: 40 }, "curved", { start: LEFT, end: RIGHT });
    await expect(reversed).toBe("M 300 140 C 231.18 140 228.82 40 160 40");
    // The handle is bounded so a long line does not swing wide and a short one has room to turn.
    await expect(outwardSpan({ x: 0, y: 0 }, { x: 2000, y: 500 }, { start: RIGHT, end: LEFT })?.[1].x).toBe(HANDLE_MAX);
    await expect(outwardSpan({ x: 0, y: 0 }, { x: 20, y: 0 }, { start: RIGHT, end: LEFT })?.[1].x).toBe(HANDLE_MIN);
  },
};

export const ACurvedLineWithNothingToLeaveFromIsStraight: Story = {
  play: async () => {
    await expect(linePath({ x: 0, y: 0 }, [], { x: 100, y: 40 }, "curved")).toBe("M 0 0 L 100 40");
    await expect(outwardSpan({ x: 3, y: 3 }, { x: 3, y: 3 }, { start: RIGHT, end: LEFT })).toBeNull();
    // An end with no direction (a leader's free end) arrives along the chord.
    const span = outwardSpan({ x: 0, y: 0 }, { x: 200, y: 100 }, { start: UP, end: null });
    await expect(span?.[1].x).toBe(0);
    await expect((span?.[2].x ?? 0) < 200 && (span?.[2].y ?? 0) < 100).toBe(true);
  },
};

export const ACurvedLineWithVerticesIsTheSplineThroughThemWithOutwardEnds: Story = {
  play: async () => {
    const through = [{ x: 50, y: 60 }, { x: 80, y: 10 }];
    // Without directions it is the spline; with them only the two end tangents change, and a spline ignores them.
    await expect(linePath({ x: 0, y: 0 }, through, { x: 100, y: 0 }, "curved")).toBe(linePath({ x: 0, y: 0 }, through, { x: 100, y: 0 }, "spline"));
    const outward = { start: UP, end: UP };
    await expect(linePath({ x: 0, y: 0 }, through, { x: 100, y: 0 }, "spline", outward)).toBe(linePath({ x: 0, y: 0 }, through, { x: 100, y: 0 }, "spline"));
    const curved = linePath({ x: 0, y: 0 }, through, { x: 100, y: 0 }, "curved", outward);
    await expect(curved.startsWith("M 0 0 C 0 -")).toBe(true);
    await expect(curved.endsWith("100 0")).toBe(true);
    // A spline with nothing to curve through is straight.
    await expect(linePath({ x: 0, y: 0 }, [], { x: 100, y: 0 }, "spline")).toBe("M 0 0 L 100 0");
  },
};

export const ALineFollowsItsDiagramUnlessItHasAShapeOfItsOwn: Story = {
  play: async () => {
    await expect(effectiveShape(null, "curved")).toBe("curved");
    await expect(effectiveShape(undefined, "spline")).toBe("spline");
    await expect(effectiveShape("straight", "curved")).toBe("straight");
  },
};
