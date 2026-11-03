import type { Meta, StoryObj } from "@storybook/react-vite";
import * as Blockly from "blockly/core";
import { useState } from "react";
import { expect, screen, userEvent, waitFor, within } from "storybook/test";

import type { TreeProblem } from "../api/reportLayouts";
import {
  buildBlockCatalogue, buildFieldCatalogue, buildImageLibrary, buildLayoutApi, buildOutlineTree, buildWidgets,
} from "../testing/reportLayoutFixtures";
import { buildUser, withStatefulAuth } from "../testing/storybook-helpers";
import { chooseSnippetMenuItem, snippetMenuItem } from "../testing/reportSnippetMenuHelpers";
import { treeToWorkspaceState, workspaceStateToTree } from "../utils/reportLayoutBlockly";
import type { Tree } from "../utils/reportLayoutTree";
import { ReportLayoutBlocks } from "./ReportLayoutBlocks";

// The designer loads the catalogues once; building them on every render would redraw the workspace each time.
const BLOCKS = buildBlockCatalogue();
const CATALOGUE = buildFieldCatalogue();
const WIDGETS = buildWidgets();
const SNIPPET_API = buildLayoutApi();
const IMAGES = { library: buildImageLibrary(), scope: "project" as const };

/** Keeps the tree in state, as the designer does, and prints it so a story can read what an edit produced. */
function Harness({ initial, problems = [], readOnly = false, family = "document", withSnippets = false }: {
  initial: Tree; problems?: TreeProblem[]; readOnly?: boolean; family?: "document" | "table"; withSnippets?: boolean;
}) {
  const [tree, setTree] = useState(initial);
  const [notice, setNotice] = useState<string | null>(null);
  const [inspectorHost, setInspectorHost] = useState<HTMLElement | null>(null);
  const [inspected, setInspected] = useState(0);
  return (
    <>
      <ReportLayoutBlocks
        tree={tree} onChange={setTree} family={family} blocks={BLOCKS} catalogue={CATALOGUE}
        widgets={WIDGETS} problems={problems} readOnly={readOnly}
        inspectorHost={inspectorHost} onInspect={() => setInspected((count) => count + 1)}
        images={withSnippets ? IMAGES : undefined}
        snippets={withSnippets ? {
          api: SNIPPET_API, onInserted: (n) => setNotice(`${n.name}: ${n.changes.join(" ")}`),
          onSave: (selection, label) => setNotice(`save ${JSON.stringify(selection)} ${label}`),
        } : undefined}
      />
      {/* Where the designer's side panel would be: the selected block's form is drawn here. */}
      <div ref={setInspectorHost} className="card" />
      <pre data-testid="inspected" hidden>{inspected}</pre>
      <pre data-testid="tree" hidden>{JSON.stringify(tree)}</pre>
      <pre data-testid="notice" hidden>{notice}</pre>
    </>
  );
}

/** The block editor: a layout as Blockly blocks generated from the server's block schemas, with the selected block's form beside it. */
const meta: Meta<typeof Harness> = {
  title: "Components/ReportLayoutBlocks",
  component: Harness,
  decorators: [withStatefulAuth(buildUser({ ui_preferences: {} }))],
  args: { initial: buildOutlineTree() },
};
export default meta;

type Story = StoryObj<typeof Harness>;

const treeOf = (canvasElement: HTMLElement): { nodes: Record<string, unknown>[] } & Tree =>
  JSON.parse(within(canvasElement).getByTestId("tree").textContent ?? "{}");

/** The editor's workspace, once Blockly has drawn it. */
async function workspaceOf(): Promise<Blockly.WorkspaceSvg> {
  await waitFor(() => expect(Blockly.getMainWorkspace()).toBeTruthy());
  return Blockly.getMainWorkspace() as Blockly.WorkspaceSvg;
}

/** The layout's blocks (the root excluded) of a type. */
const blocksOf = (ws: Blockly.WorkspaceSvg, type: string) => ws.getAllBlocks(false).filter((b) => b.type === `rl_${type}`) as Blockly.BlockSvg[];

export const DrawsEachBlockWithAReadOnlySummary: Story = {
  play: async () => {
    const ws = await workspaceOf();
    await waitFor(() => expect(ws.getAllBlocks(false).filter((b) => b.type !== "rl_root")).toHaveLength(4));
    const [first, second] = blocksOf(ws, "heading");
    // The heading's words and level are only summarised on the block; the editor panel edits them.
    await expect(first.getFieldValue("_summary")).toBe("level 1 · Requirements of {{project_name}}");
    await expect(second.getFieldValue("_summary")).toContain("level 2");
    await expect(first.getFieldValue("text")).toBeNull();
    await expect(first.getFieldValue("level")).toBeNull();
    // The For each holds the nested heading and table in its Contents list and names its alias in the summary.
    const each = blocksOf(ws, "each")[0];
    await expect(each.getInputTargetBlock("children")?.type).toBe("rl_heading");
    await expect(each.getFieldValue("_summary")).toContain("as req");
    await expect(each.getFieldValue("as")).toBeNull();
  },
};

