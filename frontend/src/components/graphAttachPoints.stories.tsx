import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect } from "storybook/test";

import cases from "./graphAttachPointCases.json";
import { ATTACH_POINTS, ATTACH_POINT_LABEL, lineAttachPoints, pointXY, type AttachPoint } from "./graphAttachPoints";

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
  expected: [AttachPoint, AttachPoint];
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
      const got = lineAttachPoints(box(c.source, c.source_offers), box(c.target, c.target_offers), c.source_point, c.target_point);
      if (got.join() !== c.expected.join()) failures.push(`${c.name}: expected ${c.expected.join()}, got ${got.join()}`);
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
