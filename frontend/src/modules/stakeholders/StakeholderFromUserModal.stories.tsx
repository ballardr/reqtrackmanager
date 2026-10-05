import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import type { OrgUser } from "../../api/types";
import { StakeholderFromUserModal } from "./StakeholderFromUserModal";

const ORG_USERS: OrgUser[] = [
  {
    user_id: "user-2", email: "jamie.lee@example.com", display_name: "Jamie Lee", is_active: true, is_archived: false,
    roles: ["member"], display_name_locked: false, last_login_at: null, is_2fa_enabled: false, module_roles: [], custom_roles: [],
  },
];

const meta: Meta<typeof StakeholderFromUserModal> = {
  title: "Modules/Stakeholders/StakeholderFromUserModal",
  component: StakeholderFromUserModal,
  args: {
    scopeLabel: "project", orgUsers: ORG_USERS, typeOptions: [{ value: "stype-customer", label: "Customer" }],
    onCancel: fn(), onSave: fn(),
  },
};
export default meta;

type Story = StoryObj<typeof StakeholderFromUserModal>;

const dialog = () => within(within(document.body).getByRole("dialog"));

export const NeedsAUserBeforeSaving: Story = {
  play: async () => {
    await expect(within(document.body).getByRole("heading", { name: "Add Stakeholder from organisation user (project)" })).toBeInTheDocument();
    await expect(dialog().getByRole("button", { name: "Add Stakeholder" })).toBeDisabled();
  },
};

export const SavesThePickedUser: Story = {
  play: async ({ args }) => {
    await userEvent.type(dialog().getByLabelText("Organisation user"), "Jamie");
    await waitFor(() => dialog().getByText(/Jamie Lee/));
    await userEvent.click(dialog().getByText(/Jamie Lee/));
    await userEvent.selectOptions(dialog().getByLabelText("Type"), "stype-customer");
    await userEvent.type(dialog().getByLabelText("Role"), "Product owner");
    await userEvent.click(dialog().getByRole("button", { name: "Add Stakeholder" }));
    await expect(args.onSave).toHaveBeenCalledWith({ user_id: "user-2", stakeholder_type_id: "stype-customer", role: "Product owner" });
  },
};

export const ShowsError: Story = {
  args: { error: "A Stakeholder already represents this user." },
  play: async () => {
    await expect(dialog().getByText("A Stakeholder already represents this user.")).toBeInTheDocument();
  },
};

export const DarkTheme: Story = { ...NeedsAUserBeforeSaving, globals: { theme: "dark" } };
