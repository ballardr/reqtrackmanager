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

/** The chevron stays beside the label and is plain; every checkbox sits in one column at the right edge whatever its depth. */
export const CheckboxesShareOneColumnAtTheRightEdge: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Groups" }));
    const popover = within(document.body);
    const chevron = popover.getByRole("button", { name: "Collapse Acme" });
    await expect(chevron).toHaveClass("tree-toggle");
    await expect(chevron).not.toHaveClass("btn");
    const rights = ["Client", "Acme", "Acme — Finance", "Operations"].map(
      (name) => popover.getByRole("checkbox", { name }).getBoundingClientRect().right,
    );
    for (const right of rights) await expect(Math.abs(right - rights[0])).toBeLessThan(1);
    // The box is right of its label, and the chevron left of it.
    const label = popover.getByText("Acme — Finance", { exact: true }).getBoundingClientRect();
    await expect(popover.getByRole("checkbox", { name: "Acme — Finance" }).getBoundingClientRect().left).toBeGreaterThan(label.right - 1);
    await expect(chevron.getBoundingClientRect().right).toBeLessThanOrEqual(popover.getByText("Acme", { exact: true }).getBoundingClientRect().left);
  },
};

/** Pressing the label chooses the row, and the chevron works from the keyboard without choosing anything. */
export const TheRowIsTheTargetAndTheChevronIsKeyboardOperable: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Groups" }));
    const popover = within(document.body);
    await userEvent.click(popover.getByText("Beta Ltd", { exact: true }));
    await expect(popover.getByRole("checkbox", { name: "Beta Ltd" })).toBeChecked();
    popover.getByRole("button", { name: "Collapse Client" }).focus();
    await userEvent.keyboard("{Enter}");
    await expect(popover.queryByRole("checkbox", { name: "Acme" })).not.toBeInTheDocument();
    await expect(popover.getByRole("button", { name: "Expand Client" })).toHaveAttribute("aria-expanded", "false");
    await expect(canvas.getByRole("button", { name: "Groups" })).toHaveTextContent("Beta Ltd");
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

/** A one-choice picker: a selectable row per node (read as a radio, not drawn as a radio button), choosing closes the list, and the clear row empties the choice. */
export const SingleChoiceClosesAndCanBeCleared: Story = {
  args: { mode: "single" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Type" }));
    // Rows, not radio inputs; the tree keeps its levels (a branch can be collapsed).
    await expect(within(document.body).queryByRole("radio", { name: "Beta Ltd" })?.tagName).toBe("BUTTON");
    await expect(within(document.body).getAllByRole("button", { name: /^Collapse / }).length).toBeGreaterThan(0);
    await userEvent.click(within(document.body).getByRole("radio", { name: "Beta Ltd" }));
    await expect(canvas.getByRole("button", { name: "Type" })).toHaveTextContent("Beta Ltd");
    await expect(within(document.body).queryByRole("radio", { name: "Beta Ltd" })).not.toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Type" }));
    await userEvent.click(within(document.body).getByRole("radio", { name: "Acme" }));
    await expect(canvas.getByRole("button", { name: "Type" })).toHaveTextContent("Acme");
    await userEvent.click(canvas.getByRole("button", { name: "Type" }));
    await expect(within(document.body).getByRole("radio", { name: "Acme" })).toHaveAttribute("aria-checked", "true");
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

/** Forty options under one heading: enough to scroll inside the capped list. */
const LONG_NODES: TreeSelectNode[] = [
  {
    id: "all", label: "Components",
    children: Array.from({ length: 40 }, (_, i) => ({ id: `c${i}`, label: `Component ${String(i + 1).padStart(2, "0")}`, children: [] })),
  },
];

/** The picker's single scroll region and its panel: the search box stays put while the list scrolls. */
function pickerParts(popover: HTMLElement) {
  const panel = popover.closest('[role="dialog"]') as HTMLElement;
  const region = panel.querySelector(".scroll-region") as HTMLElement;
  const search = within(panel).getByRole("searchbox");
  return { panel, region, search };
}

/** The search box is a fixed header: scrolling the list moves the rows, never the search. */
export const SearchStaysPutWhileTheListScrolls: Story = {
  args: { mode: "search", nodes: LONG_NODES },
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Groups" }));
    const { panel, region, search } = pickerParts(within(document.body).getByRole("group", { name: "Groups" }));
    // The list is the only scrolling element: the panel itself does not scroll.
    await expect(region.scrollHeight).toBeGreaterThan(region.clientHeight);
    await expect(panel.scrollHeight).toBeLessThanOrEqual(panel.clientHeight + 1);
    const before = search.getBoundingClientRect().top;
    region.scrollTop = 300;
    await expect(region.scrollTop).toBeGreaterThan(0);
    await expect(search.getBoundingClientRect().top).toBe(before);
  },
};

/** At the end of the list the last row is whole and the list meets the panel's border, so nothing is cut mid-text. */
export const TheLastRowIsWholeAtTheEnd: Story = {
  args: { mode: "search", nodes: LONG_NODES },
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Groups" }));
    const { panel, region } = pickerParts(within(document.body).getByRole("group", { name: "Groups" }));
    region.scrollTop = region.scrollHeight;
    const last = within(region).getByRole("checkbox", { name: "Component 40" }).closest("label") as HTMLElement;
    await expect(last.getBoundingClientRect().bottom).toBeLessThanOrEqual(region.getBoundingClientRect().bottom + 0.5);
    // Flush with the panel: only its one-pixel border lies between the region's edge and the panel's.
    await expect(panel.getBoundingClientRect().bottom - region.getBoundingClientRect().bottom).toBeLessThanOrEqual(2);
    await expect(panel.getBoundingClientRect().right - region.getBoundingClientRect().right).toBeLessThanOrEqual(2);
  },
};

