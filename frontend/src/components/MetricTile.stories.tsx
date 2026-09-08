import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";

import { withRouter } from "../testing/storybook-helpers";
import { MetricTile } from "./MetricTile";

const meta: Meta<typeof MetricTile> = {
  title: "Components/MetricTile",
  component: MetricTile,
  decorators: [withRouter("/", "*")],
};
export default meta;

type Story = StoryObj<typeof MetricTile>;

export const Default: Story = {
  args: { label: "Requirements", value: 24, to: "/projects/project-1/requirements" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("24")).toBeInTheDocument();
    await expect(canvas.getByText("Requirements")).toBeInTheDocument();
    await expect(canvas.getByRole("link")).toHaveAttribute("href", "/projects/project-1/requirements");
  },
};

export const PercentageValue: Story = {
  args: { label: "Corporate Security Standard", value: "83%", to: "/projects/project-1/modules/compliance" },
};
