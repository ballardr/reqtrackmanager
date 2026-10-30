import type { Meta, StoryObj } from "@storybook/react-vite";
import * as Blockly from "blockly/core";
import { useState } from "react";
import { expect, screen, userEvent, waitFor, within } from "storybook/test";

import type { TreeProblem } from "../api/reportLayouts";
import { buildBlockCatalogue, buildFieldCatalogue, buildOutlineTree, buildWidgets } from "../testing/reportLayoutFixtures";
import { treeToWorkspaceState, workspaceStateToTree } from "../utils/reportLayoutBlockly";
import type { Tree } from "../utils/reportLayoutTree";
import { ReportLayoutBlocks } from "./ReportLayoutBlocks";

// The designer loads the catalogues once; building them on every render would redraw the workspace each time.
const BLOCKS = buildBlockCatalogue();
const CATALOGUE = buildFieldCatalogue();
const WIDGETS = buildWidgets();

/** Keeps the tree in state, as the designer does, and prints it so a story can read what an edit produced. */
function Harness({ initial, problems = [], readOnly = false, family = "document" }: {
  initial: Tree; problems?: TreeProblem[]; readOnly?: boolean; family?: "document" | "table";
}) {
  const [tree, setTree] = useState(initial);
  return (
    <>
      <ReportLayoutBlocks
        tree={tree} onChange={setTree} family={family} blocks={BLOCKS} catalogue={CATALOGUE}
        widgets={WIDGETS} problems={problems} readOnly={readOnly}
      />
      <pre data-testid="tree" hidden>{JSON.stringify(tree)}</pre>
    </>
  );
}

/** The block editor: a layout as Blockly blocks generated from the server's block schemas, with the selected block's form beside it. */
const meta: Meta<typeof Harness> = {
  title: "Components/ReportLayoutBlocks",
  component: Harness,
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

export const DrawsEachBlockWithItsShortFieldsInline: Story = {
  play: async () => {
    const ws = await workspaceOf();
    await waitFor(() => expect(ws.getAllBlocks(false).filter((b) => b.type !== "rl_root")).toHaveLength(4));
    const [first, second] = blocksOf(ws, "heading");
    // The heading's text and level sit on the block.
    await expect(first.getFieldValue("text")).toBe("Requirements of {{project_name}}");
    await expect(first.getFieldValue("level")).toBe("1");
    await expect(second.getFieldValue("level")).toBe("2");
    // The For each holds the nested heading and table in its Contents list.
    const each = blocksOf(ws, "each")[0];
    await expect(each.getInputTargetBlock("children")?.type).toBe("rl_heading");
    await expect(each.getFieldValue("as")).toBe("req");
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

export const EditingABlockFieldChangesTheTree: Story = {
  play: async ({ canvasElement }) => {
    const ws = await workspaceOf();
    const heading = blocksOf(ws, "heading")[0];
    heading.setFieldValue("New title", "text");
    await waitFor(() => expect(treeOf(canvasElement).nodes[0].text).toBe("New title"));
    // "Not set" removes an optional key rather than storing an empty string.
    heading.setFieldValue("", "level");
    await waitFor(() => expect(treeOf(canvasElement).nodes[0]).not.toHaveProperty("level"));
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
    await expect(names.slice(0, 5).map((n) => n?.trim())).toEqual(["Heading 1", "Heading 2", "Heading 3", "Text", "Table"]);
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
