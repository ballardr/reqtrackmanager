import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import type { OrgGroup, OrgUser } from "../api/types";
import { AddToGroupControl } from "./AddToGroupControl";

const USER: OrgUser = {
  user_id: "user-2", email: "jordan@example.com", display_name: "Jordan Lee", is_active: true,
  is_archived: false, roles: ["member"], display_name_locked: false, last_login_at: null, is_2fa_enabled: false,
};

const GROUPS: OrgGroup[] = [
  { id: "grp1", name: "Engineering", member_user_ids: [], member_org_group_ids: [], idp_synced_group_name: null, granted_org_role: null },
  { id: "grp2", name: "Platform", member_user_ids: ["user-2"], member_org_group_ids: [], idp_synced_group_name: null, granted_org_role: null },
];

const meta: Meta<typeof AddToGroupControl> = {
  title: "Components/AddToGroupControl",
  component: AddToGroupControl,
  args: {
    user: USER,
    groups: GROUPS,
    onAdd: fn(),
  },
};
export default meta;

type Story = StoryObj<typeof AddToGroupControl>;

/** Only groups the user isn't already a member of are offered — Jordan is
 * already in "Platform" (`grp2`), so only "Engineering" appears in the
 * picker. Picking a group and confirming calls `onAdd(groupId, userId)`,
 * the caller's own existing `addGroupMember` handler. */
export const PicksAnAvailableGroup: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Add Jordan Lee to a group" }));
    const popover = within(document.body).getByRole("dialog", { name: "Add Jordan Lee to a group" });

    const select = within(popover).getByLabelText("Group");
    await expect(within(select).getByText("Engineering")).toBeInTheDocument();
    await expect(within(select).queryByText("Platform")).not.toBeInTheDocument();

    await expect(within(popover).getByRole("button", { name: "Add" })).toBeDisabled();
    await userEvent.selectOptions(select, "grp1");
    await userEvent.click(within(popover).getByRole("button", { name: "Add" }));

    await expect(args.onAdd).toHaveBeenCalledWith("grp1", "user-2");
    await expect(within(document.body).queryByRole("dialog")).not.toBeInTheDocument();
  },
};

/** Renders nothing at all when the user is already a member of every group
 * in the organisation — nothing left to add them to, so no trigger button
 * appears rather than a picker with an empty/useless list. */
export const HiddenWhenAlreadyInEveryGroup: Story = {
  args: {
    groups: [GROUPS[1]], // only the group Jordan is already in
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByRole("button", { name: "Add Jordan Lee to a group" })).not.toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...PicksAnAvailableGroup, globals: { theme: "light" } };
export const DarkTheme: Story = { ...PicksAnAvailableGroup, globals: { theme: "dark" } };
