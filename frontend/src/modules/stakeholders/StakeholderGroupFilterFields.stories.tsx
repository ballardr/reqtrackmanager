import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { buildStakeholderGroup } from "./fixtures";
import { StakeholderGroupFilterFields } from "./StakeholderGroupFilterFields";

const GROUPS = [
  buildStakeholderGroup({ id: "g-client", name: "Client" }),
  buildStakeholderGroup({ id: "g-acme", name: "Acme", parent_group_id: "g-client" }),
  buildStakeholderGroup({ id: "g-partner", name: "Partner" }),
];

const meta: Meta<typeof StakeholderGroupFilterFields> = {
  title: "Modules/Stakeholders/StakeholderGroupFilterFields",
  component: StakeholderGroupFilterFields,
  args: { groups: GROUPS, groupId: "", groupBy: "", onGroupIdChange: fn(), onGroupByChange: fn() },
  render: (args) => (
    <div className="row" style={{ gap: "var(--space-5)" }}>
      <StakeholderGroupFilterFields {...args} />
    </div>
  ),
};
export default meta;

type Story = StoryObj<typeof StakeholderGroupFilterFields>;

/** The filter lists every group indented by depth; "Group by" lists top-level groups only. */
export const ListsGroupsByDepth: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const group = canvas.getByLabelText("Group");
    await expect(within(group).getAllByRole("option").map((o) => o.textContent?.trim())).toEqual(["All groups", "Client", "Acme", "Partner"]);
    const groupBy = canvas.getByLabelText("Group by");
    await expect(within(groupBy).getAllByRole("option").map((o) => o.textContent)).toEqual(["No grouping", "Client", "Partner"]);
    await userEvent.selectOptions(group, "g-acme");
    await expect(args.onGroupIdChange).toHaveBeenCalledWith("g-acme");
    await userEvent.selectOptions(groupBy, "g-partner");
    await expect(args.onGroupByChange).toHaveBeenCalledWith("g-partner");
  },
};

/** Nothing renders when there are no groups, so a project without any shows no dead controls. */
export const NoGroups: Story = {
  args: { groups: [] },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).queryByLabelText("Group")).not.toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...ListsGroupsByDepth, globals: { theme: "light" } };
export const DarkTheme: Story = { ...ListsGroupsByDepth, globals: { theme: "dark" } };