/** Opening a layout must not rewrite it: tree to blocks and back is the identity, including keys the editor does not draw. */
export const TreeToBlocksAndBackIsTheIdentity: Story = {
  play: async () => {
    const odd: Tree = {
      ...buildOutlineTree(),
      nodes: [
        { type: "heading", text: "A", level: 9, futureKey: { nested: [1, 2] } },
        { type: "if", when: { field: "x" }, children: [], else_children: [{ type: "page_break" }] },
        { type: "each", source: {}, children: [] },
        { type: "from_a_module", anything: ["goes"] },
      ],
    };
    const types = BLOCKS.blocks;
    const back = workspaceStateToTree(odd, treeToWorkspaceState(odd, types), types);
    await expect(back).toEqual(odd);
  },
};

/** Every value, including the short ones that used to sit on the block, is edited in the block editor and reaches the tree. */
export const EditingABlockFieldInTheEditorChangesTheTree: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const ws = await workspaceOf();
    const heading = blocksOf(ws, "heading")[0];
    Blockly.common.setSelected(heading);
    const inspector = await canvas.findByTestId("block-inspector");
    const box = await within(inspector).findByRole("textbox", { name: "Heading" });
    await userEvent.clear(box);
    await userEvent.type(box, "New title");
    await waitFor(() => expect(treeOf(canvasElement).nodes[0].text).toBe("New title"));
    await waitFor(() => expect(heading.getFieldValue("_summary")).toBe("level 1 · New title"));
    const level = within(inspector).getByRole("spinbutton", { name: "Level" });
    await userEvent.clear(level);
    await userEvent.type(level, "3");
    await waitFor(() => expect(treeOf(canvasElement).nodes[0].level).toBe(3));
  },
};

/** A block's label replaces the start of its text on the block, with the name beside it; the Label field in the editor sets it and a name can hold hyphens. */
export const ALabelShowsOnTheBlockWithItsNameAndIsEditedInTheEditor: Story = {
  args: {
    initial: {
      ...buildOutlineTree(),
      nodes: [{
        type: "each", source: { record_type: "requirement" }, as: "open-reqs", label: "Open requirements",
        children: [{ type: "table", source: { record_type: "pain_point", linked_from: "open-reqs" }, columns: [{ field: "code" }] }],
      }],
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const ws = await workspaceOf();
    const each = blocksOf(ws, "each")[0];
    await expect(each.getFieldValue("_summary")).toBe("Open requirements · as open-reqs");
    // The table inside names the labelled block by label and name in its "Linked from" picker.
    Blockly.common.setSelected(blocksOf(ws, "table")[0]);
    const inspector = await canvas.findByTestId("block-inspector");
    const from = (await within(inspector).findByRole("combobox", { name: "Linked from" })) as HTMLSelectElement;
    await expect(Array.from(from.options).map((o) => o.textContent)).toContain("Open requirements (open-reqs)");
    // Setting a label on the table through the Label field reaches the tree and the block; emptying it removes the key.
    const label = within(inspector).getByRole("textbox", { name: "Label" });
    await userEvent.type(label, "Pain points");
    await waitFor(() => expect(treeOf(canvasElement).nodes[0]).toMatchObject({ children: [{ label: "Pain points" }] }));
    await waitFor(() => expect(blocksOf(ws, "table")[0].getFieldValue("_summary")).toBe("Pain points"));
    await userEvent.clear(label);
    await waitFor(() => expect(treeOf(canvasElement).nodes[0].children).toEqual([expect.not.objectContaining({ label: expect.anything() })]));
  },
};

export const SelectingABlockShowsItsOtherSettingsInTheInspector: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const ws = await workspaceOf();
    await expect(canvas.getByText("Select a block to edit its settings.")).toBeInTheDocument();
    Blockly.common.setSelected(blocksOf(ws, "table")[0]);
    const inspector = await canvas.findByTestId("block-inspector");
    // The table's records and columns are edited here, with the shared editors.
    await expect(within(inspector).getByText("Columns")).toBeInTheDocument();
    await expect(within(inspector).getByText("Records")).toBeInTheDocument();
  },
};