/** An edge shows on a side only while content continues beyond it: the shadow is fixed to the box under a cover that
 * moves with the content, so the box has the cover and shadow layers and no scroll listener. */
export const EdgeIndicatorsComeFromTheSharedRule: Story = {
  args: { mode: "search", nodes: LONG_NODES },
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Groups" }));
    const { region } = pickerParts(within(document.body).getByRole("group", { name: "Groups" }));
    const style = getComputedStyle(region);
    await expect(style.backgroundAttachment).toBe("local, local, scroll, scroll");
    await expect(style.overscrollBehaviorY).toBe("contain");
    await expect(style.overflowY).toBe("auto");
  },
};

/** A list shorter than its cap has no scrollbar to draw. */
export const AShortListDoesNotScroll: Story = {
  args: { mode: "search" },
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Groups" }));
    const { region } = pickerParts(within(document.body).getByRole("group", { name: "Groups" }));
    await expect(region.scrollHeight).toBeLessThanOrEqual(region.clientHeight);
  },
};

/** A one-choice picker over components and categories: a child row shows its own name under the heading (the path stays
 * its accessible name), so "Propulsion / Performance" fits on one line at the default width. */
export const OneChoiceRowShowsTheOwnNameOnOneLine: Story = {
  args: {
    mode: "single",
    nodes: [
      {
        id: "propulsion", label: "Propulsion", disabled: true,
        children: [{ id: "perf", label: "Performance", pathLabel: "Propulsion / Performance", children: [] }],
      },
      { id: "structure", label: "Structure", disabled: true, children: [] },
    ],
  },
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Type" }));
    const popover = within(document.body);
    const row = popover.getByRole("radio", { name: "Propulsion / Performance" });
    await expect(row).toHaveTextContent("Performance");
    await expect(row).not.toHaveTextContent("Propulsion");
    // One line: the row is no taller than a one-line sibling.
    await expect(row.getBoundingClientRect().height).toBeLessThanOrEqual(popover.getByRole("radio", { name: "Structure" }).getBoundingClientRect().height + 1);
    await userEvent.click(row);
    await expect(within(canvasElement).getByRole("button", { name: "Type" })).toHaveTextContent("Propulsion / Performance");
  },
};

export const LightTheme: Story = { ...Empty, globals: { theme: "light" } };
export const DarkTheme: Story = { ...Empty, globals: { theme: "dark" } };

/** The long list in each theme, opened, so the edge shadow colours are checked in both. */
export const LongListLight: Story = { ...SearchStaysPutWhileTheListScrolls, globals: { theme: "light" } };
export const LongListDark: Story = { ...SearchStaysPutWhileTheListScrolls, globals: { theme: "dark" } };
