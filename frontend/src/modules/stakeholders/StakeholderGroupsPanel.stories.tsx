import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { expectHeaderSorts } from "../../testing/sortHelpers";
import { buildUser, withRouter, withStatefulAuth, withToast } from "../../testing/storybook-helpers";
import { buildStakeholderGroup } from "./fixtures";
import { StakeholderGroupsPanel } from "./StakeholderGroupsPanel";
import type { GroupTextProposal, StakeholderGroup, StakeholderGroupMember } from "./types";

const ORG_BASE = "/api/v1/orgs/org-1/modules/stakeholders";
const PROJECT_BASE = "/api/v1/projects/project-1/modules/stakeholders";

const GROUPS: StakeholderGroup[] = [
  buildStakeholderGroup({ id: "client", name: "Client", exclusive_children: true, child_count: 1 }),
  buildStakeholderGroup({ id: "acme", name: "Acme", parent_group_id: "client", member_count: 2, description: "Our biggest customer." }),
  buildStakeholderGroup({ id: "ops", name: "Operations", sort_order: 1 }),
];

const MEMBERS: StakeholderGroupMember[] = [
  { stakeholder_id: "s1", name: "Alex Acme", scope: "organization", direct: true },
  { stakeholder_id: "s2", name: "Fran Finance", scope: "organization", direct: false },
];

const PROPOSALS: GroupTextProposal[] = [{ name: "Acme", stakeholder_count: 2, existing_group_id: null }];

/** Mocks the reads; `groups` is what the list returns. */
function mockReads(base: string, groups: StakeholderGroup[]) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path === `${base}/stakeholder-groups`) return groups;
    if (path === `${base}/stakeholder-groups/text-proposals`) return PROPOSALS;
    if (path.startsWith(`${base}/stakeholder-groups/`) && path.includes("/members")) return MEMBERS;
    if (path === `${base}/stakeholders`) return [{ id: "s3", name: "Bo Both" }, { id: "s1", name: "Alex Acme" }];
    throw new Error(`Unmocked GET: ${path}`);
  });
}

const meta: Meta<typeof StakeholderGroupsPanel> = {
  title: "Modules/Stakeholders/StakeholderGroupsPanel",
  component: StakeholderGroupsPanel,
  decorators: [withStatefulAuth(buildUser({ ui_preferences: {} })), withRouter("/org-overview"), withToast()],
  args: { organizationId: "org-1" },
};
export default meta;

type Story = StoryObj<typeof StakeholderGroupsPanel>;

const dialog = () => within(within(document.body).getByRole("dialog"));

/** Opens a group row's actions menu and returns the menu to pick from. */
const openMenu = async (canvas: ReturnType<typeof within>, name: string) =>
  userEvent.click(await canvas.findByRole("button", { name: `Actions for ${name}` }));
const pick = (name: string) => userEvent.click(within(document.body).getByRole("menuitem", { name }));

export const ShowsTheTreeWithMemberCountsAndFlags: Story = {
  beforeEach: () => mockReads(ORG_BASE, GROUPS),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("button", { name: "Collapse Client" })).toBeInTheDocument());
    await expect(canvas.getByRole("button", { name: "Acme" })).toBeInTheDocument();
    await expect(canvas.getByText("One branch")).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Show members of Acme" })).toHaveTextContent("2");
    await userEvent.click(canvas.getByRole("button", { name: "Collapse Client" }));
    await expect(canvas.queryByRole("button", { name: "Acme" })).not.toBeInTheDocument();
    // The collapsed folder is remembered, and opens again.
    await userEvent.click(canvas.getByRole("button", { name: "Expand Client" }));
    await expect(canvas.getByRole("button", { name: "Acme" })).toBeInTheDocument();
  },
};

/** A group is not a folder: a parent group and a group without children both show the group icon, and no folder icon is drawn. */
export const GroupRowsShowTheGroupIconNotAFolder: Story = {
  beforeEach: () => mockReads(ORG_BASE, GROUPS),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const parent = await canvas.findByRole("button", { name: "Collapse Client" });
    await expect(parent.querySelector(".folder-tree-folder-icon svg")).toHaveClass("lucide-users");
    await expect(canvas.getAllByRole("img", { name: "Stakeholder group" }).length).toBeGreaterThan(0);
    await expect(canvasElement.querySelector(".lucide-folder, .lucide-folder-open")).toBeNull();
  },
};

