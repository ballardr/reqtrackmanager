import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import type { OrgUser } from "../api/types";
import { expectStressStable, stressText } from "../testing/stressFixtures";
import { TextStress } from "../testing/TextStress";
import { DirectoryTable } from "./DirectoryTable";
import { OrgUserNameCell } from "./OrgUserNameCell";

const meta: Meta<typeof OrgUserNameCell> = {
  title: "Components/OrgUserNameCell",
  component: OrgUserNameCell,
  args: { onOpenServiceUser: fn() },
};
export default meta;

type Story = StoryObj<typeof OrgUserNameCell>;

function user(overrides: Partial<OrgUser> = {}): OrgUser {
  return {
    user_id: "u-1", email: "alex@example.com", display_name: "Alex Morgan", is_active: true, is_archived: false, roles: ["member"],
    display_name_locked: false, last_login_at: null, is_2fa_enabled: false, module_roles: [], custom_roles: [], ...overrides,
  };
}

/** A person's name is plain text: nothing opens from it. */
export const Person: Story = {
  args: { user: user() },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Alex Morgan")).toBeInTheDocument();
    await expect(canvas.queryByRole("button")).not.toBeInTheDocument();
    await expect(canvas.queryByText("Service")).not.toBeInTheDocument();
  },
};

/** A service user's name opens its dialog, beside the Service label and its review flags. */
export const ServiceUser: Story = {
  args: { user: user({ user_id: "su-1", display_name: "Build agent", is_service_account: true, service_flags: ["no_responsible", "administrator"] }) },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Build agent" }));
    await expect(args.onOpenServiceUser).toHaveBeenCalledWith("su-1");
    await expect(canvas.getByText("Service")).toBeInTheDocument();
    await expect(canvas.getByText("No responsible party")).toBeInTheDocument();
    await expect(canvas.getByText("Administrator rights")).toBeInTheDocument();
  },
};

/** Long names, an unbroken word and both flags in several rows keep the table's shape (the long-text rule). */
export const LongText: Story = {
  render: (args) => (
    <TextStress
      render={(long) => (
        <DirectoryTable
          ariaLabel="Users"
          rowKey={(u: OrgUser) => u.user_id}
          rows={[
            user({ user_id: "u-1", display_name: stressText(long, "Alex Morgan") }),
            user({ user_id: "su-1", display_name: stressText(long, "Build agent"), is_service_account: true, service_flags: ["no_responsible", "administrator"] }),
            user({ user_id: "su-2", display_name: stressText(long, "Report mailer", "word"), is_service_account: true, service_flags: ["administrator"] }),
          ]}
          columns={[
            { key: "name", label: "Name", render: (u: OrgUser) => <OrgUserNameCell user={u} onOpenServiceUser={args.onOpenServiceUser} /> },
            { key: "role", label: "Role", render: () => "Member" },
            { key: "login", label: "Last login", render: () => "1/2/2026" },
          ]}
          emptyState={null}
        />
      )}
    />
  ),
  args: { user: user() },
  play: async ({ canvasElement }) => { await expectStressStable(canvasElement); },
};
