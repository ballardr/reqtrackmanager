import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { buildCustomCriteriaScheme } from "../testing/storybook-helpers";
import { ScoringEnabledModels } from "./ScoringEnabledModels";

const meta: Meta<typeof ScoringEnabledModels> = {
  title: "Components/Scoring/ScoringEnabledModels",
  component: ScoringEnabledModels,
  args: { scheme: buildCustomCriteriaScheme(), custom: false, resetLabel: "Reset to module default", onSave: fn(), onReset: fn() },
};
export default meta;

type Story = StoryObj<typeof ScoringEnabledModels>;

/** The default model is ticked and locked; unticking another saves the remaining set. */
export const DefaultModelIsAlwaysShown: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("checkbox", { name: "Show ICE" })).toBeDisabled();
    await expect(canvas.getByRole("checkbox", { name: "Show ICE" })).toBeChecked();
    await userEvent.click(canvas.getByRole("checkbox", { name: "Show Weighted value" }));
    await expect(args.onSave).toHaveBeenCalledWith(["ice"]);
  },
};

/** Ticking a model that is off adds it to the set, in the scheme's own order. */
export const TickingAddsAModel: Story = {
  args: { scheme: buildCustomCriteriaScheme({ enabled_model_keys: ["ice"], enabled_models_source: "org" }), custom: true },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("checkbox", { name: "Show Weighted value" })).not.toBeChecked();
    await userEvent.click(canvas.getByRole("checkbox", { name: "Show Weighted value" }));
    await expect(args.onSave).toHaveBeenCalledWith(["ice", "m_weighted_value"]);
  },
};

/** A tier's own choice offers a way back to inheriting. */
export const ResetReturnsToInherited: Story = {
  args: { custom: true },
  play: async ({ canvasElement, args }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Reset to module default" }));
    await expect(args.onReset).toHaveBeenCalled();
  },
};
