import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, userEvent, within } from "storybook/test";

import { TreeSelect, type TreeSelectNode } from "./TreeSelect";

const NODES: TreeSelectNode[] = [
  {
    id: "client", label: "Client",
    children: [
      { id: "acme", label: "Acme", children: [{ id: "acme-fin", label: "Acme — Finance", children: [] }] },
      { id: "beta", label: "Beta Ltd", children: [] },
    ],
  },
  { id: "ops", label: "Operations", children: [] },
];

function Harness({ nodes, initial }: { nodes: TreeSelectNode[]; initial: string[] }) {
  const [selected, setSelected] = useState(initial);
  return <TreeSelect triggerLabel="Groups" nodes={nodes} selectedIds={selected} onChange={setSelected} />;
}

const meta: Meta<typeof Harness> = { title: "Components/TreeSelect", component: Harness, args: { nodes: NODES, initial: [] } };
export default meta;

type Story = StoryObj<typeof Harness>;

export const Empty: Story = {
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("button", { name: "Groups" })).toHaveTextContent("None");
  },
};

export const PicksSeveralNodes: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Groups" }));
    const popover = within(document.body);
    await userEvent.click(popover.getByRole("checkbox", { name: "Acme — Finance" }));
    await userEvent.click(popover.getByRole("checkbox", { name: "Operations" }));
    await expect(canvas.getByRole("button", { name: "Groups" })).toHaveTextContent("Acme — Finance, Operations");
    // Ancestors are independent: choosing a child does not check its parent.
    await expect(popover.getByRole("checkbox", { name: "Acme" })).not.toBeChecked();
    await userEvent.click(popover.getByRole("checkbox", { name: "Operations" }));
    await expect(canvas.getByRole("button", { name: "Groups" })).toHaveTextContent("Acme — Finance");
  },
};

export const WithDisabledNode: Story = {
  args: {
    nodes: [{ ...NODES[0], disabled: true, title: "Organisation groups are edited by an organisation admin." }, NODES[1]],
    initial: ["ops"],
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Groups" }));
    await expect(within(document.body).getByRole("checkbox", { name: "Client" })).toBeDisabled();
  },
};

export const LightTheme: Story = { ...Empty, globals: { theme: "light" } };
export const DarkTheme: Story = { ...Empty, globals: { theme: "dark" } };
