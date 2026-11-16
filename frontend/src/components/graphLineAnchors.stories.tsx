import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect } from "storybook/test";

import cases from "./graphLineAnchorCases.json";
import { ATTACH_POINTS, pointXY, type AttachPoint, type BoxGeometry } from "./graphAttachPoints";
import { assignLineAnchors, automaticEnds, type AnchorLine } from "./graphLineAnchors";

/** One shared case: the boxes and lines and the server's answer (see `graphLineAnchorCases.json`). */
interface Case {
  name: string;
  boxes: Record<string, { box: [number, number, number, number]; offers?: AttachPoint[] }>;
  lines: { id: string; source: string; target: string; source_point: AttachPoint | null; target_point: AttachPoint | null; via: [number, number][] }[];
  expected: Record<string, { source?: AttachPoint; target?: AttachPoint; shift?: [number, number]; loop_slot?: number }>;
}

const CASES = cases as unknown as Case[];

const boxesOf = (c: Case) => new Map<string, BoxGeometry>(
  Object.entries(c.boxes).map(([id, { box: [x, y, width, height], offers }]) => [id, { x, y, width, height, points: offers }]),
);
const linesOf = (c: Case): AnchorLine[] => c.lines.map((l) => ({
  id: l.id, source: l.source, target: l.target, sourcePoint: l.source_point, targetPoint: l.target_point,
  points: l.via.map(([x, y]) => ({ x, y })),
}));

function Host() {
  return <p>Runs the browser line anchor rule over every case the server's rule produced.</p>;
}

const meta: Meta<typeof Host> = { title: "Components/GraphLineAnchors", component: Host };
export default meta;

type Story = StoryObj<typeof Host>;

export const MatchesTheServersRuleOnEverySharedCase: Story = {
  play: async () => {
    const failures: string[] = [];
    for (const c of CASES) {
      const got = assignLineAnchors(boxesOf(c), linesOf(c));
      if (got.size !== Object.keys(c.expected).length) failures.push(`${c.name}: ${got.size} lines placed, expected ${Object.keys(c.expected).length}`);
      for (const [id, want] of Object.entries(c.expected)) {
        const a = got.get(id);
        if (!a) { failures.push(`${c.name}: ${id} missing`); continue; }
        if (want.loop_slot !== undefined) {
          if (a.loopSlot !== want.loop_slot) failures.push(`${c.name}: ${id} slot ${a.loopSlot}, expected ${want.loop_slot}`);
          continue;
        }
        const [sx, sy] = want.shift as [number, number];
        if (a.source !== want.source || a.target !== want.target || a.shift.x !== sx || a.shift.y !== sy) {
          failures.push(`${c.name}: ${id} got ${a.source}/${a.target}/${a.shift.x},${a.shift.y}, expected ${want.source}/${want.target}/${sx},${sy}`);
        }
      }
    }
    await expect(failures).toEqual([]);
    await expect(CASES.length).toBeGreaterThan(10);
  },
};

export const AutomaticEndsAreWhatALineWouldTakeIfLeftOpen: Story = {
  play: async () => {
    const c = CASES.find((x) => x.name.startsWith("a point a person fixed"))!;
    const boxes = boxesOf(c);
    const lines = linesOf(c);
    // With its two ends left open, the line a person fixed takes the facing sides again (nothing else holds them), and the
    // automatic line keeps the points it has: the corners above.
    await expect(automaticEnds(boxes, lines, "fixed")).toEqual(["right", "left"]);
    await expect(automaticEnds(boxes, lines, "auto")).toEqual(["top_right", "top_left"]);
    await expect(automaticEnds(boxes, lines, "missing")).toBeNull();
  },
};

export const EveryAssignedPointIsOneOfTheEight: Story = {
  play: async () => {
    for (const c of CASES) {
      for (const a of assignLineAnchors(boxesOf(c), linesOf(c)).values()) {
        await expect(ATTACH_POINTS).toContain(a.source);
        await expect(ATTACH_POINTS).toContain(a.target);
      }
    }
    await expect(pointXY({ x: 0, y: 0, width: 10, height: 10 }, "right")).toEqual({ x: 10, y: 5 });
  },
};
