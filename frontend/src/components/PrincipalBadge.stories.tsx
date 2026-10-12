import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";

import { PrincipalBadge } from "./PrincipalBadge";

const meta: Meta<typeof PrincipalBadge> = { title: "Components/PrincipalBadge", component: PrincipalBadge };
export default meta;

type Story = StoryObj<typeof PrincipalBadge>;

/** A user is just their name, with no kind tag. */
export const User: Story = {
  args: { principal: { type: "user", id: "u1", label: "Alex Morgan", member_count: null, exists: true } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Alex Morgan")).toBeInTheDocument();
    await expect(canvas.queryByText(/group/i)).not.toBeInTheDocument();
  },
};

/** An org group names its kind and how many people it stands for. */
export const OrgGroup: Story = {
  args: { principal: { type: "org_group", id: "g1", label: "Platform team", member_count: 4, exists: true } },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("Org group · 4 members")).toBeInTheDocument();
  },
};

export const ProjectGroupWithOneMember: Story = {
  args: { principal: { type: "project_group", id: "pg1", label: "Release board", member_count: 1, exists: true } },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("Project group · 1 member")).toBeInTheDocument();
  },
};

/** A history row can still name a group that has since been deleted. */
export const DeletedGroup: Story = {
  args: { principal: { type: "org_group", id: "g9", label: "Deleted group", member_count: null, exists: false } },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("Org group · deleted")).toBeInTheDocument();
  },
};

export const Empty: Story = {
  args: { principal: null },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("Unassigned")).toBeInTheDocument();
  },
};

export const DarkTheme: Story = { ...OrgGroup, globals: { theme: "dark" } };