/** An edit in the inspector is patched into the block in place: the block and its summary stay and the inspector keeps showing it. */
export const InspectorEditsReachTheBlockWithoutRedrawing: Story = {
  args: {
    initial: { schema_version: 1, family: "document", nodes: [{ type: "text", text: "Hello" }, { type: "page_break" }] },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const ws = await workspaceOf();
    const block = blocksOf(ws, "text")[0];
    await expect(block.getFieldValue("_summary")).toBe("Hello");
    Blockly.common.setSelected(block);
    const inspector = await canvas.findByTestId("block-inspector");
    const box = within(inspector).getByRole("textbox", { name: "Text" });
    await userEvent.type(box, " world");
    await waitFor(() => expect(treeOf(canvasElement).nodes[0].text).toBe("Hello world"));
    // The same block object is still there, now showing the new start of the text, and still selected.
    await waitFor(() => expect(block.getFieldValue("_summary")).toBe("Hello world"));
    await expect(blocksOf(ws, "text")[0]).toBe(block);
    // Typing in the inspector took focus from the workspace, yet the inspector still shows the block.
    await expect(within(inspector).getByRole("textbox", { name: "Text" })).toHaveValue("Hello world");
  },
};

/** A section is a block with a container; its page style shows on the block and is chosen from the layout's page styles. */
export const ASectionShowsItsPageStyleAndChoosesFromTheLayoutsStyles: Story = {
  args: {
    initial: {
      schema_version: 1, family: "document", page_styles: [{ name: "Wide tables", page_size: "A3" }, { name: "Narrow" }],
      nodes: [{ type: "section", page_style: "Wide tables", children: [{ type: "text", text: "Inside" }] }],
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const ws = await workspaceOf();
    const section = blocksOf(ws, "section")[0];
    await expect(section.getFieldValue("_summary")).toBe("Wide tables");
    Blockly.common.setSelected(section);
    const inspector = await canvas.findByTestId("block-inspector");
    await userEvent.selectOptions(within(inspector).getByRole("combobox", { name: "Page style" }), "Narrow");
    await waitFor(() => expect(treeOf(canvasElement).nodes[0].page_style).toBe("Narrow"));
  },
};

/** An At page bottom block is a container: blocks added inside it stay inside it in the tree. */
export const AnAtPageBottomBlockHoldsItsContents: Story = {
  args: {
    initial: {
      schema_version: 1, family: "document",
      nodes: [{ type: "bottom", children: [{ type: "text", text: "Signed" }] }],
    },
  },
  play: async ({ canvasElement }) => {
    const ws = await workspaceOf();
    await waitFor(() => expect(blocksOf(ws, "bottom")).toHaveLength(1));
    await waitFor(() => expect(blocksOf(ws, "text")).toHaveLength(1));
    expect(treeOf(canvasElement).nodes[0]).toEqual({ type: "bottom", children: [{ type: "text", text: "Signed" }] });
  },
};

/** Adds a block of `name` from the Add block menu. */
async function addFromMenu(canvas: ReturnType<typeof within>, name: string) {
  await userEvent.click(canvas.getByRole("button", { name: "Add block" }));
  await userEvent.click(await screen.findByRole("menuitem", { name }));
}

export const AddBlockWithNothingSelectedAppendsToTheLayoutAndSaysSo: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const ws = await workspaceOf();
    await expect(canvas.getByText("Adding at the end of the layout")).toBeInTheDocument();
    await addFromMenu(canvas, "Page break");
    await waitFor(() => expect(treeOf(canvasElement).nodes.map((n) => n.type)).toEqual(["heading", "each", "page_break"]));
    await waitFor(() => expect(blocksOf(ws, "page_break")).toHaveLength(1));
    // The new block is selected, so its settings are at hand, and the inspector is titled by it.
    await waitFor(() => expect(Blockly.common.getSelected()).toBe(blocksOf(ws, "page_break")[0]));
    await expect(await canvas.findByTestId("block-inspector")).toHaveTextContent("Page break block");
  },
};

/** The table of contents is among the blocks Add block offers, and adds a block with its own settings in the inspector. */
export const AddBlockOffersATableOfContents: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const ws = await workspaceOf();
    await addFromMenu(canvas, "Table of contents");
    await waitFor(() => expect(treeOf(canvasElement).nodes.map((n) => n.type)).toEqual(["heading", "each", "contents"]));
    await waitFor(() => expect(blocksOf(ws, "contents")).toHaveLength(1));
    await expect(await canvas.findByTestId("block-inspector")).toHaveTextContent("Table of contents block");
    await expect(await canvas.findByRole("spinbutton", { name: "Levels" })).toBeInTheDocument();
  },
};

