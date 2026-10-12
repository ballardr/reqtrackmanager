import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import type { OrgUser } from "../api/types";
import { GroupInUseDialog } from "./GroupInUseDialog";

const users: OrgUser[] = [
  {
    user_id: "u2", email: "jamie.lee@example.com", display_name: "Jamie Lee", is_active: true,
    is_archived: false, roles: ["member"], display_name_locked: false, last_login_at: null, is_2fa_enabled: false, module_roles: [], custom_roles: [],
  },
];

const meta: Meta<typeof GroupInUseDialog> = {
  title: "Components/GroupInUseDialog",
  component: GroupInUseDialog,
  args: {
    groupName: "Platform team",
    groupId: "g1",
    organizationId: "org-1",
    orgUsers: users,
    kinds: ["user"],
    usage: { total: 5, mandatory_total: 3, items: [{ label: "decision owners", count: 3, mandatory: true }, { label: "decision makers", count: 2, mandatory: false }] },
    onReplace: fn(async () => {}),
    onClear: fn(async () => {}),
    onClose: fn(),
  },
};
export default meta;

type Story = StoryObj<typeof GroupInUseDialog>;

const body = () => within(document.body);

/** A required field names the group, so clearing is unavailable and a replacement is the only way out. */
export const MandatoryUsageRequiresReplacement: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue({ members: users, external: null });
  },
  play: async ({ args }) => {
    const dialog = within(await body().findByRole("dialog", { name: "Delete “Platform team”?" }));
    await expect(dialog.getByText("“Platform team” is still named on 3 decision owners, 2 decision makers.")).toBeInTheDocument();
    await expect(dialog.getByRole("button", { name: "Clear them and delete…" })).toBeDisabled();
    const confirm = dialog.getByRole("button", { name: "Confirm delete" });
    await userEvent.type(dialog.getByRole("combobox", { name: "New owner" }), "jamie");
    await userEvent.click(await dialog.findByText("Jamie Lee"));
    await expect(confirm).toBeEnabled();
    await userEvent.click(confirm);
    await waitFor(() => expect(args.onReplace).toHaveBeenCalledWith({ type: "user", id: "u2" }));
  },
};

/** Only optional fields name the group: they can be cleared after typing the group's name. */
export const OptionalUsageCanBeCleared: Story = {
  args: { usage: { total: 2, mandatory_total: 0, items: [{ label: "decision makers", count: 2, mandatory: false }] } },
  play: async ({ args }) => {
    const dialog = within(await body().findByRole("dialog", { name: "Delete “Platform team”?" }));
    await userEvent.click(dialog.getByRole("button", { name: "Clear them and delete…" }));
    await userEvent.type(await body().findByRole("textbox", { name: /Platform team/ }), "Platform team");
    await userEvent.click(body().getByRole("button", { name: "Delete group" }));
    await waitFor(() => expect(args.onClear).toHaveBeenCalled());
  },
};
