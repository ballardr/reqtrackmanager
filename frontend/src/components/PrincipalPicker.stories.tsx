import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import type { OrgGroup, OrgUser, Principal, ProjectGroup } from "../api/types";
import { PrincipalPicker } from "./PrincipalPicker";

const fewUsers: OrgUser[] = [
  {
    user_id: "u1", email: "alex.morgan@example.com", display_name: "Alex Morgan", is_active: true,
    is_archived: false, roles: ["member"], display_name_locked: false, last_login_at: null, is_2fa_enabled: false, module_roles: [], custom_roles: [],
  },
  {
    user_id: "u2", email: "jamie.lee@example.com", display_name: "Jamie Lee", is_active: true,
    is_archived: false, roles: ["project_creator"], display_name_locked: false, last_login_at: null, is_2fa_enabled: false, module_roles: [], custom_roles: [],
  },
];

const orgGroups: OrgGroup[] = [
  { id: "g1", name: "Platform team", member_user_ids: ["u1", "u2"], member_org_group_ids: [], idp_synced_group_name: null, granted_org_role: null },
];
const projectGroups: ProjectGroup[] = [
  { id: "pg1", name: "Release board", roles: [], member_user_ids: ["u1"], member_org_group_ids: [], member_source_project_ids: [] },
];

const meta: Meta<typeof PrincipalPicker> = {
  title: "Components/PrincipalPicker",
  component: PrincipalPicker,
  args: { orgUsers: fewUsers, value: null, onChange: fn(), ariaLabel: "Owner", kinds: ["user"] },
};
export default meta;

type Story = StoryObj<typeof PrincipalPicker>;

/** Nobody is assigned: no Unassign action, and no org users loaded at all. */
export const EmptyOrgUnassigned: Story = {
  args: { orgUsers: [] },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Unassigned")).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: /Unassign/ })).not.toBeInTheDocument();
  },
};

/** A user-only field: typing narrows to a user and picking it calls `onChange` with a user principal. */
export const UserOnlySearchAndAssign: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByRole("combobox"), "jamie");
    await userEvent.click(canvas.getByText("Jamie Lee"));
    await expect(args.onChange).toHaveBeenCalledWith({ type: "user", id: "u2" });
  },
};

/** An assigned user shows their name and an Unassign action that clears the field (`onChange(null)`). */
export const AssignedUserShowsUnassign: Story = {
  args: { value: { type: "user", id: "u1" } },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Alex Morgan (alex.morgan@example.com)")).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Unassign: Owner" }));
    await expect(args.onChange).toHaveBeenCalledWith(null);
  },
};

/** A field that allows groups lists the organisation's and the project's groups next to users, each tagged with its kind. */
export const GroupsAreOffered: Story = {
  args: { kinds: ["user", "org_group", "project_group"], organizationId: "org-1", projectId: "proj-1", orgUsers: [] },
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.endsWith("/orgs/org-1/groups")) return orgGroups as never;
      if (path.endsWith("/projects/proj-1/groups")) return projectGroups as never;
      return { members: [], external: null } as never;
    });
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByRole("combobox"), "platform");
    await waitFor(() => expect(canvas.getByText("Platform team")).toBeInTheDocument());
    await userEvent.click(canvas.getByText("Platform team"));
    await expect(args.onChange).toHaveBeenCalledWith({ type: "org_group", id: "g1" });
    await userEvent.type(canvas.getByRole("combobox"), "release");
    await userEvent.click(await canvas.findByText("Release board"));
    await expect(args.onChange).toHaveBeenCalledWith({ type: "project_group", id: "pg1" });
  },
};

const ownerGroup: Principal = { type: "org_group", id: "g1", label: "Platform team", member_count: 4, exists: true };

/** A group value shows its name, its kind and how many people it stands for (taken from the record's own `display`). */
export const AssignedGroupShowsKindAndMembers: Story = {
  args: { kinds: ["user", "org_group"], value: { type: "org_group", id: "g1" }, display: ownerGroup },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Platform team")).toBeInTheDocument();
    await expect(canvas.getByText("Org group · 4 members")).toBeInTheDocument();
  },
};

/** Compact: no open search box; a (+) opens it in a popover, and picking someone assigns and closes it. */
export const CompactAssignsFromAPopover: Story = {
  args: { compact: true },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Unassigned")).toBeInTheDocument();
    await expect(canvas.queryByRole("combobox")).not.toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Assign: Owner" }));
    const popover = within(within(document.body).getByRole("dialog", { name: "Assign: Owner" }));
    await userEvent.type(popover.getByRole("combobox", { name: "Owner" }), "jamie");
    await userEvent.click(popover.getByText("Jamie Lee"));
    await expect(args.onChange).toHaveBeenCalledWith({ type: "user", id: "u2" });
    await waitFor(() => expect(within(document.body).queryByRole("dialog")).not.toBeInTheDocument());
  },
};

/** Compact with a value: a "Change" pencil and an "x" that unassigns. */
export const CompactAssignedChangesOrClears: Story = {
  args: { compact: true, value: { type: "user", id: "u1" } },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Alex Morgan (alex.morgan@example.com)")).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Change: Owner" })).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Unassign: Owner" }));
    await expect(args.onChange).toHaveBeenCalledWith(null);
  },
};

export const LightTheme: Story = { ...AssignedGroupShowsKindAndMembers, globals: { theme: "light" } };
export const DarkTheme: Story = { ...AssignedGroupShowsKindAndMembers, globals: { theme: "dark" } };
