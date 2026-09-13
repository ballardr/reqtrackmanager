import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";

import { StatCard } from "./StatCard";

const meta: Meta<typeof StatCard> = {
  title: "Components/StatCard",
  component: StatCard,
};
export default meta;

type Story = StoryObj<typeof StatCard>;

/** Value renders above the label, matching `MetricTile`'s layout — the two
 * are used interchangeably in the same `.grid.grid-metrics` row (e.g.
 * `OrgComplianceDashboard.tsx`'s top grid), so they must share the same
 * visual order or the row reads as inconsistent (found in live review). */
export const Default: Story = {
  args: { label: "Projects", value: 12 },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const value = canvas.getByText("12");
    const label = canvas.getByText("Projects");
    await expect(value).toBeInTheDocument();
    await expect(label).toBeInTheDocument();
    await expect(value.compareDocumentPosition(label) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
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
