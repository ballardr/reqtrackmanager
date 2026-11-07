import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect } from "storybook/test";

import { isoToLocalInput, localInputToIso } from "./dateTimeLocal";

/** Pure-function checks for the local time and UTC conversion, run as stories like the other helpers. */
const meta: Meta = { title: "Utils/DateTimeLocal" };
export default meta;

type Story = StoryObj;

export const EmptyAndInvalidValuesAreNull: Story = {
  render: () => <div>Empty values</div>,
  play: async () => {
    await expect(isoToLocalInput(null)).toBe("");
    await expect(isoToLocalInput("not a date")).toBe("");
    await expect(localInputToIso("")).toBeNull();
    await expect(localInputToIso("not a date")).toBeNull();
  },
};

export const AnInstantRoundTripsThroughTheLocalInput: Story = {
  render: () => <div>Round trip</div>,
  play: async () => {
    for (const iso of ["2026-07-01T09:00:00.000Z", "2026-01-01T23:00:00.000Z", "2026-03-29T01:30:00.000Z"]) {
      const local = isoToLocalInput(iso);
      await expect(local).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/);
      await expect(localInputToIso(local)).toBe(iso);
    }
  },
};

export const ALocalTimeIsReadInTheBrowsersZone: Story = {
  render: () => <div>Local reading</div>,
  play: async () => {
    // 09:00 on the person's own clock is the instant `new Date` gives for it, whatever zone the browser is in.
    await expect(localInputToIso("2026-07-01T09:00")).toBe(new Date(2026, 6, 1, 9, 0).toISOString());
    await expect(isoToLocalInput(new Date(2026, 6, 1, 23, 0).toISOString())).toBe("2026-07-01T23:00");
  },
};
