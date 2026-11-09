import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, within } from "storybook/test";

import { api } from "../api/client";
import type { OrgOverviewStats } from "../api/types";
import { OrgUsageTable } from "./OrgUsageTable";

const FULL: OrgOverviewStats = {
  project_count: 6, archived_project_count: 2, requirement_count: 148, member_count: 12,
  total_file_size_bytes: 4_500_000, is_full_org_total: true,
};

function mockStats(stats: OrgOverviewStats) {
  spyOn(api, "get").mockResolvedValue(stats);
}

const meta: Meta<typeof OrgUsageTable> = {
  title: "Components/OrgUsageTable",
  component: OrgUsageTable,
  args: { orgId: "org-1" },
};
export default meta;
type Story = StoryObj<typeof OrgUsageTable>;

/** An organisation administrator sees the real totals. */
export const FullTotals: Story = {
  beforeEach: () => mockStats(FULL),
  play: async ({ canvasElement }) => {
    const table = await within(canvasElement).findByRole("table", { name: "Usage" });
    await expect(within(table).getByRole("row", { name: /Users\s+12/ })).toBeVisible();
    await expect(within(table).getByRole("row", { name: /Active .*\s+6/ })).toBeVisible();
    await expect(within(table).getByRole("row", { name: /Archived .*\s+2/ })).toBeVisible();
    await expect(within(table).getByRole("row", { name: /File storage\s+4\.3 MB/ })).toBeVisible();
  },
};

/** A scoped figure is not the organisation's size, so nothing is drawn. */
export const ScopedFiguresHidden: Story = {
  beforeEach: () => mockStats({ ...FULL, is_full_org_total: false }),
  play: async ({ canvasElement }) => {
    await new Promise((resolve) => setTimeout(resolve, 100));
    await expect(within(canvasElement).queryByRole("table")).toBeNull();
  },
};
