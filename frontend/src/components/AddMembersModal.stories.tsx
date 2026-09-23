import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import type { OrgGroup, OrgUser, OrgUserSearchResult, ProjectGroup } from "../api/types";
import { AddMembersModal } from "./AddMembersModal";

const users: OrgUser[] = [
  {
    user_id: "u1", email: "alex.morgan@example.com", display_name: "Alex Morgan", is_active: true,
    is_archived: false, roles: ["member"], display_name_locked: false, last_login_at: null, is_2fa_enabled: false, module_roles: [], custom_roles: [],
  },
  {
    user_id: "u2", email: "jamie.lee@example.com", display_name: "Jamie Lee", is_active: true,
    is_archived: false, roles: ["project_creator"], display_name_locked: false, last_login_at: null, is_2fa_enabled: false, module_roles: [], custom_roles: [],
  },
];

const groups: OrgGroup[] = [
  { id: "g1", name: "Engineering", member_user_ids: [], member_org_group_ids: [], idp_synced_group_name: null, granted_org_role: null },
];

const projectGroups: ProjectGroup[] = [
  { id: "pg1", name: "Reviewers", roles: ["stakeholder"], member_user_ids: [], member_org_group_ids: [], member_source_project_ids: [] },
];

/** `organizationId` (matching production usage, which always passes it —
 * `OrgAdminPage.tsx`/`ProjectAdminPage.tsx` both do) puts `UserAutocomplete`
 * into its debounced server-side search mode, so every story that types a
 * user name needs this mocked rather than relying on client-side filtering
 * over `users`. Mirrors the substring match the real backend endpoint
 * (`orgs/{id}/users/search`) performs. */
function mockUserSearch() {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    const needle = new URL(path, "http://localhost").searchParams.get("q")?.toLowerCase() ?? "";
    const members = users.filter(
      (u) => u.display_name.toLowerCase().includes(needle) || u.email.toLowerCase().includes(needle)
    );
    return { members, external: null } satisfies OrgUserSearchResult;
  });
}

const meta: Meta<typeof AddMembersModal> = {
  title: "Components/AddMembersModal",
  component: AddMembersModal,
  args: {
    title: "Add member",
    onClose: fn(),
    users,
    groups,
    organizationId: "org-1",
    projectId: "proj-1",
    onAddEntry: fn(async () => {}),
  },
  beforeEach: mockUserSearch,
};
export default meta;

type Story = StoryObj<typeof AddMembersModal>;

/** Picking two people stages both, with no network call yet — the commit
 * button stays disabled until at least one row is staged, and shows the
 * staged count once it isn't. */
export const StageTwoThenCommit: Story = {
  play: async ({ args }) => {
    const body = within(document.body);
    const input = body.getByPlaceholderText("Type a name to add, or an email to invite…");

    await expect(body.getByRole("button", { name: "Add member(s)" })).toBeDisabled();

    await userEvent.type(input, "Alex");
    await userEvent.click(await body.findByRole("option", { name: /Alex Morgan/ }));
    await expect(body.getByText("Alex Morgan (alex.morgan@example.com)")).toBeInTheDocument();
    expect(args.onAddEntry).not.toHaveBeenCalled();

    await userEvent.type(input, "Jamie");
    await userEvent.click(await body.findByRole("option", { name: /Jamie Lee/ }));

    const commitButton = body.getByRole("button", { name: "Add 2 members" });
    await userEvent.click(commitButton);

    await waitFor(() => expect(args.onAddEntry).toHaveBeenCalledTimes(2));
    expect(args.onAddEntry).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "user", id: "u1", role: "member" })
    );
    expect(args.onAddEntry).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "user", id: "u2", role: "member" })
    );
    // Every staged entry succeeded — the modal closes itself.
    await waitFor(() => expect(args.onClose).toHaveBeenCalled());
  },
};

/** Each staged row's role is independently editable before committing —
 * changing one row's role doesn't affect another's. */
export const PerRowRoleIsEditable: Story = {
  play: async () => {
    const body = within(document.body);
    const input = body.getByPlaceholderText("Type a name to add, or an email to invite…");
    await userEvent.type(input, "Alex");
    await userEvent.click(await body.findByRole("option", { name: /Alex Morgan/ }));

    const roleSelect = body.getByRole("combobox", { name: "Role for Alex Morgan (alex.morgan@example.com)" });
    await expect(roleSelect).toHaveValue("member");
    await userEvent.selectOptions(roleSelect, "project_manager");
    await expect(roleSelect).toHaveValue("project_manager");
  },
};

/** A staged row can be removed again before committing — nothing is ever
 * sent for a row that was picked and then reconsidered. */
