import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, userEvent, within } from "storybook/test";

import { TreeView, type TreeViewNode } from "./TreeView";

interface Item extends TreeViewNode<Item> {
  name: string;
}

const meta: Meta<typeof TreeView<Item>> = {
  title: "Components/TreeView",
  component: TreeView<Item>,
  args: {
    nodeLabel: (n: Item) => n.name,
    renderNode: (n: Item) => <span>{n.name}</span>,
  },
};
export default meta;

type Story = StoryObj<typeof TreeView<Item>>;

const NODES: Item[] = [
  {
    id: "client", name: "Client",
    children: [
      { id: "acme", name: "Acme", children: [{ id: "acme-fin", name: "Acme — Finance", children: [] }] },
      { id: "beta", name: "Beta Ltd", children: [] },
    ],
  },
  { id: "ops", name: "Operations", children: [] },
];

export const Default: Story = {
  args: { nodes: NODES },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Acme — Finance")).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Collapse Acme" }));
    await expect(canvas.queryByText("Acme — Finance")).not.toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Expand Acme" }));
    await expect(canvas.getByText("Acme — Finance")).toBeInTheDocument();
  },
};

export const StartsCollapsed: Story = {
  args: { nodes: NODES, defaultExpanded: false },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Client")).toBeInTheDocument();
    await expect(canvas.queryByText("Acme")).not.toBeInTheDocument();
  },
};

export const Empty: Story = {
  args: { nodes: [], emptyText: "No groups yet." },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("No groups yet.")).toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...Default, globals: { theme: "light" } };
export const DarkTheme: Story = { ...Default, globals: { theme: "dark" } };
