import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";

import { DonutChart } from "./DonutChart";

const meta: Meta<typeof DonutChart> = {
  title: "Components/DonutChart",
  component: DonutChart,
};
export default meta;

type Story = StoryObj<typeof DonutChart>;

export const RequirementsByStatus: Story = {
  args: {
    title: "Requirements by status",
    segments: [
      ["Draft", 8],
      ["Reviewed", 5],
      ["Approved", 12],
      ["Completed", 20],
      ["Archived", 2],
    ],
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Requirements by status")).toBeInTheDocument();
    await expect(canvas.getByText("47")).toBeInTheDocument();
    await expect(canvas.getByText("Draft")).toBeInTheDocument();
  },
};

/** Every count zero: the component must not divide by zero and must still
 * render a legend (mirrors a brand-new project with no requirements yet). */
export const Empty: Story = {
  args: { title: "Change requests", segments: [["Draft", 0]] },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    // Both the centre total and the "Draft" row's own count render "0" —
    // assert there are exactly the two expected instances.
    await expect(canvas.getAllByText("0")).toHaveLength(2);
  },
};

export const LightTheme: Story = { ...RequirementsByStatus, globals: { theme: "light" } };
export const DarkTheme: Story = { ...RequirementsByStatus, globals: { theme: "dark" } };
