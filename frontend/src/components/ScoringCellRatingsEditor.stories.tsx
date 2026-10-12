import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { buildScoringScheme } from "../testing/storybook-helpers";
import { ScoringCellRatingsEditor } from "./ScoringCellRatingsEditor";

const scheme = buildScoringScheme();
const [severity, frequency] = scheme.axes;
const model = scheme.models[0];

const meta: Meta<typeof ScoringCellRatingsEditor> = {
  title: "Components/Scoring/ScoringCellRatingsEditor",
  component: ScoringCellRatingsEditor,
  args: {
    xAxis: frequency, yAxis: severity, bands: model.bands, cellRatings: [], custom: false,
    defaultLabel: "None defined", caption: "Preview (Severity × Frequency).",
    onSave: fn(async () => {}), onReset: fn(async () => {}),
  },
};
export default meta;

type Story = StoryObj<typeof ScoringCellRatingsEditor>;

/** Nothing pinned: every cell shows its threshold band and Save stays disabled. */
export const Untouched: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("None defined")).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Save cell ratings" })).toBeDisabled();
    // 5 x 1 of a possible 5 x 4 is 0.25, so thresholds rate it Medium.
    await expect(canvas.getByRole("cell", { name: /Severity Blocker, Frequency Rare: Medium/ })).toBeInTheDocument();
  },
};

/** Pinning a cell recolours it at once and saves the whole set. */
export const PinACellAndSave: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.selectOptions(
      canvas.getByRole("combobox", { name: "Rating for Severity Blocker, Frequency Rare" }), "Critical",
    );
    await expect(canvas.getByRole("cell", { name: /Severity Blocker, Frequency Rare: Critical/ })).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Save cell ratings" }));
    await expect(args.onSave).toHaveBeenCalledWith([{ first_level_id: "sev-5", second_level_id: "freq-1", band_label: "Critical" }]);
  },
};

export const DiscardChanges: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const select = canvas.getByRole("combobox", { name: "Rating for Severity Blocker, Frequency Rare" });
    await userEvent.selectOptions(select, "Low");
    await userEvent.click(canvas.getByRole("button", { name: "Discard changes" }));
    await expect(select).toHaveValue("");
    await expect(args.onSave).not.toHaveBeenCalled();
  },
};

/** The project's own set: shows as a custom value and can be returned to inheritance. */
export const CustomSetCanBeReset: Story = {
  args: {
    custom: true, resetLabel: "Use inherited value",
    cellRatings: [{ first_level_id: "sev-5", second_level_id: "freq-1", band_label: "Critical" }],
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("combobox", { name: "Rating for Severity Blocker, Frequency Rare" })).toHaveValue("Critical");
    await userEvent.click(canvas.getByRole("button", { name: "Use inherited value" }));
    await expect(args.onReset).toHaveBeenCalled();
  },
};

/** A pinned band that no longer exists is ignored: the cell falls back to its threshold band. */
export const StaleBandFallsBackToThresholds: Story = {
  args: { cellRatings: [{ first_level_id: "sev-5", second_level_id: "freq-1", band_label: "Gone" }] },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("cell", { name: /Severity Blocker, Frequency Rare: Medium/ })).toBeInTheDocument();
  },
};

export const LightTheme: Story = { globals: { theme: "light" } };
export const DarkTheme: Story = { globals: { theme: "dark" } };