export const AddBlockWithALeafSelectedAddsAfterIt: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const ws = await workspaceOf();
    Blockly.common.setSelected(blocksOf(ws, "heading")[0]);
    const where = await canvas.findByRole("combobox", { name: "Where to add the block" });
    // A heading holds no blocks, so the only places are after it and the end of the layout; after is the default.
    await expect(where).toHaveDisplayValue(/^Adding after: Heading – Requirements/);
    await expect(within(where).getAllByRole("option")).toHaveLength(2);
    await addFromMenu(canvas, "Page break");
    await waitFor(() => expect(treeOf(canvasElement).nodes.map((n) => n.type)).toEqual(["heading", "page_break", "each"]));
    await waitFor(() => expect(Blockly.common.getSelected()).toBe(blocksOf(ws, "page_break")[0]));
  },
};

export const AddBlockWithAContainerSelectedAddsInsideByDefaultOrAfterIt: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const ws = await workspaceOf();
    Blockly.common.setSelected(blocksOf(ws, "each")[0]);
    const where = await canvas.findByRole("combobox", { name: "Where to add the block" });
    await expect(where).toHaveDisplayValue(/^Adding inside: .* – Contents$/);
    await addFromMenu(canvas, "Equation");
    await waitFor(() => expect((treeOf(canvasElement).nodes[1].children as { type: string }[]).map((n) => n.type)).toEqual(["heading", "table", "equation"]));
    // The new block becomes the selection; then select the container again and choose After.
    await waitFor(() => expect(Blockly.common.getSelected()).toBe(blocksOf(ws, "equation")[0]));
    Blockly.common.setSelected(blocksOf(ws, "each")[0]);
    await waitFor(() => expect(canvas.getByRole("combobox", { name: "Where to add the block" })).toHaveDisplayValue(/^Adding inside: /));
    const after = within(canvas.getByRole("combobox", { name: "Where to add the block" })).getAllByRole("option").find((o) => /^Adding after: /.test(o.textContent ?? ""));
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Where to add the block" }), after as HTMLOptionElement);
    await addFromMenu(canvas, "Page break");
    await waitFor(() => expect(treeOf(canvasElement).nodes.map((n) => n.type)).toEqual(["heading", "each", "page_break"]));
    await expect((treeOf(canvasElement).nodes[1].children as unknown[]).length).toBe(3);
  },
};

const GROUPED: Tree = {
  nodes: [
    { type: "group", source: { record_type: "requirement" }, by: "status", as: "by-status", children: [] },
    { type: "group", source: {}, by: "", as: "unfinished", children: [] },
  ],
};

/** A new record block inside a group reads the group's records; elsewhere, or under a group with no records, it starts empty. */
export const ANewRecordBlockInAGroupStartsOnTheGroup: Story = {
  args: { initial: GROUPED },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const ws = await workspaceOf();
    Blockly.common.setSelected(blocksOf(ws, "group")[0]);
    await waitFor(() => expect(canvas.getByRole("combobox", { name: "Where to add the block" })).toHaveDisplayValue(/^Adding inside: /));
    await addFromMenu(canvas, "Table (records)");
    await waitFor(() => expect((treeOf(canvasElement).nodes[0].children as Record<string, unknown>[])[0]).toMatchObject({ type: "table", source: { group: "by-status" } }));
    // A group that has no record set yet gives nothing to read, so the block starts as today.
    Blockly.common.setSelected(blocksOf(ws, "group")[1]);
    await waitFor(() => expect(Blockly.common.getSelected()).toBe(blocksOf(ws, "group")[1]));
    await waitFor(() => expect(canvas.getByRole("combobox", { name: "Where to add the block" })).toHaveDisplayValue(/^Adding inside: /));
    await addFromMenu(canvas, "For each record");
    await waitFor(() => expect((treeOf(canvasElement).nodes[1].children as Record<string, unknown>[])[0]).toMatchObject({ type: "each", source: {} }));
  },
};

export const ANewRecordBlockOutsideAnyGroupIsUnchanged: Story = {
  args: { initial: GROUPED },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await workspaceOf();
    await addFromMenu(canvas, "Table (records)");
    await waitFor(() => expect(treeOf(canvasElement).nodes[2]).toMatchObject({ type: "table", source: {} }));
  },
};

