import type { Meta, StoryObj } from "@storybook/react-vite";
import { MemoryRouter } from "react-router-dom";
import { expect, userEvent, within } from "storybook/test";

import { fakeRecordTables } from "../testing/recordTablesFixtures";

import { FilterField, FilterPanel } from "./FilterPanel";
import { ListPageLayout } from "./ListPageLayout";

const meta: Meta<typeof ListPageLayout> = {
  title: "Components/ListPageLayout",
  component: ListPageLayout,
  parameters: { layout: "fullscreen" },
  decorators: [(Story) => <MemoryRouter><div style={{ maxWidth: 1100, padding: 16 }}><Story /></div></MemoryRouter>],
};
export default meta;

type Story = StoryObj<typeof ListPageLayout>;

const filter = (
  <FilterPanel sectionKey="story.list" total={3} search="" onSearchChange={() => {}} searchPlaceholder="Search…">
    <FilterField label="Status"><select className="input"><option>All statuses</option></select></FilterField>
  </FilterPanel>
);

/** The filter panel's top edge lines up with the page title, even with a settings row above the list. */
export const FilterStartsAtTheTitle: Story = {
  args: {
    title: "Pain Point",
    actions: <button className="btn btn-primary" style={{ alignSelf: "flex-start" }}>New Pain Point</button>,
    filter,
    children: (
      <>
        <div className="card">Scoring model: Weighted</div>
        <table><thead><tr><th>Title</th></tr></thead><tbody><tr><td>A pain point</td></tr></tbody></table>
      </>
    ),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const title = canvas.getByRole("heading", { name: "Pain Point" }).getBoundingClientRect();
    const panel = canvasElement.querySelector(".filter-panel")!.getBoundingClientRect();
    await expect(Math.abs(panel.top - title.top)).toBeLessThanOrEqual(2);
    // The list column sits to the left of the filter column, below the title and its actions.
    const switcher = canvas.getByText("Scoring model: Weighted").getBoundingClientRect();
    await expect(switcher.right).toBeLessThanOrEqual(panel.left);
    await expect(switcher.top).toBeGreaterThan(title.bottom);
  },
};

/** A 200-character title wraps inside the left column and never pushes the filter down or off screen. */
export const LongTitleStaysInItsColumn: Story = {
  args: { title: "Very long title ".repeat(14).trim(), filter, children: <p>List</p> },
  play: async ({ canvasElement }) => {
    const panel = canvasElement.querySelector(".filter-panel")!.getBoundingClientRect();
    const heading = canvasElement.querySelector("h1")!.getBoundingClientRect();
    await expect(heading.right).toBeLessThanOrEqual(panel.left);
    await expect(Math.abs(panel.top - heading.top)).toBeLessThanOrEqual(2);
  },
};

/** A list of records passes `records`: one List actions menu sits beside the page's own action, on the title's row. */
export const RecordsAddExportAndImportBesideTheActions: Story = {
  args: {
    title: "Requirements",
    actions: <button className="btn btn-primary">New requirement</button>,
    records: { projectId: "project-1", recordType: "requirement", filters: "status=draft", tables: fakeRecordTables() },
    filter,
    children: <p>List</p>,
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const menuButton = await canvas.findByRole("button", { name: "List actions" });
    const title = canvas.getByRole("heading", { name: "Requirements" }).getBoundingClientRect();
    const newButton = canvas.getByRole("button", { name: "New requirement" }).getBoundingClientRect();
    // One row: the new button and the menu share the title's line, the menu right after the button, and stay left of the filter panel.
    await expect(Math.abs(menuButton.getBoundingClientRect().top - newButton.top)).toBeLessThanOrEqual(8);
    await expect(menuButton.getBoundingClientRect().left).toBeGreaterThanOrEqual(newButton.right);
    await expect(newButton.top).toBeLessThanOrEqual(title.bottom);
    await expect(menuButton.getBoundingClientRect().right).toBeLessThanOrEqual(canvasElement.querySelector(".filter-panel")!.getBoundingClientRect().right);
  },
};

/** Collapsing hides the panel (the list takes the full width) and puts a "Filters" button beside the actions to bring it back. */
export const FilterPanelCanBeCollapsed: Story = {
  args: {
    title: "Pain Point", actions: <button className="btn btn-primary">New Pain Point</button>,
    records: { projectId: "project-1", recordType: "pain_point", filters: "", tables: fakeRecordTables() },
    filter, children: <table aria-label="Rows"><tbody><tr><td>A pain point</td></tr></tbody></table>,
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const list = () => canvasElement.querySelector(".list-page__content")!.getBoundingClientRect();
    const withPanel = list().width;
    await expect(canvas.queryByRole("button", { name: "Filters" })).not.toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Collapse filters" }));
    await expect(canvas.queryByPlaceholderText("Search…")).not.toBeVisible();
    await expect(list().width).toBeGreaterThan(withPanel);
    const restore = await canvas.findByRole("button", { name: "Filters" });
    await expect(restore).toHaveAttribute("aria-expanded", "false");
    // Beside the list actions menu, on the title's row.
    const menu = canvas.getByRole("button", { name: "List actions" }).getBoundingClientRect();
    await expect(restore.getBoundingClientRect().left).toBeGreaterThanOrEqual(menu.right);
    await expect(Math.abs(restore.getBoundingClientRect().top - menu.top)).toBeLessThanOrEqual(8);
    await userEvent.click(restore);
    await expect(canvas.getByPlaceholderText("Search…")).toBeVisible();
    await expect(list().width).toBe(withPanel);
    await expect(canvas.queryByRole("button", { name: "Filters" })).not.toBeInTheDocument();
  },
};
