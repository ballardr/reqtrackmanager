import type { Meta, StoryObj } from "@storybook/react-vite";
import { MemoryRouter } from "react-router-dom";
import { expect, fn, userEvent, within } from "storybook/test";

import type { EffectiveMember, PendingInvite } from "../api/types";
import { ProjectMembersTable } from "./ProjectMembersTable";

const MEMBERS: EffectiveMember[] = [
  {
    user_id: "u-alex",
    display_name: "Alex Morgan",
    email: "alex@example.com",
    effective_role: "project_manager",
    sources: [{ kind: "direct_role", role: "project_manager", via_project_id: null, via_project_name: null, via_mode: null }],
  },
  {
    user_id: "u-priya",
    display_name: "Priya Shah",
    email: "priya@example.com",
    effective_role: "stakeholder",
    sources: [{ kind: "direct_group", role: "stakeholder", via_project_id: null, via_project_name: null, via_mode: null }],
  },
  {
    user_id: "u-jordan",
    display_name: "Jordan Lee",
    email: "jordan@example.com",
    effective_role: "member",
    sources: [
      { kind: "direct_role", role: "member", via_project_id: null, via_project_name: null, via_mode: null },
      { kind: "forward_inherited", role: "stakeholder", via_project_id: "p-parent", via_project_name: "Parent Project", via_mode: "mirror_all" },
    ],
  },
];

const INVITES: PendingInvite[] = [
  {
    id: "inv-1",
    email: "invitee@example.com",
    role: "member",
    status: "pending",
    created_at: "2026-08-01T00:00:00Z",
    expires_at: "2026-09-01T00:00:00Z",
  },
];

const meta: Meta<typeof ProjectMembersTable> = {
  title: "Components/ProjectMembersTable",
  component: ProjectMembersTable,
  decorators: [(Story) => <MemoryRouter><Story /></MemoryRouter>],
  args: {
    members: MEMBERS,
    invites: INVITES,
    onToggleRole: fn(),
    onResendInvite: fn(),
    ariaLabel: "Project members",
  },
};
export default meta;

type Story = StoryObj<typeof ProjectMembersTable>;

/** Real member rows and an invited row render in one table, distinguished
 * by the Role cell's content: a member gets a `MultiSelectDropdown`, an
 * invited row gets a status badge + Resend button. */
export const MixedMembersAndInvited: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("cell", { name: "Alex Morgan" })).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Alex Morgan's roles" })).toBeInTheDocument();
    await expect(canvas.getByText("invitee@example.com")).toBeInTheDocument();
    await expect(canvas.getByText("Pending")).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Resend invite to invitee@example.com" })).toBeInTheDocument();
    // Follow-up UX fix: this table's Role (`MultiSelectDropdown`) and
    // Source (multi-line provenance text) columns crowded the old
    // `.side-grid` sidebar on both call sites, so its own `FilterPanel`
    // now renders `layout="top"` (a full-width bar above the table) —
    // see docs/ux-style-guide.md's "Pattern: filter panel placement —
    // side vs. top". Both call sites (`ProjectAdminPage.tsx`'s Members
    // section, `OrgAdminPage.tsx`'s "Manage users" modal) inherit this
    // automatically since it's composed inside this shared component.
    await expect(canvasElement.querySelector(".filter-panel-top")).toBeInTheDocument();
  },
};

/** No members and no invites at all — a distinct empty-state message from
 * "search/filter matched nothing" (below). */
export const EmptyState: Story = {
  args: { members: [], invites: [] },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("No members yet.")).toBeInTheDocument();
  },
};

/** More rows than one page — `LoadMoreButton` appears, and clicking it
 * reveals the rest without a network request (the whole array is already
 * in memory; see the component's own docstring). */
export const AtScalePaginated: Story = {
  args: {
    invites: [],
    members: Array.from({ length: 45 }, (_, i): EffectiveMember => ({
      user_id: `u-${i}`,
      display_name: `User ${String(i).padStart(2, "0")}`,
      email: `user${i}@example.com`,
      effective_role: "member",
      sources: [{ kind: "direct_role", role: "member", via_project_id: null, via_project_name: null, via_mode: null }],
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

/** A role sourced from a group (not a genuine `direct_role` grant) shows
 * checked but disabled, with a title explaining it must be changed at its
 * actual source — the core Phase D fix: `DELETE /roles` would silently
 * no-op against this option, so it must never look freely toggle-off-able. */
export const DisabledRoleWithExplanatoryTitle: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Priya Shah's roles" }));
    const group = within(document.body).getByRole("group", { name: "Priya Shah's roles" });
    const checkbox = within(group).getByRole("checkbox", { name: "Revoke Stakeholder from Priya Shah" });
    await expect(checkbox).toBeDisabled();
    await expect(checkbox).toHaveAttribute("title", expect.stringContaining("isn't a direct grant"));
  },
};

/** This table's only `direct_role`-sourced `project_manager` has its role
 * control disabled (a fast client-side C-U-08 hint — see the component's
 * own docstring for why the backend guard remains authoritative
 * regardless). */
export const LastManagerRoleControlDisabled: Story = {
  args: {
    invites: [],
    members: [MEMBERS[0]],
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Alex Morgan's roles" }));
    const group = within(document.body).getByRole("group", { name: "Alex Morgan's roles" });
    const checkbox = within(group).getByRole("checkbox", { name: "Revoke Project manager from Alex Morgan" });
    await expect(checkbox).toBeDisabled();
    await expect(checkbox).toHaveAttribute("title", expect.stringContaining("only manager source"));
  },
};

/** Typing into `FilterPanel`'s own search box narrows both member and
 * invited rows by name/email at once, with its own distinct "no results"
 * message from the true-empty state above. */
export const SearchNarrowed: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByRole("textbox", { name: "Search by name or email" }), "priya");
    await expect(canvas.getByRole("cell", { name: "Priya Shah" })).toBeInTheDocument();
    await expect(canvas.queryByRole("cell", { name: "Alex Morgan" })).not.toBeInTheDocument();
    await expect(canvas.queryByText("invitee@example.com")).not.toBeInTheDocument();
  },
};

/** The role `FilterField` narrows to only members holding the selected role
 * via *any* source — Jordan Lee's forward-inherited stakeholder source
 * counts just like Priya's group-derived one, even though neither is a
 * `direct_role` grant. */
export const RoleFiltered: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.selectOptions(canvas.getByLabelText("Role"), "stakeholder");
    await expect(canvas.getByRole("cell", { name: "Priya Shah" })).toBeInTheDocument();
    await expect(canvas.getByRole("cell", { name: "Jordan Lee" })).toBeInTheDocument();
    await expect(canvas.queryByRole("cell", { name: "Alex Morgan" })).not.toBeInTheDocument();
  },
};

/** Unchecking "Show invited" hides pending-invite rows entirely, leaving
 * only real members. */
export const ShowInvitedToggledOff: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("invitee@example.com")).toBeInTheDocument();
    await userEvent.click(canvas.getByLabelText("Show invited"));
    await expect(canvas.queryByText("invitee@example.com")).not.toBeInTheDocument();
    await expect(canvas.getByRole("cell", { name: "Alex Morgan" })).toBeInTheDocument();
  },
};

/** The caller-supplied `addControl` slot renders above the table — this
 * story stands in a plain button since the real controls
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
