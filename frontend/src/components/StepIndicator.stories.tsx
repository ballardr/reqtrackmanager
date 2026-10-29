import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";

import { StepIndicator } from "./StepIndicator";

const meta: Meta<typeof StepIndicator> = {
  title: "Components/StepIndicator",
  component: StepIndicator,
  args: { steps: ["Choose a report", "Configure and download"], current: 0, label: "Download steps" },
};
export default meta;

type Story = StoryObj<typeof StepIndicator>;

/** The first step is current; the list names every step in order. */
export const FirstStep: Story = {
  play: async ({ canvasElement }) => {
    const list = within(canvasElement).getByRole("list", { name: "Download steps" });
    await expect(within(list).getAllByRole("listitem")).toHaveLength(2);
    await expect(within(list).getByText("Choose a report").closest("li")).toHaveAttribute("aria-current", "step");
    await expect(within(list).getByText("Configure and download").closest("li")).not.toHaveAttribute("aria-current");
  },
};

/** Moving on marks the second step current instead. */
export const SecondStep: Story = {
  args: { current: 1 },
  play: async ({ canvasElement }) => {
    const list = within(canvasElement).getByRole("list", { name: "Download steps" });
    await expect(within(list).getByText("Configure and download").closest("li")).toHaveAttribute("aria-current", "step");
    await expect(within(list).getByText("Choose a report").closest("li")).not.toHaveAttribute("aria-current");
  },
};
