import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import type { EffectiveMember, OrgGroup, OrgGroupProjectRoleSummary, OrgUser } from "../api/types";
import { buildUser, withStatefulAuth, withToast } from "../testing/storybook-helpers";
import { ManageProjectUsersModal } from "./ManageProjectUsersModal";

const PROJECT = { id: "proj-1", name: "Beta", organization_id: "org-1" };

const orgUser: OrgUser = {
  user_id: "user-1", email: "alex@example.com", display_name: "Alex Morgan", is_active: true,
  is_archived: false, roles: ["org_admin"], display_name_locked: false, last_login_at: "2026-02-01T09:00:00Z",
  is_2fa_enabled: true, module_roles: [], custom_roles: [],
};

const groups: OrgGroup[] = [
  { id: "grp1", name: "Engineering", member_user_ids: ["user-1"], member_org_group_ids: [], idp_synced_group_name: null, granted_org_role: null },
];

const alex: EffectiveMember = {
  user_id: "u-alex", display_name: "Alex Morgan", email: "alex@example.com", effective_role: "stakeholder",
  sources: [{ kind: "direct_role", role: "stakeholder", via_project_id: null, via_project_name: null, via_mode: null, via_group_id: null, via_group_name: null }],
  module_roles: [],
};

function mockApis(overrides: { members?: EffectiveMember[]; groupRoles?: OrgGroupProjectRoleSummary[] } = {}) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path === "/api/v1/projects/proj-1/effective-members") return overrides.members ?? [];
    if (path === "/api/v1/projects/proj-1/group-roles") return overrides.groupRoles ?? [];
    if (path === "/api/v1/projects/proj-1/pending-invites") return [];
    if (path === "/api/v1/projects/proj-1/module-roles") return [];
    if (path === "/api/v1/orgs/org-1/groups") return groups;
    // `UserAutocomplete`'s debounced server-side search.
    if (path.includes("/users/search")) return { members: [], external: null };
    throw new Error(`unmocked path: ${path}`);
  });
  spyOn(api, "getPage").mockResolvedValue({ items: [orgUser], total: 1 });
  spyOn(api, "post").mockResolvedValue(undefined);
  spyOn(api, "delete").mockResolvedValue(undefined);
}

const meta: Meta<typeof ManageProjectUsersModal> = {
  title: "Components/ManageProjectUsersModal",
  component: ManageProjectUsersModal,
  args: { project: PROJECT, onClose: () => undefined },
  decorators: [withStatefulAuth(buildUser({ is_server_admin: false })), withToast()],
};
export default meta;

type Story = StoryObj<typeof ManageProjectUsersModal>;

/** The same `ProjectMembersTable` the project's own Members section renders: effective members with provenance. */
export const ShowsEffectiveMembers: Story = {
  beforeEach: () => mockApis({ members: [alex] }),
  play: async () => {
    const modal = await within(document.body).findByRole("dialog", { name: "Manage users — Beta" });
    await waitFor(() => expect(within(modal).getByRole("cell", { name: "Alex Morgan" })).toBeInTheDocument());
    await expect(within(modal).getByRole("button", { name: "Alex Morgan's roles" })).toBeInTheDocument();
    await expect(modal.querySelector(".filter-panel-top")).toBeInTheDocument();
  },
};

/** Toggling a direct role calls the same endpoint the project's own Members section uses. */
export const ToggleDirectRole: Story = {
  beforeEach: () => mockApis({ members: [alex] }),
  play: async () => {
    const body = within(document.body);
    const modal = await body.findByRole("dialog", { name: "Manage users — Beta" });
    await userEvent.click(await within(modal).findByRole("button", { name: "Alex Morgan's roles" }));
    const group = body.getByRole("group", { name: "Alex Morgan's roles" });
    await userEvent.click(within(group).getByRole("checkbox", { name: "Grant Member to Alex Morgan" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith("/api/v1/projects/proj-1/roles", { user_id: "u-alex", role: "member" }),
    );
  },
};

/** "Add member" opens the staged add control in a nested dialog; nothing is staged, so committing is unavailable. */
export const AddControlOpensNestedDialog: Story = {
  beforeEach: () => mockApis(),
  play: async () => {
    const body = within(document.body);
    const modal = await body.findByRole("dialog", { name: "Manage users — Beta" });
    await userEvent.click(await within(modal).findByRole("button", { name: "Add member" }));
    const add = body.getByRole("dialog", { name: "Add member" });
    await expect(within(add).getByPlaceholderText("Type a name to add, or an email to invite…")).toBeInTheDocument();
    await expect(within(add).getByRole("button", { name: "Add member(s)" })).toBeDisabled();
    await userEvent.click(within(add).getByRole("button", { name: "Close" }));
    await expect(body.queryByRole("dialog", { name: "Add member" })).not.toBeInTheDocument();
    await expect(body.getByRole("dialog", { name: "Manage users — Beta" })).toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();
  },
};

/** Picking an organisation group stages it; the grant is only sent when the staged members are added. */
export const AddOrganisationGroup: Story = {
  beforeEach: () => mockApis(),
  play: async () => {
    const body = within(document.body);
    const modal = await body.findByRole("dialog", { name: "Manage users — Beta" });
    await userEvent.click(await within(modal).findByRole("button", { name: "Add member" }));
    const add = body.getByRole("dialog", { name: "Add member" });
    await userEvent.type(within(add).getByPlaceholderText("Type a name to add, or an email to invite…"), "Eng");
    const option = await within(add).findByRole("option", { name: /Engineering/ });
    await userEvent.click(option);
    expect(api.post).not.toHaveBeenCalled();
    await userEvent.click(within(add).getByRole("button", { name: "Add 1 member" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith("/api/v1/projects/proj-1/group-roles", { org_group_id: "grp1", role: "member" }),
    );
    await expect(body.queryByRole("dialog", { name: "Add member" })).not.toBeInTheDocument();
  },
};

/** A group holding a role renders as its own row, with role toggles and a confirmed removal. */
export const GroupRowRoleToggleAndRemove: Story = {
  beforeEach: () => mockApis({ groupRoles: [{ org_group_id: "grp1", org_group_name: "Engineering", roles: ["stakeholder"] }] }),
  play: async () => {
    const body = within(document.body);
    const modal = await body.findByRole("dialog", { name: "Manage users — Beta" });
    const row = (await within(modal).findByRole("button", { name: "Engineering's roles" })).closest("tr")!;
    await expect(within(row).getByText("Group")).toBeInTheDocument();

    await userEvent.click(within(row).getByRole("button", { name: "Engineering's roles" }));
    const roleGroup = body.getByRole("group", { name: "Engineering's roles" });
    await userEvent.click(within(roleGroup).getByRole("checkbox", { name: "Grant Member to Engineering" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith("/api/v1/projects/proj-1/group-roles", { org_group_id: "grp1", role: "member" }),
    );

    await userEvent.click(within(row).getByRole("button", { name: "Engineering's actions" }));
    await userEvent.click(within(body.getByRole("menu", { name: "Engineering's actions" })).getByRole("menuitem", { name: "Remove group" }));
    const dialog = body.getByRole("dialog", { name: "Remove Engineering from this project?" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Remove group" }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith("/api/v1/projects/proj-1/group-roles/grp1/stakeholder"));
  },
};