export const RemoveStagedRow: Story = {
  play: async ({ args }) => {
    const body = within(document.body);
    const input = body.getByPlaceholderText("Type a name to add, or an email to invite…");
    await userEvent.type(input, "Alex");
    await userEvent.click(await body.findByRole("option", { name: /Alex Morgan/ }));

    await userEvent.click(body.getByRole("button", { name: "Remove Alex Morgan (alex.morgan@example.com)" }));
    await expect(body.queryByText("Alex Morgan (alex.morgan@example.com)")).not.toBeInTheDocument();
    await expect(body.getByRole("button", { name: "Add member(s)" })).toBeDisabled();
    expect(args.onAddEntry).not.toHaveBeenCalled();
  },
};

/** Style guide "Pattern: bulk operations on a list"'s tail, applied here:
 * one failing staged entry among several stays visible with its own inline
 * error and the modal stays open, while the entries that succeeded are
 * removed — a partial failure is never silently swallowed into "it must
 * have worked." */
export const PartialFailureStaysOpenWithError: Story = {
  args: {
    onAddEntry: fn(async (entry: { id: string }) => {
      if (entry.id === "u2") throw new Error("Jamie Lee already holds a role on this project.");
    }),
  },
  play: async ({ args }) => {
    const body = within(document.body);
    const input = body.getByPlaceholderText("Type a name to add, or an email to invite…");
    await userEvent.type(input, "Alex");
    await userEvent.click(await body.findByRole("option", { name: /Alex Morgan/ }));
    await userEvent.type(input, "Jamie");
    await userEvent.click(await body.findByRole("option", { name: /Jamie Lee/ }));

    await userEvent.click(body.getByRole("button", { name: "Add 2 members" }));

    await waitFor(() =>
      expect(body.getByText("Jamie Lee already holds a role on this project.")).toBeInTheDocument()
    );
    // The successful entry is gone; the failed one is still staged and the
    // modal stayed open rather than closing on a partial success.
    await expect(body.queryByText("Alex Morgan (alex.morgan@example.com)")).not.toBeInTheDocument();
    await expect(body.getByText("Jamie Lee (jamie.lee@example.com)")).toBeInTheDocument();
    expect(args.onClose).not.toHaveBeenCalled();
  },
};

/** `showRole={false}` — the "add into an existing ProjectGroup" variant
 * (`ProjectAdminPage.tsx`'s hand-off, see module docstring): no per-row
 * role `<select>` at all, since group membership here grants no role by
 * itself. */
export const RolelessVariantForGroupMembership: Story = {
  args: {
    title: 'Add to "Stakeholders"',
    showRole: false,
    hint: 'Adding someone here makes them a member of "Stakeholders" — it does not grant a role by itself.',
    organizationId: undefined,
    projectId: undefined,
    onBack: fn(),
  },
  play: async ({ args }) => {
    const body = within(document.body);
    await expect(body.getByText(/does not grant a role by itself/)).toBeInTheDocument();
    const input = body.getByPlaceholderText("Type a name to add, or an email to invite…");
    await userEvent.type(input, "Alex");
    await userEvent.click(await body.findByRole("option", { name: /Alex Morgan/ }));

    // No per-row role combobox in this configuration (the search input
    // itself is also `role="combobox"`, per `UserAutocomplete`'s own ARIA
    // combobox pattern — this checks specifically for a role picker).
    await expect(body.queryByRole("combobox", { name: /^Role for/ })).not.toBeInTheDocument();

    await userEvent.click(body.getByRole("button", { name: "Back" }));
    await expect(args.onBack).toHaveBeenCalled();
  },
};

/** Passing `projectGroups` also matches this project's own groups — but
 * picking one is a hand-off, not a staged entry: `onSelectProjectGroup`
 * fires directly and nothing is added to the staged list (see module
 * docstring for why a project-group match names a destination, not a
 * person to add). */
export const ProjectGroupMatchHandsOff: Story = {
  args: { projectGroups, onSelectProjectGroup: fn() },
  play: async ({ args }) => {
    const body = within(document.body);
    const input = body.getByPlaceholderText("Type a name to add, or an email to invite…");
    await userEvent.type(input, "Review");
    const option = await body.findByRole("option", { name: /Reviewers/ });
    await expect(option).toHaveTextContent("Project group");

    await userEvent.click(option);
    await waitFor(() => expect(args.onSelectProjectGroup).toHaveBeenCalledWith("pg1"));
    expect(args.onAddEntry).not.toHaveBeenCalled();
    // Nothing staged — this was a hand-off, not an add.
    await expect(body.getByRole("button", { name: "Add member(s)" })).toBeDisabled();
  },
};

export const LightTheme: Story = { ...StageTwoThenCommit, globals: { theme: "light" } };
export const DarkTheme: Story = { ...StageTwoThenCommit, globals: { theme: "dark" } };
