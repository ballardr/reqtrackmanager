import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect } from "storybook/test";

import cases from "./graphLinePathCases.json";
import {
  bowSpan, BOW_LIMIT, effectiveShape, insertWaypoint, lineMiddle, linePath, MAX_WAYPOINTS, moveWaypoint, NEW_WAYPOINT_DROP, removeWaypoint, reverseRoute, segmentMiddles, suggestWaypoint, type LineShape,
} from "./graphLinePath";

/** One shared case: a line and the server's path and middle for it (see `graphLinePathCases.json`). */
interface Case {
  name: string;
  start: [number, number];
  points: [number, number][];
  end: [number, number];
  shape: LineShape;
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
      const path = linePath(pt(c.start), points, pt(c.end), c.shape);
      if (path !== c.path) failures.push(`${c.name}: path ${path} is not ${c.path}`);
      const middle = lineMiddle(pt(c.start), points, pt(c.end), c.shape);
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

export const ACurvedLineWithNoVerticesIsOneArcBowedLeftOfItsDirection: Story = {
  play: async () => {
    const arc = bowSpan({ x: 0, y: 0 }, { x: 100, y: 0 });
    await expect(arc?.[1].y).toBe(-25);
    await expect(arc?.[2].y).toBe(-25);
    // The arc, the label and the vertex handle are all on the drawn line, not on its chord.
    await expect(lineMiddle({ x: 0, y: 0 }, [], { x: 100, y: 0 }, "curved")).toEqual({ x: 50, y: -18.75 });
    await expect(segmentMiddles({ x: 0, y: 0 }, [], { x: 100, y: 0 }, "curved")).toEqual([{ x: 50, y: -18.75 }]);
    await expect(linePath({ x: 0, y: 0 }, [], { x: 100, y: 0 }, "curved").split("C").length - 1).toBe(1);
    // The bow is capped on a long line, and a line with no length has none.
    await expect(bowSpan({ x: 0, y: 0 }, { x: 2000, y: 0 })?.[1].y).toBe(-BOW_LIMIT);
    await expect(bowSpan({ x: 3, y: 3 }, { x: 3, y: 3 })).toBeNull();
  },
};

export const ACurvedLineWithVerticesIsTheSplineThroughThem: Story = {
  play: async () => {
    const through = [{ x: 50, y: 60 }, { x: 80, y: 10 }];
    await expect(linePath({ x: 0, y: 0 }, through, { x: 100, y: 0 }, "curved")).toBe(linePath({ x: 0, y: 0 }, through, { x: 100, y: 0 }, "spline"));
    // A spline with nothing to curve through is straight, a Curved one is not.
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
