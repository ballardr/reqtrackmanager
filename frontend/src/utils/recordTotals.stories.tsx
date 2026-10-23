import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect } from "storybook/test";

import type { RecordTypeCount } from "../api/types";
import { buildRecordTotalsChart } from "./recordTotals";

const counts = (n: number): RecordTypeCount[] =>
  Array.from({ length: n }, (_, i) => ({ type: `type_${i}`, label: `Type ${i}`, count: 100 - i }));

/** Pure-function checks for the overview's slice grouping, run as stories like the other helpers. */
const meta: Meta = { title: "Utils/RecordTotals" };
export default meta;

type Story = StoryObj;

export const FewTypesKeepTheirOwnSlice: Story = {
  render: () => <div>Few types</div>,
  play: async () => {
    const chart = buildRecordTotalsChart(counts(3), "Other");
    await expect(chart.segments).toEqual([["Type 0", 100], ["Type 1", 99], ["Type 2", 98]]);
    await expect(chart.segmentTypes).toEqual(["type_0", "type_1", "type_2"]);
    await expect(chart.legend.map((r) => r.segment)).toEqual([0, 1, 2]);
  },
};

export const EightTypesStillFit: Story = {
  render: () => <div>Eight types</div>,
  play: async () => {
    // One more than the seven named slices would fold a single type into "Other": keep it as its own slice instead.
    const chart = buildRecordTotalsChart(counts(8), "Other");
    await expect(chart.segments).toHaveLength(8);
    await expect(chart.segmentTypes.includes(null)).toBe(false);
  },
};

export const ManyTypesFoldTheSmallestIntoOther: Story = {
  render: () => <div>Many types</div>,
  play: async () => {
    const chart = buildRecordTotalsChart(counts(12), "Other");
    await expect(chart.segments).toHaveLength(8);
    await expect(chart.segments[7]).toEqual(["Other", 93 + 92 + 91 + 90 + 89]);
    await expect(chart.segmentTypes[7]).toBeNull();
    // The legend still lists every type; the folded ones point at the "Other" slice.
    await expect(chart.legend).toHaveLength(12);
    await expect(chart.legend[11].segment).toBe(7);
    await expect(chart.legend[6].segment).toBe(6);
    // The total is unchanged by folding.
    await expect(chart.segments.reduce((sum, [, v]) => sum + v, 0)).toBe(counts(12).reduce((sum, c) => sum + c.count, 0));
  },
};

export const NothingToChart: Story = {
  render: () => <div>No types</div>,
  play: async () => {
    const chart = buildRecordTotalsChart([], "Other");
    await expect(chart.segments).toEqual([]);
    await expect(chart.legend).toEqual([]);
  },
};
