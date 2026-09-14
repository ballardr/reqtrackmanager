import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { LabeledSelect } from "./LabeledSelect";

const meta: Meta<typeof LabeledSelect> = {
  title: "Components/LabeledSelect",
  component: LabeledSelect,
  args: {
    label: "Standard",
    value: "",
    onChange: fn(),
    options: [
      { value: "std-1", label: "ISO-27001 — Corporate Security Standard" },
      { value: "std-2", label: "SOC2 — Trust Services Criteria" },
    ],
  },
};
export default meta;

type Story = StoryObj<typeof LabeledSelect>;

export const SelectingCallsOnChange: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const select = canvas.getByLabelText("Standard");
    await expect(select).toBeEnabled();
    await userEvent.selectOptions(select, "std-2");
    await expect(args.onChange).toHaveBeenCalledWith("std-2");
  },
};

export const DisabledUntilParentChosen: Story = {
  args: { label: "Version", disabled: true, placeholder: "Select a standard first…" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByLabelText("Version")).toBeDisabled();
    await expect(canvas.getByRole("option", { name: "Select a standard first…" })).toBeInTheDocument();
  },
};
