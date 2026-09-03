import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import type { OrgGroup, OrgUser, ProjectGroup } from "../api/types";
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

// PR5 of the members/groups directory rework plan — org groups the
// optional `groups`/`onSelectGroup` pair matches against, always
// client-side (see the component's own module docstring). "Jamie's Team"
// deliberately overlaps the "jamie" needle with `localUsers[1]` ("Jamie
// Lee") for `KeyboardNavigationMovesThroughGroupOptionsToo` below, so one
// query exercises both a user and a group option in the same dropdown.
const localGroups: OrgGroup[] = [
  { id: "g1", name: "Engineering", member_user_ids: [], member_org_group_ids: [], idp_synced_group_name: null, granted_org_role: null },
  { id: "g2", name: "Jamie's Team", member_user_ids: [], member_org_group_ids: [], idp_synced_group_name: null, granted_org_role: null },
];

// PR7 of the members/groups directory rework plan — this project's own
// groups, the optional `projectGroups`/`onSelectProjectGroup` pair matches
// against, same client-side substring match as `groups`/`onSelectGroup`
// above. A genuinely different concept from an org group (local to one
// project, not org-wide), so it gets a visually distinguishable match —
// `FolderKanban` instead of `Users`, and a "Project group" badge instead of
// "Org group" — see the component's own module docstring.
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
    await userEvent.click(canvas.getByText("Jamie Lee"));
    await expect(args.onSelect).toHaveBeenCalledWith("u2");
  },
};

/** PR5 of the members/groups directory rework plan: passing `groups` also
 * matches org groups by name, client-side, alongside the user matches —
 * rendered with a `Users` icon and an "Org group" badge so it's visually
 * distinct, and selecting one calls `onSelectGroup` (not `onSelect`). */
export const GroupMatchRendersAndSelects: Story = {
  args: { groups: localGroups, onSelectGroup: fn() },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const input = canvas.getByPlaceholderText("Add a user…");
    await userEvent.type(input, "engineer");
    const option = canvas.getByRole("option", { name: /Engineering/ });
    await expect(option).toHaveTextContent("Org group");
    // No user matches "engineer" — the group match is the only option.
    await expect(canvas.queryByText("Alex Morgan")).not.toBeInTheDocument();

    await userEvent.click(option);
    await expect(args.onSelectGroup).toHaveBeenCalledWith("g1");
    await expect(args.onSelect).not.toHaveBeenCalled();
    // Closes/resets the same way a user pick does.
    await expect(input).toHaveValue("");
  },
};

/** PR7: passing `projectGroups` also matches this project's own groups by
 * name, client-side, alongside user and org-group matches — rendered with a
 * `FolderKanban` icon and a "Project group" badge, visually distinct from
 * both a user row and an "Org group" match, and selecting one calls
 * `onSelectProjectGroup` (not `onSelect`/`onSelectGroup`). */
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

/** All three group-like match kinds — org group and project group — can
 * appear in the same dropdown at once, each with its own distinct badge, so
 * a caller wiring up both (PR7's "Add member" modal) never has to guess
 * which is which. */
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
    await expect(orgGroupOption).toHaveTextContent("Org group");
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

/** PR5: arrow-key navigation must reach group options too, not just users —
 * the regression this repo's "don't regress existing keyboard nav" note
 * calls out explicitly. Group options render after user matches in the
 * dropdown (see `UserAutocomplete`'s own `options` composition), so the
 * third `ArrowDown` from a fresh query lands on the one group match here. */
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
