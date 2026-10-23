import type { Meta, StoryObj } from "@storybook/react-vite";
import { MemoryRouter } from "react-router-dom";
import { expect, within } from "storybook/test";

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
