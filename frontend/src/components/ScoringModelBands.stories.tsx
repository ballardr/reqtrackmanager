import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { buildScoringScheme } from "../testing/storybook-helpers";
import { ScoringModelBands } from "./ScoringModelBands";

const meta: Meta<typeof ScoringModelBands> = {
  title: "Components/Scoring/ScoringModelBands",
  component: ScoringModelBands,
  args: {
    scheme: buildScoringScheme(), isCustom: () => false,
    onSave: fn(async () => {}), onReset: fn(async () => {}),
  },
};
export default meta;

type Story = StoryObj<typeof ScoringModelBands>;

/** Starts on the default model; a three-axis model previews its first two axes. */
export const DefaultModelPreview: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("combobox", { name: "Model" })).toHaveValue("sxfxc");
    await expect(canvas.getByText(/Preview at the top level of the remaining axes/)).toBeInTheDocument();
    await expect(canvas.getByText("Module default")).toBeInTheDocument();
  },
};

export const SwitchModelAndSave: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Model" }), "sxf");
    await expect(canvas.getByText("Preview (Severity × Frequency).")).toBeInTheDocument();
    const label = canvas.getByRole("textbox", { name: "Band 1 label" });
    await userEvent.clear(label);
    await userEvent.type(label, "Minimal");
    await userEvent.click(canvas.getByRole("button", { name: "Save bands" }));
    await expect(args.onSave).toHaveBeenCalledWith("sxf", expect.arrayContaining([{ label: "Minimal", min_score: 0, tone: "muted" }]));
  },
};
