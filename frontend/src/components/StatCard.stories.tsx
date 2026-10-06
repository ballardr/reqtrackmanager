import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";

import { statBlockViolations } from "../testing/statBlockGeometry";
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

/** A `.grid.grid-metrics` of nine cards (the compliance dashboard's shape) is tidy at every width, including a
 * phone-width container narrower than two 220px minimums. */
const grid = (width: number): Story => ({
  render: () => (
    <div style={{ width, maxWidth: "100%" }}>
      <div className="grid grid-metrics">
        {Array.from({ length: 9 }, (_, i) => (
          <StatCard key={i} label={i % 2 ? "Projects with outstanding compliance actions" : "Projects"} value={i * 11} />
        ))}
      </div>
    </div>
  ),
  play: async ({ canvasElement }) => {
    await expect(statBlockViolations(canvasElement)).toEqual([]);
  },
});
export const GridDesktop: Story = grid(1200);
export const GridPhone: Story = grid(375);
