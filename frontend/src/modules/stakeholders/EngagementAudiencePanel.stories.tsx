import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { withToast } from "../../testing/storybook-helpers";
import { buildStakeholderGroup } from "./fixtures";
import { EngagementAudiencePanel } from "./EngagementAudiencePanel";
import type { EngagementAudience, EngagementAudienceAdded } from "./types";

const BASE = "/api/v1/projects/project-1/modules/stakeholders/engagements/engagement-1/audiences";

const GROUPS = [
  buildStakeholderGroup({ id: "g-client", name: "Client" }),
  buildStakeholderGroup({ id: "g-acme", name: "Acme", parent_group_id: "g-client" }),
  buildStakeholderGroup({ id: "g-ops", name: "Operations", scope: "project", organization_id: null, project_id: "project-1" }),
];

const AUDIENCE: EngagementAudience = { link_id: "a1", group_id: "g-ops", name: "Operations", scope: "project" };

function mockAudiences(audiences: EngagementAudience[]) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path === BASE) return audiences;
    throw new Error(`Unmocked GET: ${path}`);
  });
}

const meta: Meta<typeof EngagementAudiencePanel> = {
  title: "Modules/Stakeholders/EngagementAudiencePanel",
  component: EngagementAudiencePanel,
  decorators: [withToast()],
  args: { projectId: "project-1", engagementId: "engagement-1", groups: GROUPS, onParticipantsChanged: fn() },
};
export default meta;

type Story = StoryObj<typeof EngagementAudiencePanel>;

export const ListsTheAudienceGroups: Story = {
  beforeEach: () => mockAudiences([AUDIENCE]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Operations")).toBeInTheDocument());
    await expect(canvas.getByRole("button", { name: "Remove audience Operations" })).toBeInTheDocument();
  },
};

export const EmptyState: Story = {
  beforeEach: () => mockAudiences([]),
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(within(canvasElement).getByText("Not aimed at a group.")).toBeInTheDocument());
  },
};

/** Both tiers of group can be chosen (nothing is disabled), and a group already aimed at is not offered again. */
export const AddsEveryoneInTheChosenGroups: Story = {
  beforeEach: () => {
    mockAudiences([AUDIENCE]);
    spyOn(api, "post").mockResolvedValue({
      audience: { link_id: "a2", group_id: "g-acme", name: "Acme", scope: "organization" },
      participants_added: [
        { link_id: "p1", stakeholder_id: "s1", name: "Pat Regulator", scope: "project" },
        { link_id: "p2", stakeholder_id: "s2", name: "Sam Client", scope: "organization" },
      ],
      already_participating: 1,
    } satisfies EngagementAudienceAdded);
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "Groups to add" }));
    await expect(canvas.getByRole("button", { name: "Add everyone in group" })).toBeDisabled();
    await userEvent.click(canvas.getByRole("button", { name: "Groups to add" }));
    const tree = within(within(document.body).getByRole("group", { name: "Groups to add" }));
    await expect(tree.queryByRole("checkbox", { name: "Operations" })).not.toBeInTheDocument();
    await userEvent.click(tree.getByRole("checkbox", { name: "Acme" }));
    await userEvent.keyboard("{Escape}");
    await userEvent.click(canvas.getByRole("button", { name: "Add everyone in group" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(BASE, { group_id: "g-acme" }));
    await waitFor(() => expect(within(document.body).getByText("Added 2 people as participants (1 already taking part).")).toBeInTheDocument());
    await waitFor(() => expect(args.onParticipantsChanged).toHaveBeenCalled());
  },
};

export const RemovingAnAudienceKeepsTheParticipants: Story = {
  beforeEach: () => {
    mockAudiences([AUDIENCE]);
    spyOn(api, "delete").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "Remove audience Operations" }));
    await userEvent.click(canvas.getByRole("button", { name: "Remove audience Operations" }));
    const dialog = within(within(document.body).getByRole("dialog", { name: "Remove audience Operations?" }));
    await expect(dialog.getByText(/The people it added stay as participants/)).toBeInTheDocument();
    await userEvent.click(dialog.getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith(`${BASE}/g-ops`));
  },
};

export const DarkTheme: Story = { ...ListsTheAudienceGroups, globals: { theme: "dark" } };
