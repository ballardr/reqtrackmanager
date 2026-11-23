import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import type { OrgGroup, OrgUser, ProjectGroup } from "../api/types";
import { expectTextRows } from "../testing/menuRows";
import { UserAutocomplete } from "./UserAutocomplete";

const localUsers: OrgUser[] = [
  {
    user_id: "u1", email: "alex.morgan@example.com", display_name: "Alex Morgan", is_active: true,
    is_archived: false, roles: ["member"], display_name_locked: false, last_login_at: null, is_2fa_enabled: false, module_roles: [], custom_roles: [],
  },
  {
    user_id: "u2", email: "jamie.lee@example.com", display_name: "Jamie Lee", is_active: true,
    is_archived: false, roles: ["project_creator"], display_name_locked: false, last_login_at: null, is_2fa_enabled: false, module_roles: [], custom_roles: [],
  },
];

// Org groups for the optional `groups`/`onSelectGroup` pair, matched client-side (see the component's module docstring).
// "Jamie's Team" overlaps the "jamie" needle with `localUsers[1]` ("Jamie Lee"), so one query exercises both a user and a
// group option in `KeyboardNavigationMovesThroughGroupOptionsToo`.
const localGroups: OrgGroup[] = [
  { id: "g1", name: "Engineering", member_user_ids: [], member_org_group_ids: [], idp_synced_group_name: null, granted_org_role: null },
  { id: "g2", name: "Jamie's Team", member_user_ids: [], member_org_group_ids: [], idp_synced_group_name: null, granted_org_role: null },
];

// This project's own groups for the optional `projectGroups`/`onSelectProjectGroup` pair, matched client-side like
// `groups`. A project group is local to one project, not org-wide, so it has its own icon (`FolderKanban` instead of
// `Users`) and badge ("Project group" instead of "Organisation group").
const localProjectGroups: ProjectGroup[] = [
  { id: "pg1", name: "Reviewers", roles: ["stakeholder"], member_user_ids: [], member_org_group_ids: [], member_source_project_ids: [] },
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
    // Options are plain text rows like every menu, never standard buttons.
    await expectTextRows(canvas.getByRole("listbox"));
    await userEvent.click(canvas.getByText("Jamie Lee"));
    await expect(args.onSelect).toHaveBeenCalledWith("u2");
  },
};

/** Passing `groups` also matches org groups by name, client-side, alongside the user matches, rendered with a `Users`
 * icon and an "Organisation group" badge; selecting one calls `onSelectGroup` (not `onSelect`). */
export const GroupMatchRendersAndSelects: Story = {
  args: { groups: localGroups, onSelectGroup: fn() },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const input = canvas.getByPlaceholderText("Add a user…");
    await userEvent.type(input, "engineer");
    const option = canvas.getByRole("option", { name: /Engineering/ });
    await expect(option).toHaveTextContent("Organisation group");
    // No user matches "engineer" — the group match is the only option.
    await expect(canvas.queryByText("Alex Morgan")).not.toBeInTheDocument();

    await userEvent.click(option);
    await expect(args.onSelectGroup).toHaveBeenCalledWith("g1");
    await expect(args.onSelect).not.toHaveBeenCalled();
    // Closes/resets the same way a user pick does.
    await expect(input).toHaveValue("");
  },
};

/** Passing `projectGroups` also matches this project's own groups by name, client-side, with a `FolderKanban` icon and a
 * "Project group" badge; selecting one calls `onSelectProjectGroup` (not `onSelect`/`onSelectGroup`). */
export const ProjectGroupMatchRendersAndSelects: Story = {
  args: { projectGroups: localProjectGroups, onSelectProjectGroup: fn() },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const input = canvas.getByPlaceholderText("Add a user…");
    await userEvent.type(input, "review");
    const option = canvas.getByRole("option", { name: /Reviewers/ });
    await expect(option).toHaveTextContent("Project group");
    // No user or org-group matches "review" — the project-group match is
    // the only option.
    await expect(canvas.queryByText("Alex Morgan")).not.toBeInTheDocument();

    await userEvent.click(option);
    await expect(args.onSelectProjectGroup).toHaveBeenCalledWith("pg1");
    await expect(args.onSelect).not.toHaveBeenCalled();
    // Closes/resets the same way a user pick does.
    await expect(input).toHaveValue("");
  },
};

