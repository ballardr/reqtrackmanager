import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { StatusPieChart } from "./StatusPieChart";

const meta: Meta<typeof StatusPieChart> = {
  title: "Components/StatusPieChart",
  component: StatusPieChart,
};
export default meta;

type Story = StoryObj<typeof StatusPieChart>;

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

/** Every count zero: must not divide by zero and must still render a
 * legend (mirrors a brand-new project with no requirements yet). */
export const Empty: Story = {
  args: { title: "Change requests", segments: [["Draft", 0]] },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getAllByText("0")).toHaveLength(2);
  },
};

/** Clicking a legend row (the dashboard's click-to-filter navigation,
 * UX review) fires `onSegmentClick` with the clicked segment's label. */
export const Clickable: Story = {
  args: {
    title: "Requirements by status",
    segments: [
      ["Draft", 8],
      ["Approved", 12],
    ],
    onSegmentClick: fn(),
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: /Approved/ }));
    await expect(args.onSegmentClick).toHaveBeenCalledWith("Approved", 1);
  },
};

export const LightTheme: Story = { ...RequirementsByStatus, globals: { theme: "light" } };
export const DarkTheme: Story = { ...RequirementsByStatus, globals: { theme: "dark" } };