/** The addition is made in the workspace, so the editor's own undo takes it back like a dragged block. */
export const AnAddedBlockCanBeUndone: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const ws = await workspaceOf();
    await addFromMenu(canvas, "Page break");
    await waitFor(() => expect(treeOf(canvasElement).nodes).toHaveLength(3));
    ws.undo(false);
    await waitFor(() => expect(treeOf(canvasElement).nodes.map((n) => n.type)).toEqual(["heading", "each"]));
    // The block is gone from the canvas too, not left loose beside the layout.
    await waitFor(() => expect(blocksOf(ws, "page_break")).toHaveLength(0));
  },
};

export const TheMostUsedBlocksAreListedFirst: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await workspaceOf();
    await userEvent.click(canvas.getByRole("button", { name: "Add block" }));
    const names = (await screen.findAllByRole("menuitem")).map((item) => item.textContent);
    await expect(names.slice(0, 5).map((n) => n?.trim())).toEqual(["Heading 1", "Heading 2", "Heading 3", "Text", "Table (records)"]);
    await expect(screen.getByText("Most used")).toBeInTheDocument();
    await expect(screen.getByText("Other blocks")).toBeInTheDocument();
  },
};

export const AddingInsideAContainerUsesTheInspector: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const ws = await workspaceOf();
    Blockly.common.setSelected(blocksOf(ws, "each")[0]);
    const inspector = await canvas.findByTestId("block-inspector");
    await userEvent.click(within(inspector).getByRole("button", { name: "Add to Contents" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Equation" }));
    await waitFor(() => expect((treeOf(canvasElement).nodes[1].children as { type: string }[]).map((n) => n.type)).toEqual(["heading", "table", "equation"]));
    // The structure changed, so the workspace was redrawn from the tree.
    await waitFor(() => expect(blocksOf(ws, "equation")).toHaveLength(1));
  },
};

export const HeadingsAreOfferedByLevel: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await workspaceOf();
    await userEvent.click(canvas.getByRole("button", { name: "Add block" }));
    await expect(await screen.findByRole("menuitem", { name: "Heading 1" })).toBeInTheDocument();
    await expect(screen.getByRole("menuitem", { name: "Heading 3" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("menuitem", { name: "Heading 3" }));
    await waitFor(() => expect(treeOf(canvasElement).nodes[2].level).toBe(3));
  },
};

export const ProblemsShowAsWarningsAndInTheInspector: Story = {
  args: { problems: [{ path: "nodes[0].text", message: "Must not be empty." }] },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const ws = await workspaceOf();
    const heading = blocksOf(ws, "heading")[0];
    await waitFor(() => expect(heading.getIcon(Blockly.icons.IconType.WARNING)).toBeTruthy());
    Blockly.common.setSelected(heading);
    await expect(await canvas.findByText("Must not be empty.")).toBeInTheDocument();
  },
};

/** A block dropped outside the layout is not part of it; the editor says so rather than losing it silently. */
export const ABlockOutsideTheLayoutIsCounted: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const ws = await workspaceOf();
    const loose = ws.newBlock("rl_page_break") as Blockly.BlockSvg;
    loose.initSvg();
    loose.render();
    loose.moveBy(400, 200);
    await expect(await canvas.findByText(/1 block is outside the layout/)).toBeInTheDocument();
    await expect(treeOf(canvasElement).nodes).toHaveLength(2);
  },
};

export const ASharedLayoutIsReadOnly: Story = {
  args: { readOnly: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const ws = await workspaceOf();
    await expect(ws.options.readOnly).toBe(true);
    await expect(canvas.queryByRole("button", { name: "Add block" })).not.toBeInTheDocument();
    await expect(canvas.getByText(/shared from elsewhere/)).toBeInTheDocument();
  },
};

/** Only the types for the layout's family are in the palette. */
export const ATableLayoutOffersOnlySheets: Story = {
  args: { initial: { schema_version: 1, family: "table", nodes: [] }, family: "table" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await workspaceOf();
    await userEvent.click(canvas.getByRole("button", { name: "Add block" }));
    await expect(await screen.findByRole("menuitem", { name: "Sheet" })).toBeInTheDocument();
    await expect(screen.queryByRole("menuitem", { name: "Heading 1" })).not.toBeInTheDocument();
  },
};

/** Opens Insert snippet, chooses a snippet and inserts it. */
async function insertSnippet(canvasElement: HTMLElement, name: string, choose?: (d: ReturnType<typeof within>) => Promise<void>) {
  await chooseSnippetMenuItem(canvasElement, "Insert snippet");
  const d = within(await screen.findByRole("dialog", { name: "Insert snippet" }));
  await userEvent.click(await d.findByRole("button", { name: `Select ${name}` }));
  await choose?.(d);
  await userEvent.click(d.getByRole("button", { name: "Insert" }));
  await waitFor(() => expect(screen.queryByRole("dialog", { name: "Insert snippet" })).not.toBeInTheDocument());
}

