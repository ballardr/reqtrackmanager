import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import type { OrgGroup, OrgUser } from "../../api/types";
import { api } from "../../api/client";
import { withToast } from "../../testing/storybook-helpers";
import { StandardMembersSection } from "./StandardMembersSection";
import type { ComplianceStandard, ComplianceStandardMembers } from "./types";

const ORG_ID = "org-1";

const STANDARD: ComplianceStandard = {
  id: "standard-1", organization_id: ORG_ID, reference: "ISO-27001", name: "Corporate Security Standard",
  description: "", issuing_organisation: null, owner_id: "user-1", creator_id: "user-1",
  is_archived: false, archived_at: null, archived_by: null, applicability_default: "opt_in",
  created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
};

const ORG_USERS: OrgUser[] = [
  {
    user_id: "user-1", email: "alex@example.com", display_name: "Alex Manager", is_active: true, is_archived: false,
    roles: [], display_name_locked: false, last_login_at: null, is_2fa_enabled: false, module_roles: [],
  },
  {
    user_id: "user-2", email: "sam@example.com", display_name: "Sam Contributor", is_active: true, is_archived: false,
    roles: [], display_name_locked: false, last_login_at: null, is_2fa_enabled: false, module_roles: [],
  },
  {
    user_id: "user-3", email: "jo@example.com", display_name: "Jo Newcomer", is_active: true, is_archived: false,
    roles: [], display_name_locked: false, last_login_at: null, is_2fa_enabled: false, module_roles: [],
  },
];

const ORG_GROUPS: OrgGroup[] = [
  {
    id: "group-1", name: "Security Reviewers", member_user_ids: ["user-3"], member_org_group_ids: [],
    idp_synced_group_name: null, granted_org_role: null,
  },
];

/** Mocks `GET/POST/DELETE .../standards/{id}/members(/roles|/group-roles)`
 * and the `UserAutocomplete` server-side search endpoint (`GET .../users/
 * search`) — mirrors `MappingTypesPanel.stories.tsx`'s own direct `api.*`
 * mocking shape, since this component (like that panel) owns its
 * fetch/reload state entirely. */
function mockMembersApi(initial: ComplianceStandardMembers) {
  let data = initial;
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.includes("/users/search")) {
      const q = new URL(path, "http://localhost").searchParams.get("q")?.toLowerCase() ?? "";
      const members = ORG_USERS.filter(
        (u) => u.display_name.toLowerCase().includes(q) || u.email.toLowerCase().includes(q)
      );
      return { members, external: null };
    }
    return data;
  });
  spyOn(api, "post").mockImplementation(async (path: string, body?: unknown) => {
    const userRoleMatch = path.match(/\/members\/([^/]+)\/roles$/);
    if (userRoleMatch) {
      const userId = userRoleMatch[1];
      const roleKey = (body as { role_key: "standards_manager" | "standards_contributor" }).role_key;
      const user = ORG_USERS.find((u) => u.user_id === userId);
      const existing = data.members.find((m) => m.user_id === userId);
      const members = existing
        ? data.members.map((m) =>
            m.user_id === userId ? { ...m, role_keys: [...new Set([...m.role_keys, roleKey])] } : m
          )
        : [...data.members, { user_id: userId, display_name: user?.display_name ?? "Unknown", email: user?.email ?? "", role_keys: [roleKey] }];
      data = { ...data, members };
      return;
    }
    if (path.endsWith("/group-roles")) {
      const { org_group_id: groupId, role_key: roleKey } = body as {
        org_group_id: string;
        role_key: "standards_manager" | "standards_contributor";
      };
      const group = ORG_GROUPS.find((g) => g.id === groupId);
      const existing = data.group_members.find((g) => g.org_group_id === groupId);
      const group_members = existing
        ? data.group_members.map((g) =>
            g.org_group_id === groupId ? { ...g, role_keys: [...new Set([...g.role_keys, roleKey])] } : g
          )
        : [
            ...data.group_members,
            {
              org_group_id: groupId, group_name: group?.name ?? "Unknown group",
              role_keys: [roleKey], member_count: group?.member_user_ids.length ?? 0,
            },
          ];
      data = { ...data, group_members };
      return;
    }
    throw new Error(`unmocked POST: ${path}`);
  });
  spyOn(api, "delete").mockImplementation(async (path: string) => {
    const userRoleMatch = path.match(/\/members\/([^/]+)\/roles\/([^/]+)$/);
    if (userRoleMatch) {
      const [, userId, roleKey] = userRoleMatch;
      data = {
        ...data,
        members: data.members
          .map((m) => (m.user_id === userId ? { ...m, role_keys: m.role_keys.filter((r) => r !== roleKey) } : m))
          .filter((m) => m.role_keys.length > 0),
      };
      return;
    }
    const groupRoleMatch = path.match(/\/group-roles\/([^/]+)\/([^/]+)$/);
    if (groupRoleMatch) {
      const [, groupId, roleKey] = groupRoleMatch;
      data = {
        ...data,
        group_members: data.group_members
          .map((g) => (g.org_group_id === groupId ? { ...g, role_keys: g.role_keys.filter((r) => r !== roleKey) } : g))
          .filter((g) => g.role_keys.length > 0),
      };
      return;
    }
    throw new Error(`unmocked DELETE: ${path}`);
  });
}

const meta: Meta<typeof StandardMembersSection> = {
  title: "Modules/Compliance/StandardMembersSection",
  component: StandardMembersSection,
  args: { orgId: ORG_ID, standard: STANDARD, orgUsers: ORG_USERS, orgGroups: ORG_GROUPS },
  decorators: [withToast()],
};
export default meta;

type Story = StoryObj<typeof StandardMembersSection>;