/** Org groups and project groups can appear in the same dropdown at once, each with its own badge, so a caller wiring up
 * both (the "Add member" modal) can tell them apart. */
export const OrgGroupAndProjectGroupMatchesCoexist: Story = {
  args: {
    groups: [{ id: "g3", name: "Review Squad", member_user_ids: [], member_org_group_ids: [], idp_synced_group_name: null, granted_org_role: null }],
    onSelectGroup: fn(),
    projectGroups: localProjectGroups,
    onSelectProjectGroup: fn(),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByPlaceholderText("Add a user…"), "review");
    const orgGroupOption = canvas.getByRole("option", { name: /Review Squad/ });
    const projectGroupOption = canvas.getByRole("option", { name: /Reviewers/ });
    await expect(orgGroupOption).toHaveTextContent("Organisation group");
    await expect(projectGroupOption).toHaveTextContent("Project group");
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

/** Arrow keys move the highlighted option (wrapping at the ends) and Enter
 * selects it — no mouse required. */
export const KeyboardNavigationSelectsHighlightedOption: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const input = canvas.getByPlaceholderText("Add a user…");
    await userEvent.type(input, "a");
    await expect(canvas.getByText("Alex Morgan")).toBeInTheDocument();
    await expect(canvas.getByText("Jamie Lee")).toBeInTheDocument();

    const combobox = canvas.getByRole("combobox");
    await userEvent.keyboard("{ArrowDown}");
    await expect(combobox).toHaveAttribute("aria-activedescendant", canvas.getByRole("option", { name: /Alex Morgan/ }).id);
    await userEvent.keyboard("{ArrowDown}");
    await expect(combobox).toHaveAttribute("aria-activedescendant", canvas.getByRole("option", { name: /Jamie Lee/ }).id);
    await userEvent.keyboard("{Enter}");
    await expect(args.onSelect).toHaveBeenCalledWith("u2");
  },
};

/** Arrow-key navigation reaches group options as well as users. Group options render after user matches (see
 * `UserAutocomplete`'s `options` composition), so the third `ArrowDown` from a fresh query lands on the one group match. */
export const KeyboardNavigationMovesThroughGroupOptionsToo: Story = {
  args: { groups: localGroups, onSelectGroup: fn() },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const input = canvas.getByPlaceholderText("Add a user…");
    // "jamie" matches both "Jamie Lee" (user) and "Jamie's Team" (group).
    await userEvent.type(input, "jamie");
    await expect(canvas.getByText("Jamie Lee")).toBeInTheDocument();
    const groupOption = canvas.getByRole("option", { name: /Jamie's Team/ });

    const combobox = canvas.getByRole("combobox");
    await userEvent.keyboard("{ArrowDown}"); // -> Jamie Lee (the only user match)
    await userEvent.keyboard("{ArrowDown}"); // -> Jamie's Team (the group match)
    await expect(combobox).toHaveAttribute("aria-activedescendant", groupOption.id);
    await userEvent.keyboard("{Enter}");
    await expect(args.onSelectGroup).toHaveBeenCalledWith("g2");
    await expect(args.onSelect).not.toHaveBeenCalled();
  },
};

export const EscapeClosesTheDropdown: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const input = canvas.getByPlaceholderText("Add a user…");
    await userEvent.type(input, "jamie");
    await expect(canvas.getByRole("listbox")).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    await expect(canvas.queryByRole("listbox")).not.toBeInTheDocument();
  },
};

/** The invite-capable hint is visible up front (before typing anything) so
 * the invite path is discoverable without already knowing the trick — and
 * steps aside once a query is in progress, replaced by the dropdown itself. */
export const InviteHintVisibleBeforeTyping: Story = {
  args: {
    organizationId: "org-1",
    onSelectExternal: fn(),
  },
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue({ members: [], external: null });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(/Type their email to invite them/)).toBeInTheDocument();
    await userEvent.type(canvas.getByPlaceholderText("Add a user…"), "someone");
    await expect(canvas.queryByText(/Type their email to invite them/)).not.toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...LocalFilterMode, globals: { theme: "light" } };
export const DarkTheme: Story = { ...LocalFilterMode, globals: { theme: "dark" } };
