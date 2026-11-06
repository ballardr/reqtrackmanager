import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import type { ScoringAxis } from "../api/scoring";
import { buildCustomCriteriaScheme } from "../testing/storybook-helpers";
import { ScoringAxisThresholds } from "./ScoringAxisThresholds";

const demand = (patch: Partial<ScoringAxis> = {}): ScoringAxis => ({
  ...buildCustomCriteriaScheme().axes.find((a) => a.key === "demand")!, ...patch,
});

const meta: Meta<typeof ScoringAxisThresholds> = {
  title: "Components/Scoring/ScoringAxisThresholds",
  component: ScoringAxisThresholds,
  args: { axis: demand(), onSave: fn(async () => {}), onReset: fn(async () => {}) },
};
export default meta;

type Story = StoryObj<typeof ScoringAxisThresholds>;

/** The organisation's values show beside the project's, which start as the values in force; Save needs a valid change. */
export const InheritsTheOrganisationValuesUntilChanged: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Organisation values")).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Use inherited values" })).not.toBeInTheDocument();
    const save = canvas.getByRole("button", { name: "Save thresholds" });
    await expect(save).toBeDisabled();
    const some = canvas.getByRole("spinbutton", { name: "Demand Some threshold in this project" });
    await userEvent.clear(some);
    await userEvent.type(some, "5");
    await expect(save).toBeEnabled();
    await userEvent.click(save);
    await waitFor(() => expect(args.onSave).toHaveBeenCalledWith({ "dem-1": 0, "dem-2": 5, "dem-3": 10 }));
  },
};

/** Thresholds that do not rise with the levels are refused before anything is sent. */
export const RefusesThresholdsThatDoNotRise: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const lots = canvas.getByRole("spinbutton", { name: "Demand Lots threshold in this project" });
    await userEvent.clear(lots);
    await userEvent.type(lots, "2");
    await expect(canvas.getByText("Each level must start above the one before.")).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Save thresholds" })).toBeDisabled();
    await expect(args.onSave).not.toHaveBeenCalled();
  },
};

/** With its own thresholds the project sees a Custom pill and can go back to the inherited ones. */
export const OwnThresholdsCanBeReset: Story = {
  args: { axis: demand({ thresholds_source: "project" }) },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Custom")).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Use inherited values" }));
    await waitFor(() => expect(args.onReset).toHaveBeenCalled());
  },
};

/** A parent project's thresholds are named as the source. */
export const SaysWhenInheritedFromAParentProject: Story = {
  args: { axis: demand({ thresholds_source: "ancestor" }) },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("Inherited from parent project")).toBeInTheDocument();
  },
};