/** The snippet's blocks land at the place the toolbar states, and the author is told what was done. */
export const InsertSnippetPutsItsBlocksAtTheStatedPlace: Story = {
  args: { withSnippets: true },
  play: async ({ canvasElement }) => {
    await workspaceOf();
    await expect(await within(canvasElement).findByText("Adding at the end of the layout")).toBeInTheDocument();
    await insertSnippet(canvasElement, "Cover page");
    await waitFor(() => expect(treeOf(canvasElement).nodes).toHaveLength(5));
    await expect(treeOf(canvasElement).nodes.slice(2).map((n) => n.type)).toEqual(["heading", "text", "page_break"]);
    await expect(within(canvasElement).getByTestId("notice")).toHaveTextContent("Cover page: Inserted 3 blocks at nodes[2].");
  },
};

/** A cover page or a logo belongs at the start, which Add block's places do not offer, so the snippet dialog does. */
export const InsertSnippetCanGoAtTheStartOfTheLayout: Story = {
  args: { withSnippets: true },
  play: async ({ canvasElement }) => {
    await workspaceOf();
    await insertSnippet(canvasElement, "Cover page", async (d) => {
      await userEvent.selectOptions(d.getByRole("combobox", { name: "Where to insert the snippet" }), "Inserting at the start of the layout");
    });
    await waitFor(() => expect(treeOf(canvasElement).nodes.map((n) => n.type)).toEqual(["heading", "text", "page_break", "heading", "each"]));
  },
};

/** One Ctrl+Z removes every block the snippet added, not one at a time. */
export const OneUndoRemovesTheWholeSnippet: Story = {
  args: { withSnippets: true },
  play: async ({ canvasElement }) => {
    const ws = await workspaceOf();
    await insertSnippet(canvasElement, "Cover page");
    await waitFor(() => expect(treeOf(canvasElement).nodes).toHaveLength(5));
    ws.undo(false);
    await waitFor(() => expect(treeOf(canvasElement).nodes).toHaveLength(2));
  },
};

/** A snippet's page style is part of the layout the moment it is inserted; undoing the blocks leaves it, and nothing else, behind. */
export const ARootChangeTravelsWithTheBlocks: Story = {
  args: { withSnippets: true },
  play: async ({ canvasElement }) => {
    const ws = await workspaceOf();
    await insertSnippet(canvasElement, "Logo, top right of the first page", async (d) => {
      await userEvent.click(d.getByRole("button", { name: "Choose image…" }));
      const library = within(await screen.findByRole("dialog", { name: "Image library" }));
      await userEvent.click(await library.findByRole("button", { name: "Select site-logo.png" }));
      await userEvent.click(library.getByRole("button", { name: "Use image" }));
    });
    await waitFor(() => expect(treeOf(canvasElement).nodes).toHaveLength(3));
    await expect(treeOf(canvasElement).page_styles).toEqual([{ name: "Cover" }]);
    ws.undo(false);
    await waitFor(() => expect(treeOf(canvasElement).nodes).toHaveLength(2));
    await expect(treeOf(canvasElement).page_styles).toEqual([{ name: "Cover" }]);
  },
};

/** With a block selected the snippet goes after it, in the place the toolbar names. */
export const InsertSnippetFollowsTheSelectedBlock: Story = {
  args: { withSnippets: true },
  play: async ({ canvasElement }) => {
    const ws = await workspaceOf();
    const [first] = blocksOf(ws, "heading");
    Blockly.common.setSelected(first);
    await waitFor(() => expect(within(canvasElement).getByRole("combobox", { name: "Where to add the block" })).toBeInTheDocument());
    const where = within(canvasElement).getByRole("combobox", { name: "Where to add the block" });
    await userEvent.selectOptions(where, within(where).getByRole("option", { name: /Adding after: Heading/ }));
    await insertSnippet(canvasElement, "Cover page");
    await waitFor(() => expect(treeOf(canvasElement).nodes).toHaveLength(5));
    await expect(treeOf(canvasElement).nodes.map((n) => n.type)).toEqual(["heading", "heading", "text", "page_break", "each"]);
  },
};

/** A layout shown read-only offers no Insert snippet, and neither does a view with no snippet calls. */
export const NoInsertSnippetWhenReadOnlyOrWithoutCalls: Story = {
  args: { withSnippets: true, readOnly: true },
  play: async ({ canvasElement }) => {
    await workspaceOf();
    await expect(within(canvasElement).queryByRole("button", { name: "Snippets" })).not.toBeInTheDocument();
  },
};

