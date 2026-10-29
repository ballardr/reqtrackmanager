import type { Meta, StoryObj } from "@storybook/react-vite";
import { FileText, Package } from "lucide-react";
import { useMemo, useState } from "react";
import { expect, userEvent, within } from "storybook/test";

import { buildFolderTree, type FolderNode } from "../utils/reportFolders";
import { FolderTreeList, type FolderTreeColumn } from "./FolderTreeList";

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

/** Hosts the list with its own open folders, so a story sees the chevrons and rows follow the clicks. */
function Host({
  docs = DOCS, columns, initiallyOpen = [], width, extraFolders = [], folderActions = false,
}: { docs?: Doc[]; columns?: FolderTreeColumn<Doc>[]; initiallyOpen?: string[]; width?: string; extraFolders?: string[]; folderActions?: boolean }) {
  const [open, setOpen] = useState(new Set(initiallyOpen));
  const [chosen, setChosen] = useState("");
  const tree = useMemo(() => {
    const nodes = buildFolderTree(docs, (d) => d.folder, (d) => d.title, (d) => d.id);
    const empty: FolderNode<Doc>[] = extraFolders.map((name) => ({ id: `f:${name.toLowerCase()}`, kind: "folder", name, path: name, children: [], count: 0 }));
    return [...nodes, ...empty];
  }, [docs, extraFolders]);
  return (
    <div style={width ? { width } : undefined}>
      <FolderTreeList
        nodes={tree} label="Documents" expanded={open}
        onToggle={(id, isOpen) => setOpen((c) => { const n = new Set(c); if (isOpen) n.add(id); else n.delete(id); return n; })}
        itemView={(d) => ({ icon: d.kind === "pack" ? <Package /> : <FileText />, iconLabel: d.kind === "pack" ? "Pack" : "Report", description: d.note })}
        isSelected={(d) => d.id === chosen} onOpenItem={(d) => setChosen(d.id)} columns={columns}
        folderBadge={(n) => String(n.count)}
        renderItemActions={(d) => <button type="button" className="btn" aria-label={`Star ${d.title}`}>★</button>}
        renderFolderActions={folderActions ? (n) => <button type="button" className="btn" aria-label={`Actions for the folder ${n.name}`}>⋮</button> : undefined}
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

/** At a narrow width a long name wraps inside its cell instead of widening the list. */
export const NarrowWidthWrapsLongNames: Story = {
  args: { width: "320px", columns: COLUMNS },
  play: async ({ canvasElement }) => {
    const grid = within(canvasElement).getByRole("treegrid", { name: "Documents" });
    await expect(grid.scrollWidth).toBeLessThanOrEqual(grid.clientWidth);
    const long = within(grid).getByRole("button", { name: /^A report whose title/ });
    await expect(long.getBoundingClientRect().height).toBeGreaterThan(30);
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

export const LightTheme: Story = { ...DeepFoldersIndent, globals: { theme: "light" } };
export const DarkTheme: Story = { ...DeepFoldersIndent, globals: { theme: "dark" } };
