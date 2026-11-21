import type { Meta, StoryObj } from "@storybook/react-vite";
import { FileText, Package, Users } from "lucide-react";
import { useMemo, useState } from "react";
import { expect, userEvent, within } from "storybook/test";

import { buildFolderTree, type FolderNode } from "../utils/reportFolders";
import { FolderTreeList, type FolderTreeColumn } from "./FolderTreeList";
import { realFolderIcon } from "./folderTreeIcons";

interface Doc {
  id: string;
  title: string;
  folder: string;
  kind: "report" | "pack";
  version: number;
  note: string;
}

const DOCS: Doc[] = [
  { id: "req", title: "Requirements report", folder: "Platform", kind: "report", version: 3, note: "Every requirement." },
  { id: "dec", title: "Decision register", folder: "Decision Management", kind: "report", version: 1, note: "" },
  { id: "hand", title: "Handover document", folder: "Handover/Quarterly/2026", kind: "report", version: 7, note: "For the external team." },
  { id: "zip", title: "Programme handover", folder: "Handover", kind: "pack", version: 2, note: "A zip of the handover reports." },
  { id: "long", title: "A report whose title is far too long to fit on one line of a narrow dialog without wrapping", folder: "", kind: "report", version: 1, note: "" },
];

const COLUMNS: FolderTreeColumn<Doc>[] = [
  { id: "version", header: "Version", render: (d) => `v${d.version}`, sortValue: (d) => d.version, width: "5rem" },
  { id: "note", header: "Note", render: (d) => d.note, hideBelow: true },
];

/** The ids of the items at or below a node. */
const collect = (node: FolderNode<Doc>): string[] => (node.kind === "item" ? [node.item?.id ?? ""] : node.children.flatMap(collect));

/** Hosts the list with its own open folders, so a story sees the chevrons and rows follow the clicks. */
function Host({
  docs = DOCS, columns, initiallyOpen = [], width, extraFolders = [], folderActions = false, ticks = false, order, emptyFolderText, groupIcon = false,
}: {
  docs?: Doc[]; columns?: FolderTreeColumn<Doc>[]; initiallyOpen?: string[]; width?: string; extraFolders?: string[]; folderActions?: boolean;
  ticks?: boolean; order?: "sorted" | "given"; emptyFolderText?: string; groupIcon?: boolean;
}) {
  const [open, setOpen] = useState(new Set(initiallyOpen));
  const [chosen, setChosen] = useState("");
  const [ticked, setTicked] = useState<ReadonlySet<string>>(new Set());
  const tree = useMemo(() => {
    const nodes = buildFolderTree(docs, (d) => d.folder, (d) => d.title, (d) => d.id);
    const empty: FolderNode<Doc>[] = extraFolders.map((name) => ({ id: `f:${name.toLowerCase()}`, kind: "folder", name, path: name, children: [], count: 0 }));
    return [...nodes, ...empty];
  }, [docs, extraFolders]);
  return (
    <div style={width ? { width } : undefined}>
      <FolderTreeList
        nodes={tree} label="Documents" expanded={open} order={order} emptyFolderText={emptyFolderText}
        folderIcon={groupIcon ? () => <Users aria-hidden="true" /> : realFolderIcon}
        onToggle={(id, isOpen) => setOpen((c) => { const n = new Set(c); if (isOpen) n.add(id); else n.delete(id); return n; })}
        itemView={(d) => ({ icon: d.kind === "pack" ? <Package /> : <FileText />, iconLabel: d.kind === "pack" ? "Pack" : "Report", description: d.note })}
        isSelected={(d) => d.id === chosen} onOpenItem={(d) => setChosen(d.id)} columns={columns}
        folderBadge={(n) => String(n.count)}
        renderItemActions={(d) => <button type="button" className="btn" aria-label={`Star ${d.title}`}>★</button>}
        renderFolderActions={folderActions ? (n) => <button type="button" className="btn" aria-label={`Actions for the folder ${n.name}`}>⋮</button> : undefined}
        checks={ticks ? {
          state: (n) => {
            if (n.kind === "item") return ticked.has(n.item?.id ?? "");
            const ids = collect(n);
            const count = ids.filter((id) => ticked.has(id)).length;
            return count === ids.length ? true : count === 0 ? false : "mixed";
          },
          onChange: (n, on) => setTicked((c) => {
            const next = new Set(c);
            for (const id of n.kind === "item" ? [n.item?.id ?? ""] : collect(n)) { if (on) next.add(id); else next.delete(id); }
            return next;
          }),
          label: (n) => `Select ${n.name}`,
          disabled: (n) => n.item?.id === "zip",
        } : undefined}
        emptyText="Nothing to list."
      />
    </div>
  );
}

