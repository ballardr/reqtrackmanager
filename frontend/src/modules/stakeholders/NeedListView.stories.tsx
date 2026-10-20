import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { buildNeed } from "./fixtures";
import { NeedListView } from "./NeedListView";

const meta: Meta<typeof NeedListView> = {
  title: "Modules/Stakeholders/NeedListView",
  component: NeedListView,
  args: {
    needs: [buildNeed(), buildNeed({ id: "need-2", name: "Audit without a meeting", status: "draft", unique_code: "NEED-002" })],
    ariaLabel: "Stakeholder Needs",
    sectionKey: "stakeholders.needs.list",
    emptyText: "No Stakeholder Needs recorded for this project yet.",
    includeArchived: false,
    onIncludeArchivedChange: fn(),
    onOpen: fn(),
  },
};
export default meta;

type Story = StoryObj<typeof NeedListView>;

/** Status goes through its label map; a need has no Type or Scope column, and no New button when created elsewhere. */
export const ListsNeedsWithLabelledStatus: Story = {
  play: async ({ canvasElement }) => {
    const table = within(within(canvasElement).getByRole("table", { name: "Stakeholder Needs" }));
    await expect(table.getByText("Draft")).toBeInTheDocument();
    await expect(table.getByText("Active")).toBeInTheDocument();
    await expect(table.queryByText("draft")).not.toBeInTheDocument();
    await expect(table.queryByRole("columnheader", { name: "Type" })).not.toBeInTheDocument();
    await expect(within(canvasElement).queryByRole("button", { name: "New Need" })).not.toBeInTheDocument();
  },
};

export const StatusBadgeFiltersTheList: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Draft" }));
    await expect(canvas.queryByText("Diagnose faults quickly")).not.toBeInTheDocument();
    await expect(canvas.getByText("Audit without a meeting")).toBeInTheDocument();
  },
};

/** With `onCreate` the list offers its own New button (a list that creates its own records). */
export const OffersNewWhenItCanCreate: Story = {
  args: { onCreate: fn(async () => {}) },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("button", { name: "New Need" })).toBeInTheDocument();
  },
};

export const EmptyState: Story = {
  args: { needs: [] },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("No Stakeholder Needs recorded for this project yet.")).toBeInTheDocument();
  },
};

export const DarkTheme: Story = { ...ListsNeedsWithLabelledStatus, globals: { theme: "dark" } };
