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

function Harness({ nodes, initial, mode = "multiple" }: { nodes: TreeSelectNode[]; initial: string[]; mode?: "multiple" | "single" | "search" }) {
  const [selected, setSelected] = useState(initial);
  if (mode === "single") {
    return <TreeSelect triggerLabel="Type" nodes={nodes} selectedIds={selected} onChange={setSelected} single clearLabel="All types" emptyLabel="All types" />;
  }
  return <TreeSelect triggerLabel="Groups" nodes={nodes} selectedIds={selected} onChange={setSelected} searchable={mode === "search"} />;
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
    // Why the node cannot be chosen is a tooltip, not a native title.
    await userEvent.hover(within(document.body).getByRole("checkbox", { name: "Client" }).closest("label") as HTMLElement);
    await expect(within(document.body).getByText("Organisation groups are edited by an organisation admin.")).toBeInTheDocument();
  },
};

/** A one-choice picker: a radio per node, choosing closes the list, and the clear entry empties the choice. */
export const SingleChoiceClosesAndCanBeCleared: Story = {
  args: { mode: "single" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Type" }));
    await userEvent.click(within(document.body).getByRole("radio", { name: "Beta Ltd" }));
    await expect(canvas.getByRole("button", { name: "Type" })).toHaveTextContent("Beta Ltd");
    await expect(within(document.body).queryByRole("radio", { name: "Beta Ltd" })).not.toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Type" }));
    await userEvent.click(within(document.body).getByRole("radio", { name: "Acme" }));
    await expect(canvas.getByRole("button", { name: "Type" })).toHaveTextContent("Acme");
    await userEvent.click(canvas.getByRole("button", { name: "Type" }));
    await userEvent.click(within(document.body).getByRole("radio", { name: "All types" }));
    await expect(canvas.getByRole("button", { name: "Type" })).toHaveTextContent("All types");
  },
};

/** The search keeps matching nodes and the ancestors that lead to them, with every branch open. */
export const SearchKeepsMatchesAndTheirAncestors: Story = {
  args: { mode: "search" },
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Groups" }));
    const popover = within(document.body);
    await userEvent.type(popover.getByRole("searchbox", { name: "Search Groups" }), "finance");
    await expect(popover.getByRole("checkbox", { name: "Acme — Finance" })).toBeInTheDocument();
    await expect(popover.getByRole("checkbox", { name: "Client" })).toBeInTheDocument();
    await expect(popover.queryByRole("checkbox", { name: "Operations" })).not.toBeInTheDocument();
    await userEvent.clear(popover.getByRole("searchbox", { name: "Search Groups" }));
    await userEvent.type(popover.getByRole("searchbox", { name: "Search Groups" }), "zzz");
    await expect(popover.getByText("Nothing matches.")).toBeInTheDocument();
  },
};

/** A node under two parents shows the same state in both places. */
export const ANodeUnderTwoParentsStaysInStep: Story = {
  args: {
    nodes: [
      { id: "serial", label: "Serial bus", children: [{ id: "i2c", label: "I2C", children: [] }] },
      { id: "board", label: "Board-to-board", children: [{ id: "i2c", label: "I2C", children: [] }] },
    ],
  },
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Groups" }));
    const both = within(document.body).getAllByRole("checkbox", { name: "I2C" });
    await expect(both).toHaveLength(2);
    await userEvent.click(both[0]);
    for (const box of within(document.body).getAllByRole("checkbox", { name: "I2C" })) await expect(box).toBeChecked();
  },
};

export const LightTheme: Story = { ...Empty, globals: { theme: "light" } };
export const DarkTheme: Story = { ...Empty, globals: { theme: "dark" } };