/**
 * A file manager's list view of folders and items: a sortable Name header, a chevron and folder icon on each folder,
 * a type icon on each item, indented children and banded rows.
 */
const meta: Meta<typeof Host> = { title: "Components/FolderTreeList", component: Host };
export default meta;

type Story = StoryObj<typeof Host>;

const names = (list: HTMLElement) => within(list).getAllByRole("row").slice(1).map((r) => r.textContent ?? "");

/** Folders are closed, carry a count and sit before the loose item. */
export const FoldersFirstAndClosed: Story = {
  play: async ({ canvasElement }) => {
    const grid = within(canvasElement).getByRole("treegrid", { name: "Documents" });
    await expect(within(grid).getByRole("button", { name: "Expand Platform" })).toHaveAttribute("aria-expanded", "false");
    const rows = names(grid);
    await expect(rows[rows.length - 1]).toMatch(/^A report whose title/);
    await expect(within(grid).queryByRole("button", { name: /^Requirements report/ })).not.toBeInTheDocument();
  },
};

/** Opening a folder indents what is inside it one level further, to the depth of the path. */
export const DeepFoldersIndent: Story = {
  args: { initiallyOpen: ["f:handover", "f:handover/quarterly", "f:handover/quarterly/2026"] },
  play: async ({ canvasElement }) => {
    const grid = within(canvasElement).getByRole("treegrid", { name: "Documents" });
    const level = (name: RegExp) => within(grid).getByRole("button", { name }).closest("[role=row]")!.getAttribute("aria-level");
    await expect(level(/Collapse Handover$/)).toBe("1");
    await expect(level(/Collapse Quarterly$/)).toBe("2");
    await expect(level(/Collapse 2026$/)).toBe("3");
    await expect(level(/^Handover document/)).toBe("4");
  },
};

/** An open folder with nothing in it says so. */
export const EmptyFolder: Story = {
  args: { extraFolders: ["Archive"], initiallyOpen: ["f:archive"] },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("Empty folder")).toBeInTheDocument();
  },
};

/** Nothing to list shows the empty text, not a bare header. */
export const NothingToList: Story = {
  args: { docs: [] },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("Nothing to list.")).toBeInTheDocument();
    await expect(within(canvasElement).queryByRole("treegrid")).not.toBeInTheDocument();
  },
};

/** The Name header sorts the items either way, and folders stay first. */
export const NameHeaderSorts: Story = {
  args: { initiallyOpen: ["f:platform", "f:decision management"] },
  play: async ({ canvasElement }) => {
    const grid = within(canvasElement).getByRole("treegrid", { name: "Documents" });
    const header = within(grid).getByRole("columnheader", { name: /Name/ });
    await expect(header).toHaveAttribute("aria-sort", "ascending");
    await userEvent.click(within(header).getByRole("button"));
    await expect(header).toHaveAttribute("aria-sort", "descending");
    const rows = names(grid);
    await expect(rows[0]).toMatch(/^Platform/);
    await expect(rows[rows.length - 1]).toMatch(/^A report whose title/);
  },
};

/** A column that declares a sort value sorts by it; the other column cannot be sorted. */
export const ExtraColumnsSort: Story = {
  args: { columns: COLUMNS, docs: DOCS.map((d) => ({ ...d, folder: "" })) },
  play: async ({ canvasElement }) => {
    const grid = within(canvasElement).getByRole("treegrid", { name: "Documents" });
    await expect(within(grid).getByRole("columnheader", { name: "Note" })).not.toHaveAttribute("aria-sort");
    await userEvent.click(within(within(grid).getByRole("columnheader", { name: "Version" })).getByRole("button"));
    await expect(within(grid).getByRole("columnheader", { name: "Version" })).toHaveAttribute("aria-sort", "ascending");
    await userEvent.click(within(within(grid).getByRole("columnheader", { name: "Version" })).getByRole("button"));
    await expect(names(grid)[0]).toMatch(/^Handover document/);
  },
};

