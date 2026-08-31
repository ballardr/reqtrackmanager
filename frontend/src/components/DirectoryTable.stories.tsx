import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { MemoryRouter } from "react-router-dom";
import { expect, fn, userEvent, within } from "storybook/test";

import type { DirectoryColumn } from "./DirectoryTable";
import { DirectoryTable } from "./DirectoryTable";
import type { SortState } from "./SortableHeader";

interface DemoRow {
  id: string;
  name: string;
  email: string;
  status: "active" | "invited";
  joined: string;
}

const ROWS: DemoRow[] = [
  { id: "u-alex", name: "Alex Morgan", email: "alex@example.com", status: "active", joined: "2026-01-14" },
  { id: "u-priya", name: "Priya Shah", email: "priya@example.com", status: "active", joined: "2026-03-02" },
  { id: "u-jordan", name: "Jordan Lee", email: "jordan@example.com", status: "invited", joined: "2026-08-20" },
];

const COLUMNS: DirectoryColumn<DemoRow>[] = [
  { key: "name", label: "Name", sortable: true, render: (row) => row.name },
  { key: "email", label: "Email", sortable: true, render: (row) => row.email },
  {
    key: "status",
    label: "Status",
    // Deliberately not sortable — a badge column has no natural order, per
    // style guide "Pattern: sortable column header".
    render: (row) => <span className="badge">{row.status === "active" ? "Active" : "Invited"}</span>,
  },
];

const meta: Meta<typeof DirectoryTable<DemoRow>> = {
  title: "Components/DirectoryTable",
  component: DirectoryTable,
  decorators: [
    (Story) => (
      <MemoryRouter>
        <Story />
      </MemoryRouter>
    ),
  ],
  args: {
    ariaLabel: "Demo directory",
    columns: COLUMNS,
    rows: ROWS,
    rowKey: (row: DemoRow) => row.id,
    emptyState: <p className="text-muted">No rows yet.</p>,
  },
};
export default meta;

type Story = StoryObj<typeof DirectoryTable<DemoRow>>;

/** A live sort demo: two sortable columns (Name, Email) alongside one
 * non-sortable badge column (Status) — clicking a sortable header cycles
 * `aria-sort` via the shared `SortableHeader`/`cycleSort`, exactly the
 * contract this component hands back to its caller (it never sorts `rows`
 * itself). */
function SortDemo() {
  const [sort, setSort] = useState<SortState | null>(null);
  const sorted = sort
    ? [...ROWS].sort((a, b) => {
        const dir = sort.direction === "asc" ? 1 : -1;
        const av = sort.key === "name" ? a.name : a.email;
        const bv = sort.key === "name" ? b.name : b.email;
        return av.localeCompare(bv) * dir;
      })
    : ROWS;
  return (
    <DirectoryTable
      ariaLabel="Demo directory"
      columns={COLUMNS}
      rows={sorted}
      rowKey={(row) => row.id}
      sort={sort}
      onSort={(key) => {
        setSort((current) => {
          if (!current || current.key !== key) return { key, direction: "asc" };
          if (current.direction === "asc") return { key, direction: "desc" };
          return null;
        });
      }}
      emptyState={<p className="text-muted">No rows yet.</p>}
    />
  );
}

export const BasicSortableTable: Story = {
  render: () => <SortDemo />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    // Non-sortable Status column renders as a plain columnheader, no button.
    await expect(canvas.getByRole("columnheader", { name: "Status" })).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Status" })).not.toBeInTheDocument();

    const nameHeader = canvas.getByRole("button", { name: "Name" });
    await expect(nameHeader.closest("th")).toHaveAttribute("aria-sort", "none");
    await userEvent.click(nameHeader);
    await expect(nameHeader.closest("th")).toHaveAttribute("aria-sort", "ascending");

    const rows = canvas.getAllByRole("row").slice(1); // drop the header row
    await expect(within(rows[0]).getByText("Alex Morgan")).toBeInTheDocument();
  },
};

/** `onRowClick` renders the first column's content as a real `<button>` —
 * keyboard-operable, and firing the caller's callback with the clicked
 * row, not the whole `<tr>`. */
export const OnRowClickMakesFirstCellAButton: Story = {
  args: { onRowClick: fn() },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const trigger = canvas.getByRole("button", { name: "Alex Morgan" });
    await userEvent.click(trigger);
    await expect(args.onRowClick).toHaveBeenCalledWith(ROWS[0]);
    // Other columns in the same row stay plain, non-interactive text.
    await expect(canvas.queryByRole("button", { name: "alex@example.com" })).not.toBeInTheDocument();
  },
};

/** `rowHref` renders the first column's content as a real `<Link>` instead
 * — bookmarkable/deep-linkable, unlike a click handler. */
export const RowHrefMakesFirstCellALink: Story = {
  args: { rowHref: (row: DemoRow) => `/users/${row.id}` },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const link = canvas.getByRole("link", { name: "Alex Morgan" });
    await expect(link).toHaveAttribute("href", "/users/u-alex");
  },
};

/** `rowHref` wins if a caller somehow passes both — see the component's
 * own docstring for why. */
export const RowHrefTakesPriorityOverOnRowClick: Story = {
  args: { rowHref: (row: DemoRow) => `/users/${row.id}`, onRowClick: fn() },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("link", { name: "Alex Morgan" })).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Alex Morgan" })).not.toBeInTheDocument();
  },
};

/** Neither `onRowClick` nor `rowHref` set — every cell, including the
 * first column, is plain non-interactive text (Server Admin's Access
 * Review, which has no per-row detail panel). */
export const NeitherOnRowClickNorRowHref: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("cell", { name: "Alex Morgan" })).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Alex Morgan" })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("link", { name: "Alex Morgan" })).not.toBeInTheDocument();
  },
};

/** No rows at all — the caller's `emptyState` renders in place of the
 * table entirely, not an empty `<table>` with a header row and no body. */
export const EmptyState: Story = {
  args: { rows: [], emptyState: <p className="text-muted">No members match this search.</p> },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("No members match this search.")).toBeInTheDocument();
    await expect(canvas.queryByRole("table")).not.toBeInTheDocument();
  },
};

/** More rows loaded than `total` — `LoadMoreButton` appears below the
 * table and calls `onLoadMore` on click, the same contract that component
 * already establishes elsewhere in the app. */
export const PaginatedWithLoadMore: Story = {
  args: { total: 45, onLoadMore: fn() },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const loadMore = canvas.getByRole("button", { name: /Load more/i });
    await expect(loadMore).toHaveTextContent("3/45");
    await userEvent.click(loadMore);
    await expect(args.onLoadMore).toHaveBeenCalledOnce();
  },
};

/** `total` already met by the loaded `rows` — no `LoadMoreButton` at all,
 * matching that component's own "loaded >= total renders nothing" rule. */
export const NoLoadMoreOnceFullyLoaded: Story = {
  args: { total: ROWS.length, onLoadMore: fn() },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByRole("button", { name: /Load more/i })).not.toBeInTheDocument();
  },
};

export const LightTheme: Story = { globals: { theme: "light" } };
export const DarkTheme: Story = { globals: { theme: "dark" } };
