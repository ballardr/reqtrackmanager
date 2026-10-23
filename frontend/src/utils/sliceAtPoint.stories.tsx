import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect } from "storybook/test";

import { sliceAtPoint } from "./sliceAtPoint";

/** Pure-function checks for the donut's hit-testing, run as stories like the other helpers. */
const meta: Meta = { title: "Utils/SliceAtPoint" };
export default meta;

type Story = StoryObj;

export const SlicesRunClockwiseFromTheTop: Story = {
  render: () => <div>Slice hit-testing</div>,
  play: async () => {
    const values = [50, 25, 25];
    await expect(sliceAtPoint(10, -48, values)).toBe(0); // just right of the top
    await expect(sliceAtPoint(48, 0, values)).toBe(0); // 3 o'clock: still the first half
    await expect(sliceAtPoint(0, 48, values)).toBe(1); // 6 o'clock starts the second slice
    await expect(sliceAtPoint(-48, 0, values)).toBe(2); // 9 o'clock starts the third
    await expect(sliceAtPoint(-10, -48, values)).toBe(2); // just left of the top ends the last
  },
};

export const TheHoleAndOutsideAreNoSlice: Story = {
  render: () => <div>Slice hit-testing</div>,
  play: async () => {
    await expect(sliceAtPoint(0, 0, [1, 1])).toBe(-1);
    await expect(sliceAtPoint(20, 20, [1, 1])).toBe(-1);
    await expect(sliceAtPoint(70, 0, [1, 1])).toBe(-1);
  },
};

export const ZeroValuedSlicesAreSkippedAndAnEmptyRingHasNone: Story = {
  render: () => <div>Slice hit-testing</div>,
  play: async () => {
    await expect(sliceAtPoint(0, 48, [0, 10, 10])).toBe(2);
    await expect(sliceAtPoint(0, 48, [0, 0])).toBe(-1);
  },
};
