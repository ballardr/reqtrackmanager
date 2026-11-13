import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect } from "storybook/test";

import cases from "./diagramResolverCases.json";
import { outerSide, resolveLines, type ResolvedLine } from "./diagramResolver";

/** One shared case: its inputs and the server's resolver's answer (see `diagramResolverCases.json`). */
interface Case {
  name: string;
  placed: string[];
  parents: Record<string, string | null>;
  connections: { id: string; source_id: string; target_id: string; directional: boolean }[];
  hidden_elements: string[];
  hidden_connections: string[];
  merge_parallel: boolean;
  boundaries?: { id: string; element_id: string; outside_id: string; connection_ids: string[] }[];
  scope?: string;
  outer_sides?: Record<string, string>;
  expected: {
    hidden_placed: string[];
    internal: Record<string, string[]>;
    lines: {
      source_id: string; target_id: string; two_way: boolean; connection_ids: string[]; rolled_up: boolean;
      bridged: boolean; indirect: boolean; hops: string[];
    }[];
  };
}

/** The shared cases (the file's keys vary by case, so the file is read as the shape documented above). */
const CASES = cases as unknown as Case[];

/** A line in the wire shape the cases use. */
const wire = (line: ResolvedLine) => ({
  source_id: line.sourceId, target_id: line.targetId, two_way: line.twoWay, connection_ids: line.connectionIds,
  rolled_up: line.rolledUp, bridged: line.bridged, indirect: line.indirect, hops: line.hops,
});

function Host() {
  return <p>Runs the browser resolver over every case the server's resolver produced.</p>;
}

const meta: Meta<typeof Host> = { title: "Modules/Architecture/DiagramResolver", component: Host };
export default meta;

type Story = StoryObj<typeof Host>;

export const MatchesTheServersResolverOnEverySharedCase: Story = {
  play: async () => {
    const failures: string[] = [];
    for (const c of CASES) {
      const result = resolveLines({
        placed: c.placed,
        parents: new Map(Object.entries(c.parents)),
        connections: c.connections.map((k) => ({ id: k.id, sourceId: k.source_id, targetId: k.target_id, directional: k.directional })),
        hiddenElements: c.hidden_elements,
        hiddenConnections: c.hidden_connections,
        mergeParallel: c.merge_parallel,
        boundaries: (c.boundaries ?? []).map((b) => ({ id: b.id, elementId: b.element_id, outsideId: b.outside_id, connectionIds: b.connection_ids })),
      });
      const got = {
        hidden_placed: [...result.hiddenPlaced].sort(),
        internal: Object.fromEntries(result.internal),
        lines: result.lines.map(wire),
      };
      if (JSON.stringify(got) !== JSON.stringify({ ...c.expected, internal: sorted(c.expected.internal, got.internal) })) {
        failures.push(c.name);
      }
      if (c.scope !== undefined) {
        const parents = new Map(Object.entries(c.parents));
        const outer = Object.fromEntries(
          c.connections.flatMap((k) => {
            const side = outerSide(c.scope as string, parents, k.source_id, k.target_id);
            return side === null ? [] : [[k.id, side]];
          }),
        );
        if (JSON.stringify(outer) !== JSON.stringify(c.outer_sides)) failures.push(`${c.name} (outer connections)`);
      }
    }
    expect(failures).toEqual([]);
    expect(CASES.length).toBeGreaterThan(20);
    expect(CASES.some((c) => (c.boundaries ?? []).length > 0)).toBe(true);
  },
};

/** The expected internal map in the order the result lists its keys (the server lists them sorted; a map has no order to compare). */
function sorted(expected: Record<string, string[]>, like: Record<string, string[]>): Record<string, string[]> {
  return Object.fromEntries(Object.keys(like).map((k) => [k, expected[k]]));
}
