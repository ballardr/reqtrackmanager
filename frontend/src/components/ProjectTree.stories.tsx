import type { Meta, StoryObj } from "@storybook/react-vite";
import { MemoryRouter } from "react-router-dom";
import { expect, fn, userEvent, within } from "storybook/test";

import type { ProjectTreeNode } from "../api/types";
import { ProjectTree } from "./ProjectTree";

const meta: Meta<typeof ProjectTree> = {
  title: "Components/ProjectTree",
  component: ProjectTree,
  decorators: [(Story) => <MemoryRouter><Story /></MemoryRouter>],
};
export default meta;

type Story = StoryObj<typeof ProjectTree>;

function node(overrides: Partial<ProjectTreeNode>): ProjectTreeNode {
  return { id: "1", name: "Project", organization_id: "org-1", is_archived: false, children: [], ...overrides };
}

export const Empty: Story = {
  args: { nodes: [] },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("No projects to show.")).toBeInTheDocument();
  },
};

export const SingleRootNoChildren: Story = {
  args: { nodes: [node({ id: "root", name: "Platform" })] },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("link", { name: "Platform" })).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: /Collapse|Expand/ })).not.toBeInTheDocument();
  },
};

const multiLevelNodes: ProjectTreeNode[] = [
  node({
    id: "root",
    name: "Platform",
    children: [
      node({
        id: "auth",
        name: "Authentication",
        children: [node({ id: "sso", name: "SSO Integration" }), node({ id: "mfa", name: "MFA Rollout" })],
      }),
      node({ id: "billing", name: "Billing", is_archived: true }),
    ],
  }),
];

export const MultiLevel: Story = {
  args: { nodes: multiLevelNodes },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("link", { name: "Platform" })).toBeInTheDocument();
    await expect(canvas.getByRole("link", { name: "SSO Integration" })).toBeInTheDocument();
    // Archived children still render, visually de-emphasised.
    await expect(canvas.getByRole("link", { name: "Billing" })).toBeInTheDocument();
  },
};

export const CollapseExpand: Story = {
  args: { nodes: multiLevelNodes },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("link", { name: "SSO Integration" })).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Collapse Authentication" }));
    await expect(canvas.queryByRole("link", { name: "SSO Integration" })).not.toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Expand Authentication" }));
    await expect(canvas.getByRole("link", { name: "SSO Integration" })).toBeInTheDocument();
  },
};

export const ManyChildrenWithAddAffordance: Story = {
  args: {
    nodes: [
      node({
        id: "root",
        name: "Program",
        children: Array.from({ length: 6 }, (_, i) => node({ id: `child-${i}`, name: `Workstream ${i + 1}` })),
      }),
    ],
    onAddChild: fn(),
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getAllByRole("button", { name: /Add a sub-project under/ }).length).toBeGreaterThan(1);
    await userEvent.click(canvas.getByRole("button", { name: "Add a sub-project under Program" }));
    await expect(args.onAddChild).toHaveBeenCalledWith("root", "Program");
  },
};

export const LightTheme: Story = { ...MultiLevel, globals: { theme: "light" } };
export const DarkTheme: Story = { ...MultiLevel, globals: { theme: "dark" } };
