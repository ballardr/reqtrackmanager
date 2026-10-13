import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { buildStakeholderGroup } from "./fixtures";
import { StakeholderGroupFormModal } from "./StakeholderGroupFormModal";

const GROUPS = [
  buildStakeholderGroup({ id: "client", name: "Client", child_count: 1 }),
  buildStakeholderGroup({ id: "acme", name: "Acme", parent_group_id: "client", child_count: 1 }),
  buildStakeholderGroup({ id: "acme-fin", name: "Acme — Finance", parent_group_id: "acme" }),
  buildStakeholderGroup({ id: "ops", name: "Operations" }),
];

const meta: Meta<typeof StakeholderGroupFormModal> = {
  title: "Modules/Stakeholders/StakeholderGroupFormModal",
  component: StakeholderGroupFormModal,
  args: { groups: GROUPS, onCancel: fn(), onSave: fn() },
};
export default meta;

type Story = StoryObj<typeof StakeholderGroupFormModal>;

// The modal portals to `document.body`.
const dialog = () => within(within(document.body).getByRole("dialog"));

export const CreateNeedsAName: Story = {
  play: async () => {
    await expect(dialog().getByRole("button", { name: "Save" })).toBeDisabled();
    await userEvent.type(dialog().getByLabelText("Group name"), "Beta Ltd");
    await expect(dialog().getByRole("button", { name: "Save" })).toBeEnabled();
  },
};

export const SavesParentAndExclusiveFlag: Story = {
  play: async ({ args }) => {
    await userEvent.type(dialog().getByLabelText("Group name"), "Beta Ltd");
    await userEvent.selectOptions(dialog().getByLabelText("Parent group"), "client");
    await userEvent.click(dialog().getByLabelText("One branch per stakeholder"));
    await userEvent.click(dialog().getByRole("button", { name: "Save" }));
    await expect(args.onSave).toHaveBeenCalledWith({
      name: "Beta Ltd", description: "", parent_group_id: "client", exclusive_children: true,
    });
  },
};

export const AddChildPreselectsTheParent: Story = {
  args: { defaultParentId: "ops" },
  play: async () => {
    await expect(dialog().getByLabelText("Parent group")).toHaveValue("ops");
  },
};

export const EditOffersNeitherItselfNorItsDescendantsAsParent: Story = {
  args: { initial: GROUPS[1] },
  play: async () => {
    const options = within(dialog().getByLabelText("Parent group")).getAllByRole("option").map((o) => o.textContent?.trim());
    await expect(options).toEqual(["None (top level)", "Client", "Operations"]);
    await expect(dialog().getByLabelText("Group name")).toHaveValue("Acme");
  },
};

export const ShowsAServerError: Story = {
  args: { error: "A group named 'Beta Ltd' already exists here." },
  play: async () => {
    await expect(dialog().getByText("A group named 'Beta Ltd' already exists here.")).toBeInTheDocument();
  },
};
