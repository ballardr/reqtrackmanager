import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect } from "storybook/test";

import cases from "./graphSelfLoopCases.json";
import { SELF_LOOP_REACH, selfLoop, selfLoopPath } from "./graphSelfLoop";

/** One shared case: a box and the server's loop for it (see `graphSelfLoopCases.json`). */
interface Case {
  name: string;
  box: [number, number, number, number];
  slot: number;
  sides?: string[];
  align: "start" | "end";
  reach: number;
  loop: Record<"start" | "control1" | "control2" | "end" | "label", [number, number]>;
  path: string;
}

const CASES = cases as unknown as Case[];

function Host() {
  return <p>Runs the browser self-loop rule over every case the server's rule produced.</p>;
}

const meta: Meta<typeof Host> = { title: "Components/GraphSelfLoop", component: Host };
export default meta;

type Story = StoryObj<typeof Host>;

export const MatchesTheServersRuleOnEverySharedCase: Story = {
  play: async () => {
    const failures: string[] = [];
    for (const c of CASES) {
      const [x, y, width, height] = c.box;
      const got = selfLoop({ x, y, width, height }, c.slot, c.sides);
      if (got.align !== c.align) failures.push(`${c.name}: align ${got.align} is not ${c.align}`);
      for (const key of ["start", "control1", "control2", "end", "label"] as const) {
        const [ex, ey] = c.loop[key];
        if (Math.abs(got[key].x - ex) > 1e-9 || Math.abs(got[key].y - ey) > 1e-9) failures.push(`${c.name}: ${key}`);
      }
      if (selfLoopPath(got) !== c.path) failures.push(`${c.name}: path ${selfLoopPath(got)} is not ${c.path}`);
    }
    await expect(failures).toEqual([]);
    await expect(CASES.length).toBeGreaterThan(3);
    await expect(CASES.every((c) => c.reach === SELF_LOOP_REACH)).toBe(true);
  },
};

/** A marker's loop runs between the middles of its sides (vertices of its drawing), never the corners of its frame, and keeps off a label's side. */
export const AMarkersLoopLeavesAndReturnsOnItsDrawing: Story = {
  play: async () => {
    const box = { x: 100, y: 50, width: 96, height: 96 };
    const every = ["top", "right", "bottom", "left"];
    const first = selfLoop(box, 0, every);
    await expect([first.start, first.end]).toEqual([{ x: 148, y: 50 }, { x: 196, y: 98 }]);
    const labelRight = selfLoop(box, 0, ["top", "bottom", "left"]);
    await expect(labelRight.end.x).toBe(100);
    // An ordinary box keeps the corner rule.
    await expect(selfLoop({ x: 0, y: 0, width: 160, height: 64 }, 0).start).toEqual({ x: 120, y: 0 });
  },
};
