import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import type { OrgUser } from "../api/types";
import { UserAutocomplete } from "./UserAutocomplete";

const localUsers: OrgUser[] = [
  {
    user_id: "u1", email: "alex.morgan@example.com", display_name: "Alex Morgan", is_active: true,
    is_archived: false, roles: ["member"], display_name_locked: false, last_login_at: null, is_2fa_enabled: false,
  },
  {
    user_id: "u2", email: "jamie.lee@example.com", display_name: "Jamie Lee", is_active: true,
    is_archived: false, roles: ["project_creator"], display_name_locked: false, last_login_at: null, is_2fa_enabled: false,
  },
];

const meta: Meta<typeof UserAutocomplete> = {
  title: "Components/UserAutocomplete",
  component: UserAutocomplete,
  args: { users: localUsers, onSelect: fn(), placeholder: "Add a user…" },
};
export default meta;

type Story = StoryObj<typeof UserAutocomplete>;

/** Default mode: filters the already-loaded `users` array locally, no API call. */
export const LocalFilterMode: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const input = canvas.getByPlaceholderText("Add a user…");
    await userEvent.type(input, "jamie");
    await expect(canvas.getByText("Jamie Lee")).toBeInTheDocument();
    await expect(canvas.queryByText("Alex Morgan")).not.toBeInTheDocument();
    await userEvent.click(canvas.getByText("Jamie Lee"));
    await expect(args.onSelect).toHaveBeenCalledWith("u2");
  },
};

/** `organizationId` mode: debounced server-side search, with a synthetic
 * "external" result for an email not yet a member of this org. */
export const ServerSearchModeWithExternalMatch: Story = {
  args: {
    organizationId: "org-1",
    onSelectExternal: fn(),
  },
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue({
      members: [{ ...localUsers[0] }],
      external: { email: "new.person@example.com", exists: false },
    });
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const input = canvas.getByPlaceholderText("Add a user…");
    await userEvent.type(input, "new.person");
    await waitFor(() => expect(canvas.getByText(/Invite new.person@example.com/)).toBeInTheDocument());
    await expect(canvas.getByText("Alex Morgan")).toBeInTheDocument();
    await userEvent.click(canvas.getByText(/Invite new.person@example.com/));
    await expect(args.onSelectExternal).toHaveBeenCalledWith("new.person@example.com");
  },
};

export const NoMatches: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByPlaceholderText("Add a user…"), "nobody");
    await expect(canvas.queryByText(/Alex Morgan|Jamie Lee/)).not.toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...LocalFilterMode, globals: { theme: "light" } };
export const DarkTheme: Story = { ...LocalFilterMode, globals: { theme: "dark" } };
