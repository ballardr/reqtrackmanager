import type { Meta, StoryObj } from "@storybook/react-vite";
import { MemoryRouter, useLocation } from "react-router-dom";
import { expect, userEvent, waitFor, within } from "storybook/test";

import { useListSort } from "../hooks/useListSort";
import { buildUser, withStatefulAuth } from "../testing/storybook-helpers";
import { sortRows, TIME_SORT_VALUES } from "../utils/sortRows";
import { DirectoryTable, type DirectoryColumn } from "./DirectoryTable";
import { FilterPanel } from "./FilterPanel";
import { SortField } from "./SortField";

interface Row {
  id: string;
  unique_code: string;
  title: string;
  status: string;
  created_at: string;
  updated_at: string;
}

const ROWS: Row[] = [
  { id: "1", unique_code: "DEC-10", title: "Choose the battery", status: "Draft", created_at: "2026-03-01T09:00:00Z", updated_at: "2026-11-20T09:00:00Z" },
  { id: "2", unique_code: "DEC-2", title: "adopt the bus", status: "Approved", created_at: "2026-01-01T09:00:00Z", updated_at: "2026-02-01T09:00:00Z" },
  { id: "3", unique_code: "DEC-1", title: "Pick a vendor", status: "Approved", created_at: "2026-02-01T09:00:00Z", updated_at: "2026-06-01T09:00:00Z" },
];

const COLUMNS: DirectoryColumn<Row>[] = [
  { key: "unique_code", label: "Code", sortable: true, render: (r) => r.unique_code },
  { key: "title", label: "Title", sortable: true, render: (r) => r.title },
  { key: "status", label: "Status", sortable: true, render: (r) => r.status },
];
const KEYS = ["unique_code", "title", "status", "created", "modified"] as const;
const VALUES = {
  ...TIME_SORT_VALUES,
  unique_code: (r: Row) => r.unique_code,
  title: (r: Row) => r.title,
  status: (r: Row) => r.status,
};

function Harness({ local = false }: { local?: boolean }) {
  const listSort = useListSort("demo", KEYS, "unique_code", local);
  const { search } = useLocation();
  return (
    <div className="side-grid">
      <DirectoryTable
        ariaLabel="Records"
        columns={COLUMNS}
        rows={sortRows(ROWS, listSort.sort, VALUES)}
        sort={listSort.sort}
        onSort={listSort.onHeaderSort}
        rowKey={(r) => r.id}
        emptyState={<p>No records.</p>}
      />
      <div>
        <FilterPanel sectionKey="story.sort">
          <SortField list={listSort} columns={COLUMNS} codeKey="unique_code" />
        </FilterPanel>
        <output aria-label="URL">{search}</output>
      </div>
    </div>
  );
}

/**
 * The Sort by and Order fields of a record list's filter panel. They share one state with the table's column
 * headers (`useListSort`), so the two never disagree; the order is code ascending until a person chooses another.
 */
const meta: Meta<typeof Harness> = {
  title: "Components/SortField",
  component: Harness,
  decorators: [
    withStatefulAuth(buildUser({ ui_preferences: {} })),
    (Story, context) => (
      <MemoryRouter initialEntries={[(context.parameters.path as string | undefined) ?? "/list"]}>
        <Story />
      </MemoryRouter>
    ),
  ],
};
export default meta;

type Story = StoryObj<typeof Harness>;

const codes = (canvas: ReturnType<typeof within>) =>
  canvas.getAllByRole("row").slice(1).map((row: HTMLElement) => within(row).getAllByRole("cell")[0].textContent);

/** With nothing chosen the list is by code ascending, numbers by value (DEC-2 before DEC-10). */
export const DefaultsToCodeAscending: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(codes(canvas)).toEqual(["DEC-1", "DEC-2", "DEC-10"]);
    await expect(canvas.getByRole("combobox", { name: "Sort by" })).toHaveValue("unique_code");
    await expect(canvas.getByRole("combobox", { name: "Order" })).toHaveValue("asc");
  },
};