export const ListsExistingMembers: Story = {
  beforeEach: () =>
    mockMembersApi({
      members: [
        { user_id: "user-1", display_name: "Alex Manager", email: "alex@example.com", role_keys: ["standards_manager"] },
        { user_id: "user-2", display_name: "Sam Contributor", email: "sam@example.com", role_keys: ["standards_contributor"] },
      ],
      group_members: [],
      manager_floor_covered_by_fallback: false,
    }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Alex Manager")).toBeInTheDocument());
    await expect(canvas.getByText("Sam Contributor")).toBeInTheDocument();
  },
};

export const ListsGroupGrants: Story = {
  beforeEach: () =>
    mockMembersApi({
      members: [
        { user_id: "user-1", display_name: "Alex Manager", email: "alex@example.com", role_keys: ["standards_manager"] },
      ],
      group_members: [
        { org_group_id: "group-1", group_name: "Security Reviewers", role_keys: ["standards_contributor"], member_count: 3 },
      ],
      manager_floor_covered_by_fallback: false,
    }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Security Reviewers")).toBeInTheDocument());
    await expect(canvas.getByText("Org group")).toBeInTheDocument();
    await expect(canvas.getByText("3 members")).toBeInTheDocument();
  },
};

export const LastManagerCheckboxDisabledWithNoFallback: Story = {
  beforeEach: () =>
    mockMembersApi({
      members: [
        { user_id: "user-1", display_name: "Alex Manager", email: "alex@example.com", role_keys: ["standards_manager"] },
      ],
      group_members: [],
      manager_floor_covered_by_fallback: false,
    }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Alex Manager")).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Roles for Alex Manager" }));
    const group = within(document.body).getByRole("group", { name: "Roles for Alex Manager" });
    const checkbox = within(group).getByRole("checkbox", { name: "Revoke Standards Manager from Alex Manager" });
    await expect(checkbox).toBeDisabled();
    await expect(checkbox).toHaveAttribute("title", expect.stringContaining("must always have at least one"));
  },
};

export const LastManagerCheckboxEnabledWithGroupCoverage: Story = {
  beforeEach: () =>
    mockMembersApi({
      members: [
        { user_id: "user-1", display_name: "Alex Manager", email: "alex@example.com", role_keys: ["standards_manager"] },
      ],
      group_members: [
        { org_group_id: "group-1", group_name: "Security Reviewers", role_keys: ["standards_manager"], member_count: 2 },
      ],
      manager_floor_covered_by_fallback: false,
    }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Alex Manager")).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Roles for Alex Manager" }));
    const group = within(document.body).getByRole("group", { name: "Roles for Alex Manager" });
    const checkbox = within(group).getByRole("checkbox", { name: "Revoke Standards Manager from Alex Manager" });
    await expect(checkbox).not.toBeDisabled();
  },
};

export const LastManagerCheckboxEnabledWithFallbackCoverage: Story = {
  beforeEach: () =>
    mockMembersApi({
      members: [
        { user_id: "user-1", display_name: "Alex Manager", email: "alex@example.com", role_keys: ["standards_manager"] },
      ],
      group_members: [],
      manager_floor_covered_by_fallback: true,
    }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Alex Manager")).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Roles for Alex Manager" }));
    const group = within(document.body).getByRole("group", { name: "Roles for Alex Manager" });
    const checkbox = within(group).getByRole("checkbox", { name: "Revoke Standards Manager from Alex Manager" });
    await expect(checkbox).not.toBeDisabled();
  },
};

export const AddMemberViaSearch: Story = {
  beforeEach: () => mockMembersApi({ members: [], group_members: [], manager_floor_covered_by_fallback: false }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Add member" }));
    const popover = within(document.body).getByRole("dialog", { name: "Add a member" });
    await userEvent.type(within(popover).getByPlaceholderText("Search people or groups…"), "Jo");
    const option = await within(document.body).findByRole("option", { name: /Jo Newcomer/ });
    await userEvent.click(option);

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      `/api/v1/orgs/${ORG_ID}/modules/compliance/standards/${STANDARD.id}/members/user-3/roles`,
      { role_key: "standards_contributor" }
    ));
    await waitFor(() => expect(canvas.getByText("Jo Newcomer")).toBeInTheDocument());
  },
};

export const AddGroupViaSearch: Story = {
  beforeEach: () => mockMembersApi({ members: [], group_members: [], manager_floor_covered_by_fallback: false }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Add member" }));
    const popover = within(document.body).getByRole("dialog", { name: "Add a member" });
    await userEvent.selectOptions(within(popover).getByLabelText("Role"), "standards_manager");
    await userEvent.type(within(popover).getByPlaceholderText("Search people or groups…"), "Security");
    const option = await within(document.body).findByRole("option", { name: /Security Reviewers/ });
    await userEvent.click(option);

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      `/api/v1/orgs/${ORG_ID}/modules/compliance/standards/${STANDARD.id}/group-roles`,
      { org_group_id: "group-1", role_key: "standards_manager" }
    ));
    await waitFor(() => expect(canvas.getByText("Security Reviewers")).toBeInTheDocument());
  },
};

export const NoGroupsAvailable: Story = {
  args: { orgGroups: [] },
  beforeEach: () => mockMembersApi({ members: [], group_members: [], manager_floor_covered_by_fallback: false }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Add member" }));
    const popover = within(document.body).getByRole("dialog", { name: "Add a member" });
    await userEvent.type(within(popover).getByPlaceholderText("Search people or groups…"), "Security");
    await expect(within(document.body).queryByRole("option", { name: /Security Reviewers/ })).not.toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...ListsExistingMembers };
export const DarkTheme: Story = { ...ListsExistingMembers, globals: { theme: "dark" } };
