import type { Meta, StoryObj } from "@storybook/react-vite";
import { MemoryRouter } from "react-router-dom";
import { expect, fn, userEvent, within } from "storybook/test";

import type { MemberRoleRow } from "./MemberRoleTable";
import { MemberRoleTable } from "./MemberRoleTable";

const MIXED_ROWS: MemberRoleRow[] = [
  { kind: "group", id: "g-managers", name: "Project Managers", email: null, role: "project_manager", memberCount: 2, isDefault: true },
  { kind: "group", id: "g-reviewers", name: "Reviewers", email: null, role: "stakeholder", memberCount: 3, isDefault: false },
  { kind: "user", id: "u-alex", name: "Alex Morgan", email: "alex@example.com", roles: ["stakeholder", "member"] },
  { kind: "user", id: "u-priya", name: "Priya Shah", email: "priya@example.com", roles: ["project_administrator"] },
];

const meta: Meta<typeof MemberRoleTable> = {
  title: "Components/MemberRoleTable",
  component: MemberRoleTable,
  decorators: [(Story) => <MemoryRouter><Story /></MemoryRouter>],
  args: {
    rows: MIXED_ROWS,
    onToggleUserRole: fn(),
    onChangeGroupRole: fn(),
    ariaLabel: "Members and groups",
  },
};
export default meta;

type Story = StoryObj<typeof MemberRoleTable>;

/** Both row kinds render in one table, distinguished by the Type column —
 * a user row's Role cell is a `MultiSelectDropdown` (multi-valued), a
 * group row's is a plain `<select>` (single-valued), deliberately
 * different controls for the same column. */
export const MixedUserAndGroupRows: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("cell", { name: "Project Managers" })).toBeInTheDocument();
    await expect(canvas.getByRole("cell", { name: "Alex Morgan" })).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Alex Morgan's roles" })).toBeInTheDocument();
    await expect(canvas.getByRole("combobox", { name: "Role for Project Managers" })).toBeInTheDocument();
  },
};

/** No rows at all — a distinct empty-state message from "search matched
 * nothing" (below). */
export const EmptyState: Story = {
  args: { rows: [] },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("No direct members or groups yet.")).toBeInTheDocument();
  },
};

/** More rows than one page — `LoadMoreButton` appears, and clicking it
 * reveals the rest without a network request (the whole array is already
 * in memory; see the component's own docstring). */
export const AtScalePaginated: Story = {
  args: {
    rows: Array.from({ length: 45 }, (_, i): MemberRoleRow => ({
      kind: "user", id: `u-${i}`, name: `User ${String(i).padStart(2, "0")}`, email: `user${i}@example.com`, roles: ["member"],
    })),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getAllByRole("row")).toHaveLength(21); // header + 20
    await expect(canvas.getByRole("button", { name: /Load more/ })).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: /Load more/ }));
    await expect(canvas.getAllByRole("row")).toHaveLength(41); // header + 40
  },
};

/** This table's only `project_manager`-granting row has its role control
 * disabled (a fast client-side C-U-08 hint — see the component's own
 * docstring for why the backend guard remains authoritative regardless). */
export const LastManagerRoleControlDisabled: Story = {
  args: {
    rows: [
      { kind: "group", id: "g-managers", name: "Project Managers", email: null, role: "project_manager", memberCount: 1, isDefault: true },
      { kind: "user", id: "u-alex", name: "Alex Morgan", email: "alex@example.com", roles: ["member"] },
    ],
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const select = canvas.getByRole("combobox", { name: "Role for Project Managers" }) as HTMLSelectElement;
    await expect(select).toBeDisabled();
    await expect(select).toHaveAttribute("title", expect.stringContaining("only manager source"));
  },
};

/** Typing into the search box narrows both row kinds by name/email at
 * once, with its own distinct "no results" message from the true-empty
 * state above. */
export const SearchNarrowed: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByRole("textbox", { name: "Members and groups" }), "priya");
    await expect(canvas.getByRole("cell", { name: "Priya Shah" })).toBeInTheDocument();
    await expect(canvas.queryByRole("cell", { name: "Alex Morgan" })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("cell", { name: "Project Managers" })).not.toBeInTheDocument();

    await userEvent.clear(canvas.getByRole("textbox", { name: "Members and groups" }));
    await userEvent.type(canvas.getByRole("textbox", { name: "Members and groups" }), "nobody-matches-this");
    await expect(canvas.getByText("No members or groups match this search.")).toBeInTheDocument();
  },
};

/** The caller-supplied `addControl` slot renders inline next to the search
 * box — this story stands in a plain button since the real controls
 * (`UserAutocomplete` + a role `<select>`) are exercised by the pages that
 * actually compose them. */
export const WithAddControl: Story = {
  args: {
    addControl: <button className="btn btn-primary">Add member…</button>,
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("button", { name: "Add member…" })).toBeInTheDocument();
  },
};

export const LightTheme: Story = { globals: { theme: "light" } };
export const DarkTheme: Story = { globals: { theme: "dark" } };
