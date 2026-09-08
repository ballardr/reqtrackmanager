import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";

import { StatCard } from "./StatCard";

const meta: Meta<typeof StatCard> = {
  title: "Components/StatCard",
  component: StatCard,
};
export default meta;

type Story = StoryObj<typeof StatCard>;

export const Default: Story = {
  args: { label: "Projects", value: 12 },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("12")).toBeInTheDocument();
    await expect(canvas.getByText("Projects")).toBeInTheDocument();
  },
};

export const WithDrillDown: Story = {
  args: {
    label: "Non-compliant projects",
    value: 2,
    children: (
      <ul style={{ margin: 0, paddingLeft: "1.2rem" }}>
        <li>Alpha</li>
        <li>Beta</li>
      </ul>
    ),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Alpha")).toBeInTheDocument();
    await expect(canvas.getByText("Beta")).toBeInTheDocument();
  },
};