/** A deeper tree: every column starts at the same x on every row, and each name is indented by its depth. */
export const NestedGroupsAlignInColumns: Story = {
  beforeEach: () =>
    mockReads(ORG_BASE, [
      ...GROUPS,
      buildStakeholderGroup({ id: "fin", name: "Acme Finance", parent_group_id: "acme", member_count: 1 }),
    ]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const grid = await canvas.findByRole("treegrid", { name: "Stakeholder groups" });
    await waitFor(() => expect(within(grid).getByRole("button", { name: "Acme Finance" })).toBeInTheDocument());
    const left = (el: HTMLElement) => el.getBoundingClientRect().left;
    const headerLeft = left(within(grid).getByRole("columnheader", { name: "Members" }));
    for (const button of within(grid).getAllByRole("button", { name: /^Show members of / })) {
      await expect(Math.abs(left(button) - headerLeft)).toBeLessThan(1);
    }
    const codeLeft = left(within(grid).getByRole("columnheader", { name: "Code" }));
    for (const code of grid.querySelectorAll<HTMLElement>('[role="gridcell"]:nth-child(2)')) {
      await expect(Math.abs(left(code) - codeLeft)).toBeLessThan(1);
    }
    // Deeper groups are indented further than their parents.
    await expect(left(within(grid).getByRole("button", { name: "Acme Finance" }))).toBeGreaterThan(left(within(grid).getByRole("button", { name: "Collapse Acme" })));
  },
};

/** A group with child groups is selected from its Members count; the selected row is outlined. */
export const AParentGroupIsSelectedFromItsMembersCount: Story = {
  beforeEach: () => mockReads(ORG_BASE, GROUPS),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Show members of Client" }));
    await expect(await canvas.findByRole("region", { name: "Members of Client" })).toBeInTheDocument();
    const row = canvas.getByRole("button", { name: "Collapse Client" }).closest('[role="row"]') as HTMLElement;
    await expect(row).toHaveAttribute("aria-selected", "true");
    await expect(row).toHaveClass("folder-tree-selected");
  },
};

/** At a narrow width the Scope and Rule columns drop and the page does not scroll sideways. */
export const NarrowWidthKeepsTheNameAndActions: Story = {
  decorators: [(Story) => <div style={{ width: "320px" }}><Story /></div>],
  beforeEach: () => mockReads(ORG_BASE, GROUPS),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("button", { name: "Collapse Client" });
    await expect(canvas.getByRole("button", { name: "Actions for Client" })).toBeInTheDocument();
    await expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(document.documentElement.clientWidth);
  },
};

export const EmptyStateExplainsGroups: Story = {
  beforeEach: () => mockReads(ORG_BASE, []),
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(within(canvasElement).getByText(/No Stakeholder groups yet/)).toBeInTheDocument());
  },
};

export const SelectingAGroupListsItsMembers: Story = {
  beforeEach: () => mockReads(ORG_BASE, GROUPS),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Acme" }));
    const region = await canvas.findByRole("region", { name: "Members of Acme" });
    await waitFor(() => expect(within(region).getByText("Alex Acme")).toBeInTheDocument());
    await expect(within(region).getByText("Via a child group")).toBeInTheDocument();
    await expect(within(region).getByText("Direct")).toBeInTheDocument();
    await expect(within(region).getByRole("button", { name: "Remove Alex Acme from Acme" })).toBeInTheDocument();
    // A member that is only in a child group cannot be removed here.
    await expect(within(region).queryByRole("button", { name: "Remove Fran Finance from Acme" })).not.toBeInTheDocument();
    await expect(within(region).getByText("Our biggest customer.")).toBeInTheDocument();
    // Already-members are not offered again.
    await expect(within(region).queryByRole("option", { name: "Alex Acme" })).not.toBeInTheDocument();
    await expect(within(region).getByRole("option", { name: "Bo Both" })).toBeInTheDocument();
  },
};

/** The members are listed by name, and the Name header reverses them. */
export const MembersSortByName: Story = {
  beforeEach: () => mockReads(ORG_BASE, GROUPS),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Acme" }));
    const region = await canvas.findByRole("region", { name: "Members of Acme" });
    const order = () => within(region).getAllByRole("row").slice(1).map((r) => r.textContent ?? "");
    await waitFor(() => expect(order()[0]).toContain("Alex Acme"));
    await userEvent.click(within(region).getByRole("button", { name: /Name/ }));
    await userEvent.click(within(region).getByRole("button", { name: /Name/ }));
    await waitFor(() => expect(order()[0]).toContain("Fran Finance"));
  },
};

/** The Membership header orders direct members before members that arrive through a child group, and back. */
export const MembersSortByMembership: Story = {
  beforeEach: () => mockReads(ORG_BASE, GROUPS),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Acme" }));
    const region = await canvas.findByRole("region", { name: "Members of Acme" });
    const table = await within(region).findByRole("table");
    await expectHeaderSorts(table, "Membership", ["Direct", "Via a child group"]);
  },
};

