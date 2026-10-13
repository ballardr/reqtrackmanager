import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { GroupsFromTextModal } from "./GroupsFromTextModal";

const PROPOSALS = [
  { name: "Acme", stakeholder_count: 2, existing_group_id: null },
  { name: "Beta", stakeholder_count: 1, existing_group_id: "group-beta" },
];

const meta: Meta<typeof GroupsFromTextModal> = {
  title: "Modules/Stakeholders/GroupsFromTextModal",
  component: GroupsFromTextModal,
  args: { proposals: PROPOSALS, onCancel: fn(), onConfirm: fn() },
};
export default meta;

type Story = StoryObj<typeof GroupsFromTextModal>;

const dialog = () => within(within(document.body).getByRole("dialog"));

export const EveryValueStartsTicked: Story = {
  play: async ({ args }) => {
    await expect(dialog().getByText("2 stakeholders")).toBeInTheDocument();
    await expect(dialog().getByText(/1 stakeholder · group exists/)).toBeInTheDocument();
    await userEvent.click(dialog().getByRole("button", { name: "Create groups" }));
    await expect(args.onConfirm).toHaveBeenCalledWith(["Acme", "Beta"]);
  },
};

export const UntickingLeavesAValueOut: Story = {
  play: async ({ args }) => {
    await userEvent.click(dialog().getByLabelText("Beta"));
    await userEvent.click(dialog().getByRole("button", { name: "Create groups" }));
    await expect(args.onConfirm).toHaveBeenCalledWith(["Acme"]);
  },
};

export const NothingTickedDisablesConfirm: Story = {
  play: async () => {
    await userEvent.click(dialog().getByLabelText("Acme"));
    await userEvent.click(dialog().getByLabelText("Beta"));
    await expect(dialog().getByRole("button", { name: "Create groups" })).toBeDisabled();
  },
};

export const NoValuesExplainsWhy: Story = {
  args: { proposals: [] },
  play: async () => {
    await expect(dialog().getByText(/No Stakeholder has an Organisation \/ group value yet/)).toBeInTheDocument();
    await expect(dialog().getByRole("button", { name: "Create groups" })).toBeDisabled();
  },
};
