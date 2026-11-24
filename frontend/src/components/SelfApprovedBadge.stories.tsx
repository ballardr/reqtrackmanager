import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";

import { buildApprovalStatus } from "../testing/approvalSeparationFixtures";
import { SelfApprovedBadge } from "./SelfApprovedBadge";

/** The marker of a record whose latest approval was given by the person who created it. */
const meta: Meta<typeof SelfApprovedBadge> = {
  title: "Components/SelfApprovedBadge",
  component: SelfApprovedBadge,
};
export default meta;

type Story = StoryObj<typeof SelfApprovedBadge>;

export const MarksASelfApproval: Story = {
  args: { status: buildApprovalStatus({ self_approved: true, approved_by_name: "Ada Lovelace", approved_at: "2026-11-24T09:00:00Z" }) },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("Self-approved")).toBeInTheDocument();
  },
};

export const DrawsNothingForAnotherApprover: Story = {
  args: { status: buildApprovalStatus() },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).queryByText("Self-approved")).not.toBeInTheDocument();
  },
};

export const DrawsNothingWhileUnknown: Story = {
  args: { status: null },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).queryByText("Self-approved")).not.toBeInTheDocument();
  },
};