/** The choices are the sortable columns, then Created and Modified, and each is described in the caption's tooltip. */
export const OffersEveryColumnAndTheTwoTimes: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const select = canvas.getByRole("combobox", { name: "Sort by" });
    await expect(within(select).getAllByRole("option").map((o) => o.textContent)).toEqual(["Code", "Title", "Status", "Created", "Modified"]);
    await userEvent.hover(canvas.getByRole("button", { name: "Help: Sort by" }));
    const tip = await within(document.body).findByRole("tooltip");
    await expect(tip).toHaveTextContent("Code: the record's code, numbers by value (REQ-2 before REQ-10).");
    await expect(tip).toHaveTextContent("Title: alphabetical, ignoring case.");
    await expect(tip).toHaveTextContent("Created: when the record was created.");
    await expect(tip).toHaveTextContent("Modified: when the record was last changed, including a new version.");
  },
};

/** Choosing Modified and Descending puts the record changed last at the top, and the choice is written to the address. */
export const ModifiedNewestFirst: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Sort by" }), "modified");
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Order" }), "desc");
    await expect(codes(canvas)).toEqual(["DEC-10", "DEC-1", "DEC-2"]);
    const query = new URLSearchParams(canvas.getByLabelText("URL").textContent ?? "");
    await expect(query.get("sort")).toBe("modified");
    await expect(query.get("order")).toBe("desc");
  },
};

/** A column header and the select are one state: clicking Title sorts by it and the select follows. */
export const HeaderClickMovesTheSelect: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Title" }));
    await expect(canvas.getByRole("combobox", { name: "Sort by" })).toHaveValue("title");
    await expect(codes(canvas)).toEqual(["DEC-2", "DEC-10", "DEC-1"]);
    await userEvent.click(canvas.getByRole("button", { name: "Title" }));
    await expect(canvas.getByRole("combobox", { name: "Order" })).toHaveValue("desc");
    await expect(codes(canvas)).toEqual(["DEC-1", "DEC-10", "DEC-2"]);
    // A third click on the same column toggles back to ascending: the sort is never empty.
    await userEvent.click(canvas.getByRole("button", { name: "Title" }));
    await expect(canvas.getByRole("combobox", { name: "Order" })).toHaveValue("asc");
    await expect(canvas.getByRole("combobox", { name: "Sort by" })).toHaveValue("title");
  },
};

/** A shared link wins: the address's sort applies even when the person remembered another for this list. */
export const TheAddressWinsOverTheRememberedChoice: Story = {
  decorators: [withStatefulAuth(buildUser({ ui_preferences: { list_sort_demo: "title:desc" } }))],
  parameters: { path: "/list?sort=created&order=asc" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("combobox", { name: "Sort by" })).toHaveValue("created");
    await expect(codes(canvas)).toEqual(["DEC-2", "DEC-1", "DEC-10"]);
  },
};

/** With no sort in the address the person's last choice for this list applies, and an unknown stored key is ignored. */
export const TheRememberedChoiceApplies: Story = {
  decorators: [withStatefulAuth(buildUser({ ui_preferences: { list_sort_demo: "title:desc" } }))],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("combobox", { name: "Sort by" })).toHaveValue("title"));
    await expect(canvas.getByRole("combobox", { name: "Order" })).toHaveValue("desc");
    await expect(codes(canvas)).toEqual(["DEC-1", "DEC-10", "DEC-2"]);
  },
};

export const AnUnknownRememberedKeyIsIgnored: Story = {
  decorators: [withStatefulAuth(buildUser({ ui_preferences: { list_sort_demo: "removed_column:desc" } }))],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("combobox", { name: "Sort by" })).toHaveValue("unique_code");
    await expect(canvas.getByRole("combobox", { name: "Order" })).toHaveValue("asc");
  },
};

/** A list embedded in another page keeps the sort in the component and leaves the address alone. */
export const AnEmbeddedListLeavesTheAddressAlone: Story = {
  args: { local: true },
  parameters: { path: "/list?tab=evidence" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Sort by" }), "title");
    await expect(codes(canvas)).toEqual(["DEC-2", "DEC-10", "DEC-1"]);
    await expect(canvas.getByLabelText("URL").textContent).toBe("?tab=evidence");
  },
};