/** Save as snippet saves the selected block, with everything inside it, as a run of one in its own list. */
export const SaveAsSnippetNeedsASelectedBlockAndNamesIt: Story = {
  args: { withSnippets: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const ws = await workspaceOf();
    const disabled = await snippetMenuItem(canvasElement, "Save as snippet");
    await expect(disabled).toBeDisabled();
    await expect(disabled).toHaveAttribute("title", "Select a block first: it is saved with everything inside it.");
    await userEvent.keyboard("{Escape}");
    const [, nested] = blocksOf(ws, "heading");
    Blockly.common.setSelected(nested);
    await canvas.findByTestId("block-inspector");
    await chooseSnippetMenuItem(canvasElement, "Save as snippet");
    await waitFor(() => expect(canvas.getByTestId("notice")).toHaveTextContent('save {"container":"nodes[1].children","start":0,"count":1} Saving Heading'));
  },
};

export const ASharedLayoutOffersNoSaveAsSnippet: Story = {
  args: { withSnippets: true, readOnly: true },
  play: async ({ canvasElement }) => {
    await workspaceOf();
    await expect(within(canvasElement).queryByRole("button", { name: "Snippets" })).not.toBeInTheDocument();
  },
};

/** The layout's own settings are not stacked above the blocks: they open in the block editor when the layout block is selected. */
export const LayoutSettingsOpenFromTheLayoutBlock: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const ws = await workspaceOf();
    await expect(canvas.queryByText("Layout settings")).not.toBeInTheDocument();
    Blockly.common.setSelected(ws.getTopBlocks(false).find((b) => b.type === "rl_root") as Blockly.BlockSvg);
    const inspector = await canvas.findByTestId("layout-inspector");
    await userEvent.selectOptions(within(inspector).getByRole("combobox", { name: "Page orientation" }), "landscape");
    await waitFor(() => expect(treeOf(canvasElement).orientation).toBe("landscape"));
    // Selecting a block takes the inspector back to that block.
    Blockly.common.setSelected(blocksOf(ws, "table")[0]);
    await canvas.findByTestId("block-inspector");
    await expect(canvas.queryByTestId("layout-inspector")).not.toBeInTheDocument();
  },
};

/** The caller is told when the inspector has something new to show, so a tabbed panel can bring it forward. */
export const SelectingABlockOrOpeningSettingsTellsTheCaller: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const ws = await workspaceOf();
    const count = () => Number(canvas.getByTestId("inspected").textContent);
    const before = count();
    Blockly.common.setSelected(blocksOf(ws, "heading")[0]);
    await waitFor(() => expect(count()).toBeGreaterThan(before));
    const afterBlock = count();
    Blockly.common.setSelected(ws.getTopBlocks(false).find((b) => b.type === "rl_root") as Blockly.BlockSvg);
    await waitFor(() => expect(count()).toBeGreaterThan(afterBlock));
  },
};

/** A problem with a layout setting is a warning on the layout block, and the settings list it against the setting. */
export const AProblemInTheLayoutSettingsIsAWarningOnTheLayoutBlock: Story = {
  args: { problems: [{ path: "variables[0].name", message: "Must be lower-case letters." }] },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const ws = await workspaceOf();
    const root = ws.getTopBlocks(false).find((b) => b.type === "rl_root") as Blockly.BlockSvg;
    await waitFor(() => expect(root.getIcon(Blockly.icons.IconType.WARNING)).toBeTruthy());
    Blockly.common.setSelected(root);
    await expect(await canvas.findByText("Must be lower-case letters.")).toBeVisible();
  },
};

/** The instructions are one (?) away: not in the page until it is opened, reachable by keyboard, closed by Escape. */
export const TheInstructionsAreBehindAHelpButton: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await workspaceOf();
    await expect(canvas.queryByText(/Drag a block on the canvas/)).not.toBeInTheDocument();
    const help = canvas.getByRole("button", { name: "Help: Using the block editor" });
    help.focus();
    await expect(await screen.findByRole("tooltip", { hidden: true })).toHaveTextContent(/Drag a block on the canvas/);
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("tooltip", { hidden: true })).not.toBeInTheDocument());
  },
};

const nextFrame = () => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));

/**
 * Drags `block` with a plain pointer (no modifier key) so its previous connection lands on `target`, as Blockly's own
 * gesture does: start, move, end. The target is read after the drag starts, because the stack closes up behind the block.
 */
