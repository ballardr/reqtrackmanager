import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { buildScoringScheme } from "../testing/storybook-helpers";
import { ScoringLevelPicker } from "./ScoringLevelPicker";

const severity = buildScoringScheme().axes[0];

const meta: Meta<typeof ScoringLevelPicker> = {
  title: "Components/Scoring/ScoringLevelPicker",
  component: ScoringLevelPicker,
  args: { axis: severity, value: null, onChange: fn() },
};
export default meta;

type Story = StoryObj<typeof ScoringLevelPicker>;

export const NotScored: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const select = canvas.getByRole("combobox", { name: "Severity" });
    await expect(select).toHaveValue("");
    await userEvent.selectOptions(select, "sev-5");
    await expect(args.onChange).toHaveBeenCalledWith("sev-5");
  },
};

/** The (?) tooltip lists every level with its guidance, whatever is selected; clearing reports `null`. */
export const HelpListsEveryLevel: Story = {
  args: { value: "sev-5" },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.hover(canvas.getByRole("button", { name: "Help: Severity" }));
    const tip = await within(document.body).findByRole("tooltip");
    await expect(tip).toHaveTextContent("Cosmetic: Task unaffected.");
    await expect(tip).toHaveTextContent("Minor");
    await expect(tip).toHaveTextContent("Blocker: Unusable for this persona; no workaround.");
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Severity" }), "");
    await expect(args.onChange).toHaveBeenCalledWith(null);
  },
};

export const Disabled: Story = {
  args: { value: "sev-2", disabled: true },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("combobox", { name: "Severity" })).toBeDisabled();
  },
};
