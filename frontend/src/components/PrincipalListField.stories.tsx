import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import type { OrgGroup, OrgUser, Principal } from "../api/types";
import { PrincipalListField } from "./PrincipalListField";

const users: OrgUser[] = [
  {
    user_id: "u1", email: "alex.morgan@example.com", display_name: "Alex Morgan", is_active: true,
    is_archived: false, roles: ["member"], display_name_locked: false, last_login_at: null, is_2fa_enabled: false, module_roles: [], custom_roles: [],
  },
  {
    user_id: "u2", email: "jamie.lee@example.com", display_name: "Jamie Lee", is_active: true,
    is_archived: false, roles: ["member"], display_name_locked: false, last_login_at: null, is_2fa_enabled: false, module_roles: [], custom_roles: [],
  },
];
const groups: OrgGroup[] = [
  { id: "g1", name: "Platform team", member_user_ids: ["u1", "u2"], member_org_group_ids: [], idp_synced_group_name: null, granted_org_role: null },
];
const alex: Principal = { type: "user", id: "u1", label: "Alex Morgan (alex.morgan@example.com)", member_count: null, exists: true };
const team: Principal = { type: "org_group", id: "g1", label: "Platform team", member_count: 2, exists: true };

const meta: Meta<typeof PrincipalListField> = {
  title: "Components/PrincipalListField",
  component: PrincipalListField,
  args: {
    label: "Facilitators", ariaLabel: "Facilitator", values: [alex], orgUsers: users, organizationId: "org-1",
    kinds: ["user", "org_group"], onChange: fn(),
  },
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.endsWith("/orgs/org-1/groups")) return groups as never;
      return { members: [], external: null } as never;
    });
  },
};
export default meta;

type Story = StoryObj<typeof PrincipalListField>;

/** Entries show as chips; the (+) opens the search and picking one reports the whole new list. */
export const AddsToTheList: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Alex Morgan (alex.morgan@example.com)")).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Add to Facilitators" }));
    const popover = within(within(document.body).getByRole("dialog", { name: "Add to Facilitators" }));
    await userEvent.type(popover.getByRole("combobox", { name: "Facilitator" }), "platform");
    await userEvent.click(await popover.findByText("Platform team"));
    await expect(args.onChange).toHaveBeenCalledWith([{ type: "user", id: "u1" }, { type: "org_group", id: "g1" }]);
    await waitFor(() => expect(within(document.body).queryByRole("dialog")).not.toBeInTheDocument());
  },
};

/** Someone already listed is not added twice. */
export const IgnoresADuplicate: Story = {
  args: { values: [team] },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Add to Facilitators" }));
    const popover = within(within(document.body).getByRole("dialog", { name: "Add to Facilitators" }));
    await userEvent.type(popover.getByRole("combobox", { name: "Facilitator" }), "platform");
    await userEvent.click(await popover.findByText("Platform team"));
    await expect(args.onChange).not.toHaveBeenCalled();
    await waitFor(() => expect(within(document.body).queryByRole("dialog")).not.toBeInTheDocument());
  },
};

/** The "x" on a chip reports the list without it. */
export const RemovesAnEntry: Story = {
  args: { values: [alex, team] },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Remove Platform team" }));
    await expect(args.onChange).toHaveBeenCalledWith([{ type: "user", id: "u1" }]);
  },
};

/** Empty: the hint shows. Read-only: no (+) and no "x". */
export const EmptyShowsTheHint: Story = {
  args: { values: [], emptyText: "Nobody is recorded as running it." },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("Nobody is recorded as running it.")).toBeInTheDocument();
  },
};

export const ReadOnlyHasNoControls: Story = {
  args: { values: [alex, team], readOnly: true },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).queryByRole("button")).not.toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...RemovesAnEntry, globals: { theme: "light" } };
export const DarkTheme: Story = { ...RemovesAnEntry, globals: { theme: "dark" } };
