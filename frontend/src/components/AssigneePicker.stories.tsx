import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import type { OrgUser } from "../api/types";
import { AssigneePicker } from "./AssigneePicker";

const fewUsers: OrgUser[] = [
  {
    user_id: "u1", email: "alex.morgan@example.com", display_name: "Alex Morgan", is_active: true,
    is_archived: false, roles: ["member"], display_name_locked: false, last_login_at: null, is_2fa_enabled: false, module_roles: [],
  },
  {
    user_id: "u2", email: "jamie.lee@example.com", display_name: "Jamie Lee", is_active: true,
    is_archived: false, roles: ["project_creator"], display_name_locked: false, last_login_at: null, is_2fa_enabled: false, module_roles: [],
  },
];

const meta: Meta<typeof AssigneePicker> = {
  title: "Components/AssigneePicker",
  component: AssigneePicker,
  args: { orgUsers: fewUsers, assigneeId: null, onChange: fn(), ariaLabel: "Assignee" },
};
export default meta;

type Story = StoryObj<typeof AssigneePicker>;

/** Nobody is assigned: no Unassign action, and no org users loaded at all —
 * the search box simply has nothing to match against. */
export const EmptyOrgUnassigned: Story = {
  args: { orgUsers: [], assigneeId: null },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Unassigned")).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: /Unassign/ })).not.toBeInTheDocument();
  },
};

/** A handful of users, client-side filtered (no `organizationId`) — typing
 * narrows to a match and picking it calls `onChange` with that user's id. */
export const FewUsersSearchAndAssign: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByRole("combobox"), "jamie");
    await expect(canvas.getByText("Jamie Lee")).toBeInTheDocument();
    await userEvent.click(canvas.getByText("Jamie Lee"));
    await expect(args.onChange).toHaveBeenCalledWith("u2");
  },
};

/** Already assigned: shows the current assignee and an Unassign action that
 * clears it (`onChange("")`), preserving the old `<select>`'s "Unassigned"
 * empty-option behaviour. */
export const AssignedShowsUnassignAction: Story = {
  args: { assigneeId: "u1" },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Alex Morgan (alex.morgan@example.com)")).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Unassign: Assignee" }));
    await expect(args.onChange).toHaveBeenCalledWith("");
  },
};

/** `organizationId` mode: debounced server-side search, for orgs too large
 * to hand the whole user list to the client. */
export const ManyUsersServerSearchNarrows: Story = {
  args: { orgUsers: [], organizationId: "org-1" },
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue({ members: [fewUsers[1]], external: null });
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByRole("combobox"), "jamie");
    await waitFor(() => expect(canvas.getByText("Jamie Lee")).toBeInTheDocument());
    await userEvent.click(canvas.getByText("Jamie Lee"));
    await expect(args.onChange).toHaveBeenCalledWith("u2");
  },
};

export const LightTheme: Story = { ...FewUsersSearchAndAssign, globals: { theme: "light" } };
export const DarkTheme: Story = { ...FewUsersSearchAndAssign, globals: { theme: "dark" } };
