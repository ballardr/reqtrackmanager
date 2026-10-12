import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, within } from "storybook/test";

import type { OrgUser } from "../api/types";
import { PrincipalFormField } from "./PrincipalFormField";

const users: OrgUser[] = [
  {
    user_id: "u1", email: "alex.morgan@example.com", display_name: "Alex Morgan", is_active: true,
    is_archived: false, roles: ["member"], display_name_locked: false, last_login_at: null, is_2fa_enabled: false, module_roles: [], custom_roles: [],
  },
];

const meta: Meta<typeof PrincipalFormField> = {
  title: "Components/PrincipalFormField",
  component: PrincipalFormField,
  args: { label: "Owner", orgUsers: users, value: null, onChange: fn(), ariaLabel: "Owner", kinds: ["user"] },
};
export default meta;

type Story = StoryObj<typeof PrincipalFormField>;

/** An empty field: the caption, "Unassigned" and the search input. */
export const Empty: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Owner")).toBeInTheDocument();
    await expect(canvas.getByText("Unassigned")).toBeInTheDocument();
    await expect(canvas.getByRole("combobox")).toBeInTheDocument();
  },
};

/** A set field offers the action that clears it. */
export const Assigned: Story = {
  args: { value: { type: "user", id: "u1" }, clearLabel: "Clear" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("button", { name: "Clear: Owner" })).toBeInTheDocument();
  },
};
