import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { buildScoringScheme } from "../testing/storybook-helpers";
import { ScoringBandsEditor } from "./ScoringBandsEditor";

const bands = buildScoringScheme().models[0].bands;

const meta: Meta<typeof ScoringBandsEditor> = {
  title: "Components/Scoring/ScoringBandsEditor",
  component: ScoringBandsEditor,
  args: {
    bands, custom: false, defaultLabel: "Inherited from organisation", resetLabel: "Use inherited value",
    onSave: fn(async () => {}), onReset: fn(async () => {}),
  },
};
export default meta;

type Story = StoryObj<typeof ScoringBandsEditor>;

export const InheritedNoChanges: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Inherited from organisation")).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Save bands" })).toBeDisabled();
    // The first band always starts at 0%.
    await expect(canvas.getByRole("spinbutton", { name: "Band 1 starts at percent" })).toBeDisabled();
  },
};

export const EditAndSave: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const label = canvas.getByRole("textbox", { name: "Band 4 label" });
    await userEvent.clear(label);
    await userEvent.type(label, "Urgent");
    const start = canvas.getByRole("spinbutton", { name: "Band 4 starts at percent" });
    await userEvent.clear(start);
    await userEvent.type(start, "75");
    await userEvent.click(canvas.getByRole("button", { name: "Save bands" }));
    await waitFor(() => expect(args.onSave).toHaveBeenCalledWith([
      { label: "Low", min_score: 0, tone: "muted" },
      { label: "Medium", min_score: 0.2, tone: "info" },
      { label: "High", min_score: 0.4, tone: "warning" },
      { label: "Urgent", min_score: 0.75, tone: "danger" },
    ]));
  },
};

/** Thresholds must increase; the error shows and Save stays disabled. */
export const InvalidThresholdsBlockSave: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const start = canvas.getByRole("spinbutton", { name: "Band 3 starts at percent" });
    await userEvent.clear(start);
    await userEvent.type(start, "10");
    await expect(canvas.getByText("Starting percentages must increase and stay below 100%.")).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Save bands" })).toBeDisabled();
  },
};

export const CustomWithReset: Story = {
  args: { custom: true },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Use inherited value" }));
    await waitFor(() => expect(args.onReset).toHaveBeenCalledOnce());
  },
};

export const AddAndRemoveBand: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Add band" }));
    await expect(canvas.getByRole("textbox", { name: "Band 5 label" })).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Remove band 5" }));
    await expect(canvas.queryByRole("textbox", { name: "Band 5 label" })).not.toBeInTheDocument();
  },
};
