import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { ScoringModelSwitcher } from "./ScoringModelSwitcher";

const models = [
  { value: "sxf", label: "Severity × Frequency" },
  { value: "sxfxc", label: "Severity × Frequency × Confidence" },
];

const meta: Meta<typeof ScoringModelSwitcher> = {
  title: "Components/Scoring/ScoringModelSwitcher",
  component: ScoringModelSwitcher,
  args: { models, model: "sxfxc", onModelChange: fn() },
};
export default meta;

type Story = StoryObj<typeof ScoringModelSwitcher>;

export const ModelOnly: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const select = canvas.getByRole("combobox", { name: "Scoring model" });
    // No blank option: a view is always under exactly one model.
    await expect(within(select).queryByRole("option", { name: "Select…" })).not.toBeInTheDocument();
    await userEvent.selectOptions(select, "sxf");
    await expect(args.onModelChange).toHaveBeenCalledWith("sxf");
    await expect(canvas.queryByRole("combobox", { name: "Combine personas by" })).not.toBeInTheDocument();
  },
};

export const WithRollup: Story = {
  args: {
    rollups: [{ value: "weighted", label: "Weighted average" }, { value: "worst", label: "Worst case" }],
    rollup: "weighted",
    onRollupChange: fn(),
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Combine personas by" }), "worst");
    await expect(args.onRollupChange).toHaveBeenCalledWith("worst");
  },
};