async function dragBlockTo(ws: Blockly.WorkspaceSvg, block: Blockly.BlockSvg, target: () => Blockly.RenderedConnection): Promise<void> {
  const dragger = new Blockly.dragging.Dragger(block);
  const from = { x: block.previousConnection!.x, y: block.previousConnection!.y };
  dragger.onDragStart(new PointerEvent("pointerdown"));
  await nextFrame();
  const to = target();
  const delta = new Blockly.utils.Coordinate((to.x - from.x) * ws.scale, (to.y - from.y) * ws.scale);
  dragger.onDrag(new PointerEvent("pointermove"), delta);
  await nextFrame();
  dragger.onDragEnd(new PointerEvent("pointerup"));
  await nextFrame();
}

const FOUR: Tree = {
  nodes: [
    { type: "heading", text: "A", level: 1 },
    { type: "heading", text: "B", level: 1 },
    { type: "heading", text: "C", level: 1 },
    { type: "heading", text: "D", level: 1 },
  ],
};

const headings = (canvasElement: HTMLElement) => treeOf(canvasElement).nodes.map((n) => n.text);

/** A plain drag moves the block that was grabbed; the blocks below it stay and close up. */
export const DraggingABlockMovesOnlyThatBlock: Story = {
  args: { initial: FOUR },
  play: async ({ canvasElement }) => {
    const ws = await workspaceOf();
    const [, b, , d] = blocksOf(ws, "heading");
    await dragBlockTo(ws, b, () => d.nextConnection as Blockly.RenderedConnection);
    await waitFor(() => expect(headings(canvasElement)).toEqual(["A", "C", "D", "B"]));
  },
};

/** One Ctrl+Z puts the block back with the stack as it was. */
export const ADragIsOneUndoStep: Story = {
  args: { initial: FOUR },
  play: async ({ canvasElement }) => {
    const ws = await workspaceOf();
    const [, b, , d] = blocksOf(ws, "heading");
    await dragBlockTo(ws, b, () => d.nextConnection as Blockly.RenderedConnection);
    await waitFor(() => expect(headings(canvasElement)).toEqual(["A", "C", "D", "B"]));
    ws.undo(false);
    await waitFor(() => expect(headings(canvasElement)).toEqual(["A", "B", "C", "D"]));
  },
};

/** The last block has nothing below it; dragging it up still moves just it. */
export const DraggingTheLastBlockMovesIt: Story = {
  args: { initial: FOUR },
  play: async ({ canvasElement }) => {
    const ws = await workspaceOf();
    const [a, , , d] = blocksOf(ws, "heading");
    await dragBlockTo(ws, d, () => a.nextConnection as Blockly.RenderedConnection);
    await waitFor(() => expect(headings(canvasElement)).toEqual(["A", "D", "B", "C"]));
  },
};

/** A block that holds others takes its contents with it, and only its own followers stay behind. */
export const DraggingAContainerTakesItsContents: Story = {
  args: {
    initial: {
      nodes: [
        { type: "group", source: {}, by: "", as: "g", children: [{ type: "heading", text: "Inside", level: 2 }] },
        { type: "heading", text: "After", level: 1 },
        { type: "heading", text: "Last", level: 1 },
      ],
    },
  },
  play: async ({ canvasElement }) => {
    const ws = await workspaceOf();
    const group = blocksOf(ws, "group")[0];
    const last = blocksOf(ws, "heading").find((h) => h.getFieldValue("_summary")?.includes("Last"))!;
    await dragBlockTo(ws, group, () => last.nextConnection as Blockly.RenderedConnection);
    await waitFor(() => expect(treeOf(canvasElement).nodes.map((n) => n.type)).toEqual(["heading", "heading", "group"]));
    await expect((treeOf(canvasElement).nodes[2].children as { text: string }[]).map((n) => n.text)).toEqual(["Inside"]);
  },
};

/** A block can be dropped inside a container, from the middle of a list. */
export const DraggingABlockIntoAContainer: Story = {
  args: {
    initial: {
      nodes: [
        { type: "group", source: {}, by: "", as: "g", children: [] },
        { type: "heading", text: "Moves", level: 1 },
        { type: "heading", text: "Stays", level: 1 },
      ],
    },
  },
  play: async ({ canvasElement }) => {
    const ws = await workspaceOf();
    const group = blocksOf(ws, "group")[0];
    const moves = blocksOf(ws, "heading")[0];
    await dragBlockTo(ws, moves, () => group.getInput("children")!.connection as Blockly.RenderedConnection);
    await waitFor(() => expect(treeOf(canvasElement).nodes.map((n) => n.type)).toEqual(["group", "heading"]));
    await expect((treeOf(canvasElement).nodes[0].children as { text: string }[]).map((n) => n.text)).toEqual(["Moves"]);
    await expect(treeOf(canvasElement).nodes[1].text).toBe("Stays");
  },
};