/** A click on a folder opens and closes it; a click on an item opens it. */
export const MouseOpensFoldersAndItems: Story = {
  play: async ({ canvasElement }) => {
    const grid = within(canvasElement).getByRole("treegrid", { name: "Documents" });
    await userEvent.click(within(grid).getByRole("button", { name: "Expand Platform" }));
    await userEvent.click(within(grid).getByRole("button", { name: /^Requirements report/ }));
    await expect(within(grid).getByRole("button", { name: /^Requirements report/ })).toHaveAttribute("aria-current", "true");
    await userEvent.click(within(grid).getByRole("button", { name: "Collapse Platform" }));
    await expect(within(grid).queryByRole("button", { name: /^Requirements report/ })).not.toBeInTheDocument();
  },
};

/** Arrow keys move between rows, Right opens a folder and goes in, Left closes it or goes to the parent, Enter opens an item. */
export const KeyboardNavigation: Story = {
  render: () => <Host />,
  play: async ({ canvasElement }) => {
    const grid = within(canvasElement).getByRole("treegrid", { name: "Documents" });
    const rows = () => within(grid).getAllByRole("row");
    // After the sortable Name header, the first row is the list's one tab stop.
    await userEvent.tab();
    await expect(within(grid).getByRole("button", { name: "Name" })).toHaveFocus();
    await userEvent.tab();
    await expect(rows()[1]).toHaveFocus();
    await userEvent.keyboard("{ArrowDown}");
    await expect(rows()[2]).toHaveFocus();
    await userEvent.keyboard("{Home}");
    await expect(rows()[1]).toHaveFocus();
    // Decision Management is the first folder by name; open it and step into it.
    await userEvent.keyboard("{ArrowRight}");
    await expect(rows()[1]).toHaveAttribute("aria-expanded", "true");
    await userEvent.keyboard("{ArrowRight}");
    await expect(rows()[2]).toHaveFocus();
    await expect(rows()[2]).toHaveTextContent("Decision register");
    // Enter on the item chooses it.
    await userEvent.keyboard("{Enter}");
    await expect(rows()[2]).toHaveAttribute("aria-selected", "true");
    // Left from an item goes to its folder, Left again closes the folder.
    await userEvent.keyboard("{ArrowLeft}");
    await expect(rows()[1]).toHaveFocus();
    await userEvent.keyboard("{ArrowLeft}");
    await expect(rows()[1]).toHaveAttribute("aria-expanded", "false");
    // Enter on a folder toggles it; End goes to the last row.
    await userEvent.keyboard("{Enter}");
    await expect(rows()[1]).toHaveAttribute("aria-expanded", "true");
    await userEvent.keyboard("{End}");
    await expect(rows()[rows().length - 1]).toHaveFocus();
  },
};

/** At a narrow width a long name wraps inside its cell, and the columns that do not fit scroll inside the list. */
export const NarrowWidthWrapsLongNames: Story = {
  args: { width: "320px", columns: COLUMNS },
  play: async ({ canvasElement }) => {
    const grid = within(canvasElement).getByRole("treegrid", { name: "Documents" });
    const long = within(grid).getByRole("button", { name: /^A report whose title/ });
    await expect(long.getBoundingClientRect().height).toBeGreaterThan(30);
    // The page itself never scrolls sideways: the overflow stays inside the list.
    await expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(document.documentElement.clientWidth);
  },
};

/** A phone-width list scrolls sideways inside its own region and the Name cell stays at the left edge, so every column can be reached. */
export const NarrowWidthScrollsWithNameHeld: Story = {
  args: { width: "260px", columns: [{ id: "wide", header: "Wide", render: () => "wide cell", width: "14rem" }], initiallyOpen: ["f:platform"] },
  play: async ({ canvasElement }) => {
    const grid = within(canvasElement).getByRole("treegrid", { name: "Documents" });
    await expect(grid.scrollWidth).toBeGreaterThan(grid.clientWidth);
    const name = () => within(grid).getByRole("button", { name: /^Requirements report/ }).closest<HTMLElement>(".folder-tree-name-cell")!;
    const edge = grid.getBoundingClientRect().left;
    grid.scrollLeft = 120;
    await expect(Math.abs(name().getBoundingClientRect().left - edge)).toBeLessThan(2);
    // The last cell is reachable by scrolling.
    grid.scrollLeft = grid.scrollWidth;
    await expect(within(grid).getAllByText("wide cell")[0].getBoundingClientRect().right).toBeLessThanOrEqual(grid.getBoundingClientRect().right + 1);
  },
};

