import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { withToast } from "../../testing/storybook-helpers";
import { buildStakeholderGroup } from "./fixtures";
import { StakeholderGroupsField } from "./StakeholderGroupsField";

const GROUPS = [
  buildStakeholderGroup({ id: "client", name: "Client" }),
  buildStakeholderGroup({ id: "acme", name: "Acme", parent_group_id: "client" }),
  buildStakeholderGroup({ id: "ops", name: "Operations" }),
  buildStakeholderGroup({ id: "p-pilot", scope: "project", organization_id: null, project_id: "project-1", name: "Pilot", parent_group_id: "ops" }),
];

const meta: Meta<typeof StakeholderGroupsField> = {
  title: "Modules/Stakeholders/StakeholderGroupsField",
  component: StakeholderGroupsField,
  decorators: [withToast()],
  args: { current: [], groups: GROUPS, tier: "organization", onSave: fn(async () => []) },
};
export default meta;

type Story = StoryObj<typeof StakeholderGroupsField>;

export const EmptyState: Story = {
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("Not in any group.")).toBeInTheDocument();
    await expect(within(canvasElement).getByRole("button", { name: "Save groups" })).toBeDisabled();
  },
};

export const ShowsCurrentGroupsWithTheirPath: Story = {
  args: { current: [{ id: "acme", name: "Acme", scope: "organization", parent_group_id: "client" }] },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("Acme", { selector: ".badge" })).toHaveAttribute("title", "Client › Acme");
  },
};

export const SavesTheChosenSet: Story = {
  args: { current: [{ id: "acme", name: "Acme", scope: "organization", parent_group_id: "client" }] },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Organisation groups" }));
    await userEvent.click(within(document.body).getByRole("checkbox", { name: "Operations" }));
    await userEvent.click(canvas.getByRole("button", { name: "Save groups" }));
    await expect(args.onSave).toHaveBeenCalledWith(expect.arrayContaining(["acme", "ops"]));
    await waitFor(() => expect(canvas.getByRole("button", { name: "Save groups" })).toBeDisabled());
  },
};

export const ProjectTierDisablesOrganisationGroups: Story = {
  args: { tier: "project" },
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Project groups" }));
    const popover = within(document.body);
    await expect(popover.getByRole("checkbox", { name: "Operations" })).toBeDisabled();
    await expect(popover.getByRole("checkbox", { name: "Pilot" })).toBeEnabled();
  },
};

export const ASaveFailureKeepsTheDraft: Story = {
  args: { onSave: fn(async () => { throw new Error("Conflict"); }) },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Organisation groups" }));
    await userEvent.click(within(document.body).getByRole("checkbox", { name: "Operations" }));
    await userEvent.click(canvas.getByRole("button", { name: "Save groups" }));
    await expect(canvas.getByRole("button", { name: "Save groups" })).toBeEnabled();
  },
};
