import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect } from "storybook/test";

import cases from "./graphAttachPointCases.json";
import { ATTACH_POINTS, ATTACH_POINT_LABEL, lineDirections, outwardDirection, pointXY, routeAttachPoints, type AttachPoint } from "./graphAttachPoints";

/** One shared case: its inputs and the server's answer (see `graphAttachPointCases.json`). */
interface Case {
  name: string;
  source: [number, number, number, number];
  target: [number, number, number, number];
  source_point: AttachPoint | null;
  target_point: AttachPoint | null;
  /** The points a marker box offers, when the case has one (the other box offers all eight). */
  source_offers?: AttachPoint[];
  target_offers?: AttachPoint[];
  /** The vertices of a routed line; its open ends follow the vertex beside them. */
  via?: [number, number][];
  expected: [AttachPoint, AttachPoint];
  /** The outward direction of each end toward the line's next point. */
  directions: [[number, number], [number, number]];
}

const CASES = cases as unknown as Case[];
const box = ([x, y, width, height]: Case["source"], points?: AttachPoint[]) => ({ x, y, width, height, points });

function Host() {
  return <p>Runs the browser attach-point rule over every case the server's rule produced.</p>;
}

const meta: Meta<typeof Host> = { title: "Components/GraphAttachPoints", component: Host };
export default meta;

type Story = StoryObj<typeof Host>;

export const MatchesTheServersRuleOnEverySharedCase: Story = {
  play: async () => {
    const failures: string[] = [];
    for (const c of CASES) {
      const via = (c.via ?? []).map(([x, y]) => ({ x, y }));
      const got = routeAttachPoints(box(c.source, c.source_offers), box(c.target, c.target_offers), c.source_point, c.target_point, via);
      if (got.join() !== c.expected.join()) failures.push(`${c.name}: expected ${c.expected.join()}, got ${got.join()}`);
      const [a, b] = lineDirections(box(c.source, c.source_offers), box(c.target, c.target_offers), c.expected[0], c.expected[1], via);
      const near = ([x, y]: [number, number], d: { x: number; y: number }) => Math.abs(x - d.x) < 1e-8 && Math.abs(y - d.y) < 1e-8;
      if (!near(c.directions[0], a) || !near(c.directions[1], b)) failures.push(`${c.name}: directions ${JSON.stringify([a, b])} are not ${JSON.stringify(c.directions)}`);
    }
    await expect(failures).toEqual([]);
    await expect(CASES.length).toBeGreaterThan(10);
  },
};

export const EightDistinctPointsAllLabelled: Story = {
  play: async () => {
    const where = ATTACH_POINTS.map((p) => pointXY({ x: 10, y: 20, width: 100, height: 60 }, p));
    await expect(new Set(where.map((w) => `${w.x},${w.y}`)).size).toBe(8);
    await expect(ATTACH_POINTS.every((p) => ATTACH_POINT_LABEL[p].length > 0)).toBe(true);
  },
};

export const ACornerLeavesAlongTheLeastBentCandidate: Story = {
  play: async () => {
    const square = { x: 0, y: 0, width: 100, height: 100 };
    await expect(outwardDirection(square, "top", { x: 500, y: 500 })).toEqual({ x: 0, y: -1 });
    await expect(outwardDirection(square, "top_right", { x: 110, y: -300 })).toEqual({ x: 0, y: -1 });
    await expect(outwardDirection(square, "top_right", { x: 400, y: -10 })).toEqual({ x: 1, y: 0 });
    const diagonal = outwardDirection(square, "top_right", null);
    await expect(Math.abs(diagonal.x - Math.SQRT1_2) < 1e-12 && Math.abs(diagonal.y + Math.SQRT1_2) < 1e-12).toBe(true);
    await expect(outwardDirection(square, "top_right", { x: 100, y: 0 })).toEqual(diagonal);
  },
};
