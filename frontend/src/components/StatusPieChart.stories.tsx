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

/** A legend that lists more items than there are slices: the folded "Other" slice keeps one row per item. */
export const FoldedLegend: Story = {
  args: {
    title: "Total records",
    segments: [
      ["Requirements", 10],
      ["Other", 5],
    ],
    legend: [
      { label: "Requirements", value: 10, segment: 0 },
      { label: "Risks", value: 3, segment: 1 },
      { label: "Decisions", value: 2, segment: 1 },
    ],
    colors: ["var(--color-primary)", "var(--color-text-muted)"],
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("15")).toBeInTheDocument();
    await expect(canvas.getByText("Risks")).toBeInTheDocument();
    await expect(canvas.getByText("Decisions")).toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...RequirementsByStatus, globals: { theme: "light" } };
export const DarkTheme: Story = { ...RequirementsByStatus, globals: { theme: "dark" } };
