import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";

import { ProgressMeter } from "./ProgressMeter";

/** How far something has got, as a bar with the value in words beside it. */
const meta: Meta<typeof ProgressMeter> = {
  title: "Components/ProgressMeter",
  component: ProgressMeter,
  args: { value: 2, max: 5, label: "Step 2 of 5" },
};
export default meta;

type Story = StoryObj<typeof ProgressMeter>;

/** The bar is a named progress bar at the right fraction and the words are visible. */
export const ShowsTheValueInWords: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const bar = canvas.getByRole("progressbar", { name: "Step 2 of 5" });
    await expect(bar).toHaveAttribute("aria-valuenow", "2");
    await expect(bar).toHaveAttribute("aria-valuemax", "5");
    await expect(canvas.getAllByText("Step 2 of 5").length).toBeGreaterThan(0);
  },
};

/** A value above the maximum is a full bar. */
export const ClampsToFull: Story = {
  args: { value: 9, max: 5, label: "Completed" },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("progressbar", { name: "Completed" })).toHaveAttribute("aria-valuenow", "5");
  },
};
