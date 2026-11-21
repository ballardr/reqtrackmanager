import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";

import { buildAliasedRequirement } from "../testing/requirementAliasFixtures";
import { RequirementListCode } from "./RequirementListCode";

/**
 * A requirement's code in a list row. Narrowed to a place the requirement reaches only through an alias, the alias
 * code follows in muted text.
 */
const meta: Meta<typeof RequirementListCode> = {
  title: "Components/RequirementListCode",
  component: RequirementListCode,
  args: { requirement: buildAliasedRequirement(), componentId: "", categoryId: "" },
};
export default meta;

type Story = StoryObj<typeof RequirementListCode>;

export const OwnCodeWhenNotNarrowed: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("SW-PERF-001")).toBeInTheDocument();
    await expect(canvas.queryByText(/HW-COOL-002/)).not.toBeInTheDocument();
  },
};

export const AliasCodeFollowsWhenNarrowedToTheAliasComponent: Story = {
  args: { componentId: "c-hw" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("SW-PERF-001")).toBeInTheDocument();
    await expect(canvas.getByText(/HW-COOL-002/)).toBeInTheDocument();
  },
};

export const OwnCodeAloneWhenNarrowedToTheOwnComponent: Story = {
  args: { componentId: "c-sw", categoryId: "k-perf" },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).queryByText(/HW-COOL-002/)).not.toBeInTheDocument();
  },
};
