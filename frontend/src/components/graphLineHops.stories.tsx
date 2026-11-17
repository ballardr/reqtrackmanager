import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect } from "storybook/test";

import cases from "./graphLineHopCases.json";
import { HOP_CLEARANCE, HOP_RADIUS, lineHops, type HopLine } from "./graphLineHops";
import type { LineShape } from "./graphLinePath";

/** One shared case: the lines of a drawing and the server's path for each line that hops (see `graphLineHopCases.json`). */
interface Case {
  name: string;
  lines: { id: string; start: [number, number]; points: [number, number][]; end: [number, number]; shape: LineShape }[];
  paths: Record<string, string>;
}

const CASES = cases as unknown as Case[];
const pt = ([x, y]: [number, number]) => ({ x, y });
const toLines = (c: Case): HopLine[] => c.lines.map((l) => ({ id: l.id, start: pt(l.start), points: l.points.map(pt), end: pt(l.end), shape: l.shape }));

function Host() {
  return <p>Runs the browser line hop rule over every case the server's rule produced.</p>;
}

const meta: Meta<typeof Host> = { title: "Components/GraphLineHops", component: Host };
export default meta;

type Story = StoryObj<typeof Host>;

export const MatchesTheServersRuleOnEverySharedCase: Story = {
  play: async () => {
    const failures: string[] = [];
    for (const c of CASES) {
      const got = Object.fromEntries(lineHops(toLines(c)));
      if (JSON.stringify(got) !== JSON.stringify(c.paths)) failures.push(`${c.name}: ${JSON.stringify(got)} is not ${JSON.stringify(c.paths)}`);
    }
    await expect(failures).toEqual([]);
    await expect(CASES.length).toBeGreaterThan(10);
  },
};

export const TheLaterLineHopsWhateverTheListOrder: Story = {
  play: async () => {
    const across: HopLine[] = [
      { id: "a", start: { x: 0, y: 100 }, points: [], end: { x: 200, y: 100 }, shape: "straight" },
      { id: "b", start: { x: 100, y: 0 }, points: [], end: { x: 100, y: 200 }, shape: "straight" },
    ];
    await expect([...lineHops(across).keys()]).toEqual(["b"]);
    await expect([...lineHops([...across].reverse()).keys()]).toEqual(["b"]);
    await expect(lineHops(across).get("b")).toBe("M 100 0 L 100 94 A 6 6 0 0 1 100 106 L 100 200");
    await expect(HOP_RADIUS).toBe(6);
    await expect(HOP_CLEARANCE).toBe(12);
  },
};

export const IsFastOnAManyLineDrawing: Story = {
  play: async () => {
    const lines: HopLine[] = [];
    for (let i = 0; i < 100; i += 1) {
      lines.push({ id: `h${String(i).padStart(3, "0")}`, start: { x: 0, y: i * 20 }, points: [], end: { x: 4000, y: i * 20 + 7 }, shape: "straight" });
      lines.push({ id: `v${String(i).padStart(3, "0")}`, start: { x: i * 40, y: 0 }, points: [], end: { x: i * 40 + 5, y: 2100 }, shape: "straight" });
    }
    const began = performance.now();
    const paths = lineHops(lines);
    await expect(performance.now() - began).toBeLessThan(2000);
    await expect(paths.size).toBeGreaterThan(90);
  },
};
