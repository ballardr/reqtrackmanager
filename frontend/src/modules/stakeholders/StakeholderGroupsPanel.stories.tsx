import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { withRouter, withToast } from "../../testing/storybook-helpers";
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
  decorators: [withRouter("/org-overview"), withToast()],
  args: { organizationId: "org-1" },
};
export default meta;

type Story = StoryObj<typeof StakeholderGroupsPanel>;

const dialog = () => within(within(document.body).getByRole("dialog"));

export const ShowsTheTreeWithMemberCountsAndFlags: Story = {
  beforeEach: () => mockReads(ORG_BASE, GROUPS),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("button", { name: "Client" })).toBeInTheDocument());
    await expect(canvas.getByRole("button", { name: "Acme" })).toBeInTheDocument();
    await expect(canvas.getByText("One branch")).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Collapse Client" }));
    await expect(canvas.queryByRole("button", { name: "Acme" })).not.toBeInTheDocument();
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
    await expect(within(region).getByText(/via a child group/)).toBeInTheDocument();
    await expect(within(region).getByText("Our biggest customer.")).toBeInTheDocument();
    // Already-members are not offered again.
    await expect(within(region).queryByRole("option", { name: "Alex Acme" })).not.toBeInTheDocument();
    await expect(within(region).getByRole("option", { name: "Bo Both" })).toBeInTheDocument();
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
    await userEvent.click(await within(canvasElement).findByRole("button", { name: "Delete Acme" }));
    await expect(dialog().getByText(/removes 2 memberships and moves its 0 child groups up one level/)).toBeInTheDocument();
    await userEvent.click(dialog().getByRole("button", { name: "Delete group" }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith(`${ORG_BASE}/stakeholder-groups/acme`));
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
    await expect(canvas.getAllByText("Organisation").length).toBeGreaterThan(0);
    await expect(canvas.getByRole("button", { name: "Edit Pilot" })).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Edit Client" })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Add a group under Client" })).not.toBeInTheDocument();
  },
};

export const LoadFailureShowsAMessage: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockRejectedValue(new Error("nope"));
  },
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(within(canvasElement).getByText(/nope|isn't enabled/)).toBeInTheDocument());
  },
};