/** The rows share one column template: a column header sits over its cells whatever the cells hold. */
export const ColumnsLineUpWithHeader: Story = {
  args: { columns: COLUMNS, docs: DOCS.map((d) => ({ ...d, folder: "" })) },
  play: async ({ canvasElement }) => {
    const grid = within(canvasElement).getByRole("treegrid", { name: "Documents" });
    const headerLeft = within(grid).getByRole("columnheader", { name: /Version/ }).getBoundingClientRect().left;
    for (const cell of within(grid).getAllByText(/^v\d$/)) {
      await expect(Math.abs(cell.getBoundingClientRect().left - headerLeft)).toBeLessThan(1);
    }
  },
};

/** A folder's row can carry trailing controls, as an item's does (the setup list's New folder, Rename and Delete). */
export const FolderRowsCarryTheirOwnActions: Story = {
  args: { folderActions: true },
  play: async ({ canvasElement }) => {
    const grid = within(canvasElement).getByRole("treegrid", { name: "Documents" });
    await expect(within(grid).getByRole("button", { name: "Actions for the folder Platform" })).toBeInTheDocument();
    await userEvent.click(within(grid).getByRole("button", { name: "Expand Platform" }));
    await expect(within(grid).getByRole("button", { name: "Star Requirements report" })).toBeInTheDocument();
    await expect(within(grid).getAllByRole("columnheader", { name: "Actions" })).toHaveLength(1);
  },
};

/** The icon of a folder row is the list's own: a real folder shows a closed folder, and an open folder shows the open one. */
export const RealFoldersShowTheFolderIcon: Story = {
  play: async ({ canvasElement }) => {
    const grid = within(canvasElement).getByRole("treegrid", { name: "Documents" });
    const icon = (name: string) => within(grid).getByRole("button", { name }).querySelector(".folder-tree-folder-icon svg");
    await expect(icon("Expand Platform")).toHaveClass("lucide-folder");
    await userEvent.click(within(grid).getByRole("button", { name: "Expand Platform" }));
    await expect(icon("Collapse Platform")).toHaveClass("lucide-folder-open");
  },
};

/** A list whose rows are not folders gives its own icon, and no folder icon is drawn. */
export const AListCanGiveItsFolderRowsAnotherIcon: Story = {
  args: { groupIcon: true },
  play: async ({ canvasElement }) => {
    const grid = within(canvasElement).getByRole("treegrid", { name: "Documents" });
    const button = within(grid).getByRole("button", { name: "Expand Platform" });
    await expect(button.querySelector(".folder-tree-folder-icon svg")).toHaveClass("lucide-users");
    await expect(grid.querySelector(".lucide-folder, .lucide-folder-open")).toBeNull();
  },
};

export const LightTheme: Story = { ...DeepFoldersIndent, globals: { theme: "light" } };
export const DarkTheme: Story = { ...DeepFoldersIndent, globals: { theme: "dark" } };

/** With tick boxes, a folder's box covers what is in it, shows the mixed state when only some are ticked, and a row can be left unticked. */
export const TickBoxesChooseRowsAndAFolderCoversItsItems: Story = {
  args: { ticks: true, initiallyOpen: ["f:handover"] },
  play: async ({ canvasElement }) => {
    const grid = within(canvasElement).getByRole("treegrid", { name: "Documents" });
    await userEvent.click(within(grid).getByRole("checkbox", { name: "Select Handover" }));
    await expect(within(grid).getByRole("checkbox", { name: "Select Handover" })).toBeChecked();
    await expect(within(grid).getByRole("checkbox", { name: "Select Programme handover" })).toBeDisabled();
    await userEvent.click(within(grid).getByRole("button", { name: "Expand Quarterly" }));
    await userEvent.click(within(grid).getByRole("button", { name: "Expand 2026" }));
    await userEvent.click(within(grid).getByRole("checkbox", { name: "Select Handover document" }));
    await expect(within(grid).getByRole("checkbox", { name: "Select Handover" })).toHaveAttribute("aria-checked", "mixed");
  },
};

