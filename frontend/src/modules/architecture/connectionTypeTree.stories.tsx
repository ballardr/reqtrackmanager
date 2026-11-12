import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect } from "storybook/test";

import { connectionTypeNodes, cycleReasons, flattenTypes, pathOptions, typeClosure } from "./connectionTypeTree";
import { MAX_TYPE_DEPTH } from "./connectionTypeTree";
import type { ConnectionType } from "./types";

/** A type with only what the tree needs. */
const type = (id: string, name: string, sort_order: number, parent_ids: string[] = []): ConnectionType => ({
  id, name, sort_order, parent_ids, project_id: null, organization_id: "org", domain: "any", line_style: "solid",
  directional: true, color_light: null, color_dark: null,
});

/** Serial bus > I2C, SPI; Board-to-board > I2C (two parents); Power; Orphan whose parent is not in the list. */
const TYPES: ConnectionType[] = [
  type("serial", "Serial bus", 0),
  type("board", "Board-to-board", 1),
  type("i2c", "I2C", 2, ["serial", "board"]),
  type("spi", "SPI", 3, ["serial"]),
  type("power", "Power", 4),
  type("orphan", "Orphan", 5, ["hidden-parent"]),
];

function Host() {
  return <p>Checks the connection type tree helpers.</p>;
}

const meta: Meta<typeof Host> = { title: "Modules/Architecture/ConnectionTypeTree", component: Host };
export default meta;

type Story = StoryObj<typeof Host>;

export const NodesPutATypeUnderEveryParentAndKeepOrphansAsRoots: Story = {
  play: async () => {
    const nodes = connectionTypeNodes(TYPES);
    await expect(nodes.map((n) => n.label)).toEqual(["Serial bus", "Board-to-board", "Power", "Orphan"]);
    await expect(nodes[0].children.map((n) => n.label)).toEqual(["I2C", "SPI"]);
    await expect(nodes[1].children.map((n) => n.label)).toEqual(["I2C"]);
  },
};

export const ClosureIncludesEveryTypeBeneathAGroup: Story = {
  play: async () => {
    await expect([...typeClosure(TYPES, ["serial"])].sort()).toEqual(["i2c", "serial", "spi"]);
    await expect([...typeClosure(TYPES, ["board"])].sort()).toEqual(["board", "i2c"]);
    await expect([...typeClosure(TYPES, ["power"])]).toEqual(["power"]);
  },
};

export const ATypeCannotSitUnderItselfOrBeneathItself: Story = {
  play: async () => {
    const reasons = cycleReasons(TYPES, "serial");
    await expect([...reasons.keys()].sort()).toEqual(["i2c", "serial", "spi"]);
    await expect(connectionTypeNodes(TYPES, reasons)[0].disabled).toBe(true);
    await expect(connectionTypeNodes(TYPES, reasons)[2].disabled).toBe(false);
    await expect(cycleReasons(TYPES).size).toBe(0);
  },
};

export const FlatSelectsShowThePathInTreeOrder: Story = {
  play: async () => {
    await expect(pathOptions(TYPES).map((o) => o.label)).toEqual([
      "Serial bus", "Serial bus › I2C", "Serial bus › SPI", "Board-to-board", "Power", "Orphan",
    ]);
    await expect(flattenTypes(TYPES).map((e) => e.depth)).toEqual([0, 1, 1, 0, 0, 0]);
  },
};

export const ACorruptLoopIsCutAtTheDepthLimit: Story = {
  play: async () => {
    const loop = [type("a", "A", 0, ["b"]), type("b", "B", 1, ["a"])];
    await expect(typeClosure(loop, ["a"]).size).toBe(2);
    await expect(pathOptions(loop).length).toBeLessThanOrEqual(MAX_TYPE_DEPTH);
  },
};