export const AddingAMemberPostsAndToasts: Story = {
  beforeEach: () => {
    mockReads(ORG_BASE, GROUPS);
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Acme" }));
    const region = await canvas.findByRole("region", { name: "Members of Acme" });
    await userEvent.selectOptions(await within(region).findByLabelText("Stakeholder to add"), "s3");
    await userEvent.click(within(region).getByRole("button", { name: "Add" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(`${ORG_BASE}/stakeholder-groups/acme/members`, { stakeholder_id: "s3" }));
    await expect(await within(document.body).findByText("Added to the group.")).toBeInTheDocument();
  },
};

export const CreatingAGroupPostsTheForm: Story = {
  beforeEach: () => {
    mockReads(ORG_BASE, GROUPS);
    spyOn(api, "post").mockResolvedValue(buildStakeholderGroup({ id: "new", name: "Beta Ltd" }));
  },
  play: async ({ canvasElement }) => {
    await userEvent.click(await within(canvasElement).findByRole("button", { name: "New group" }));
    await userEvent.type(dialog().getByLabelText("Group name"), "Beta Ltd");
    await userEvent.click(dialog().getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(`${ORG_BASE}/stakeholder-groups`, {
        name: "Beta Ltd", description: "", parent_group_id: null, exclusive_children: false,
      }),
    );
  },
};

export const DeleteConfirmStatesWhatIsRemoved: Story = {
  beforeEach: () => {
    mockReads(ORG_BASE, GROUPS);
    spyOn(api, "delete").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    await openMenu(within(canvasElement), "Acme");
    await pick("Delete");
    await expect(dialog().getByText(/removes 2 memberships and moves its 0 child groups up one level/)).toBeInTheDocument();
    await userEvent.click(dialog().getByRole("button", { name: "Delete group" }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith(`${ORG_BASE}/stakeholder-groups/acme`));
  },
};

/** A row's menu holds Edit, Add group under, Move up, Move down and Delete; the ends of a level cannot move further. */
export const RowMenuHoldsTheGroupActions: Story = {
  beforeEach: () => {
    mockReads(ORG_BASE, GROUPS);
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await openMenu(canvas, "Client");
    const menu = within(document.body);
    for (const name of ["Edit", "Add group under Client", "Move up", "Move down", "Delete"]) {
      await expect(menu.getByRole("menuitem", { name })).toBeInTheDocument();
    }
    // Client is first of two roots, so it cannot move up.
    await expect(menu.getByRole("menuitem", { name: "Move up" })).toBeDisabled();
    await pick("Move down");
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(`${ORG_BASE}/stakeholder-groups/client/move`, { direction: "down" }));
  },
};

export const CreateFromTextOffersTheDistinctValues: Story = {
  beforeEach: () => {
    mockReads(ORG_BASE, GROUPS);
    spyOn(api, "post").mockResolvedValue({ root_group_id: "r", group_ids: ["g"], memberships_added: 2 });
  },
  play: async ({ canvasElement }) => {
    await userEvent.click(await within(canvasElement).findByRole("button", { name: "Create from Organisation / group text" }));
    await expect(await within(document.body).findByText("2 stakeholders")).toBeInTheDocument();
    await userEvent.click(dialog().getByRole("button", { name: "Create groups" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(`${ORG_BASE}/stakeholder-groups/from-text`, { names: ["Acme"] }));
  },
};

export const ProjectViewKeepsOrganisationGroupsReadOnly: Story = {
  args: { organizationId: undefined, projectId: "project-1" },
  beforeEach: () =>
    mockReads(PROJECT_BASE, [
      ...GROUPS,
      buildStakeholderGroup({ id: "p1", scope: "project", organization_id: null, project_id: "project-1", name: "Pilot", parent_group_id: "ops" }),
    ]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("button", { name: "Pilot" })).toBeInTheDocument());
    await expect(canvas.getByRole("columnheader", { name: "Scope" })).toBeInTheDocument();
    await expect(canvas.getAllByText("Organisation").length).toBeGreaterThan(0);
    await expect(canvas.getByRole("button", { name: "Actions for Pilot" })).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Actions for Client" })).not.toBeInTheDocument();
    await openMenu(canvas, "Pilot");
    await expect(within(document.body).getByRole("menuitem", { name: "Edit" })).toBeInTheDocument();
  },
};

export const LoadFailureShowsAMessage: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockRejectedValue(new Error("nope"));
  },
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(within(canvasElement).getByText(/nope|is not enabled/)).toBeInTheDocument());
  },
};