/** With the given order, folders keep the order of the nodes passed in (here a folder that sorts first is last), and no header sorts. */
export const GivenOrderKeepsTheCallersOrderAndNoHeaderSorts: Story = {
  args: {
    order: "given", extraFolders: ["Aardvark"],
    columns: [{ id: "version", header: "Version", render: (d: Doc) => `v${d.version}`, sortValue: (d: Doc) => d.version, width: "5rem" }],
  },
  play: async ({ canvasElement }) => {
    const grid = within(canvasElement).getByRole("treegrid", { name: "Documents" });
    const names = within(grid).getAllByRole("button", { name: /^(Expand|Collapse) / }).map((b) => b.textContent);
    await expect(names[names.length - 1]).toBe("Aardvark");
    await expect(within(grid).queryByRole("button", { name: /Sort by/ })).not.toBeInTheDocument();
    await expect(within(grid).getByRole("columnheader", { name: "Name" })).not.toHaveAttribute("aria-sort");
  },
};

/** Without it (the default) the same folder sorts first, by name. */
export const SortedOrderPlacesThatFolderFirst: Story = {
  args: { extraFolders: ["Aardvark"] },
  play: async ({ canvasElement }) => {
    const grid = within(canvasElement).getByRole("treegrid", { name: "Documents" });
    const names = within(grid).getAllByRole("button", { name: /^(Expand|Collapse) / }).map((b) => b.textContent);
    await expect(names[0]).toBe("Aardvark");
  },
};

/** A column may draw a cell for a folder row as well as for an item row. */
export const AFolderRowCanCarryAColumnCell: Story = {
  args: {
    columns: [{ id: "count", header: "Count", render: (d: Doc) => `v${d.version}`, renderFolder: (n: FolderNode<Doc>) => `${n.count} inside`, width: "6rem" }],
  },
  play: async ({ canvasElement }) => {
    const grid = within(canvasElement).getByRole("treegrid", { name: "Documents" });
    await expect(within(grid).getAllByText(/inside$/).length).toBeGreaterThan(0);
    await expect(within(grid).getByText("2 inside")).toBeInTheDocument();
  },
};

/** An open folder with nothing in it can say so in the caller's words. */
export const EmptyFolderTextIsTheCallers: Story = {
  args: { extraFolders: ["Archive"], initiallyOpen: ["f:archive"], emptyFolderText: "Nothing filed yet." },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("Nothing filed yet.")).toBeInTheDocument();
  },
};

/** A record with children of its own is a folder that carries its record as `item`. */
function RecordFolderHost() {
  const record = (id: string): Doc => ({ id, title: id, folder: "", kind: "report", version: 1, note: "" });
  const nodes: FolderNode<Doc>[] = [{
    id: "parent", kind: "folder", name: "Parent", path: "parent", item: record("parent"), count: 1,
    children: [{ id: "child", kind: "item", name: "Child", path: "parent", item: record("child"), count: 0, children: [] }],
  }];
  const [chosen, setChosen] = useState("parent");
  return (
    <FolderTreeList
      nodes={nodes} label="Records" expanded={new Set(["parent"])} onToggle={() => {}} order="given" folderIcon={() => <FileText aria-hidden="true" />}
      itemView={() => ({ icon: <FileText />, iconLabel: "Record" })}
      isSelected={(d) => d.id === chosen} onOpenItem={(d) => setChosen(d.id)}
    />
  );
}

/** A folder that carries an `item` is outlined and marked selected like an item row; a folder without one is not selectable. */
export const AFolderThatCarriesAnItemCanBeTheSelectedRow: Story = {
  render: () => <RecordFolderHost />,
  play: async ({ canvasElement }) => {
    const grid = within(canvasElement).getByRole("treegrid", { name: "Records" });
    const rowOf = (name: string) => within(grid).getByText(name).closest<HTMLElement>('[role="row"]')!;
    await expect(rowOf("Parent")).toHaveAttribute("aria-selected", "true");
    await expect(rowOf("Parent")).toHaveClass("folder-tree-selected");
    await userEvent.click(within(grid).getByRole("button", { name: "Child" }));
    await expect(rowOf("Parent")).toHaveAttribute("aria-selected", "false");
    await expect(rowOf("Child")).toHaveAttribute("aria-selected", "true");
  },
};
