import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect } from "storybook/test";

import cases from "./graphSelfLoopCases.json";
import { SELF_LOOP_REACH, selfLoop, selfLoopPath } from "./graphSelfLoop";

/** One shared case: a box and the server's loop for it (see `graphSelfLoopCases.json`). */
interface Case {
  name: string;
  box: [number, number, number, number];
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
      const got = selfLoop({ x, y, width, height });
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
