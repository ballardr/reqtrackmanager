import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, screen, userEvent, waitFor, within } from "storybook/test";

import type { TreeProblem } from "../api/reportLayouts";
import { buildBlockCatalogue, buildFieldCatalogue, buildOutlineTree, buildWidgets } from "../testing/reportLayoutFixtures";
import type { Tree } from "../utils/reportLayoutTree";
import { ReportLayoutOutline } from "./ReportLayoutOutline";

/** Keeps the tree in state, as the designer does, and prints it so a story can read what an edit produced. */
function Harness({ initial, problems = [], readOnly = false, family = "document" }: {
  initial: Tree; problems?: TreeProblem[]; readOnly?: boolean; family?: "document" | "table";
}) {
  const [tree, setTree] = useState(initial);
  return (
    <>
      <ReportLayoutOutline
        tree={tree} onChange={setTree} family={family} blocks={buildBlockCatalogue()} catalogue={buildFieldCatalogue()}
        widgets={buildWidgets()} problems={problems} readOnly={readOnly}
      />
      <pre data-testid="tree" hidden>{JSON.stringify(tree)}</pre>
    </>
  );
}

/** The block outline: a layout as nested cards with a form per block, drawn from the server's block schemas. */
const meta: Meta<typeof Harness> = {
  title: "Components/ReportLayoutOutline",
  component: Harness,
  args: { initial: buildOutlineTree() },
};
export default meta;

type Story = StoryObj<typeof Harness>;

/** The first card with this name: a nested block can share a name and position with a top-level one. */
const card = (canvas: ReturnType<typeof within>, name: string) => within(canvas.getAllByRole("listitem", { name })[0]);

const treeOf = (canvasElement: HTMLElement): { nodes: Record<string, unknown>[] } & Tree =>
  JSON.parse(within(canvasElement).getByTestId("tree").textContent ?? "{}");

export const ShowsEachBlockAsACardWithItsForm: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const cards = canvas.getByRole("list", { name: "Layout outline" });
    await expect(within(cards).getAllByRole("listitem", { name: "Heading block 1" })).toHaveLength(2);
    await expect(within(cards).getByRole("listitem", { name: "For each record block 2" })).toBeInTheDocument();
    // The heading's form: text and level, with the level's schema bounds.
    const heading = card(canvas, "Heading block 1");
    await expect(heading.getByRole("textbox", { name: "Heading" })).toHaveValue("Requirements of {{project_name}}");
    await expect(heading.getByRole("spinbutton", { name: "Level" })).toHaveAttribute("max", "4");
    // The nested heading and table are cards inside the For each's Contents.
    const each = card(canvas, "For each record block 2");
    await expect(each.getByRole("list", { name: "Contents: For each record 2" })).toBeInTheDocument();
    await expect(each.getByRole("listitem", { name: "Table block 2" })).toBeInTheDocument();
  },
};

export const EditingAFieldChangesTheTree: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const heading = card(canvas, "Heading block 1");
    const box = heading.getByRole("textbox", { name: "Heading" });
    await userEvent.clear(box);
    await userEvent.type(box, "New title");
    await waitFor(() => expect(treeOf(canvasElement).nodes[0].text).toBe("New title"));
    const level = heading.getByRole("spinbutton", { name: "Level" });
    await userEvent.clear(level);
    // An emptied optional number is removed from the node, not stored as an empty string.
    await waitFor(() => expect(treeOf(canvasElement).nodes[0]).not.toHaveProperty("level"));
  },
};

export const AddingABlockUsesItsTemplate: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const adders = canvas.getAllByRole("button", { name: "Add block" });
    await userEvent.click(adders[adders.length - 1]);
    await userEvent.click(await screen.findByRole("menuitem", { name: "Page break" }));
    await waitFor(() => expect(treeOf(canvasElement).nodes.map((n) => n.type)).toEqual(["heading", "each", "page_break"]));
    await expect(canvas.getByRole("listitem", { name: "Page break block 3" })).toBeInTheDocument();
  },
};

/** Only the types for the layout's family are offered. */
export const ATableLayoutOffersOnlySheets: Story = {
  args: { initial: { schema_version: 1, family: "table", nodes: [] }, family: "table" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("This layout has no blocks yet. Add one to start.")).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Add block" }));
    await expect(await screen.findByRole("menuitem", { name: "Sheet" })).toBeInTheDocument();
    await expect(screen.queryByRole("menuitem", { name: "Heading" })).not.toBeInTheDocument();
  },
};

export const MovingABlockKeepsFocusOnTheSameControl: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const first = card(canvas, "Heading block 1");
    await expect(first.getByRole("button", { name: "Move up" })).toBeDisabled();
    await userEvent.click(first.getByRole("button", { name: "Move down" }));
    await waitFor(() => expect(treeOf(canvasElement).nodes.map((n) => n.type)).toEqual(["each", "heading"]));
    // The heading is now last, so Move down is disabled: focus goes to its opposite, Move up, on the same block.
    const second = card(canvas, "Heading block 2");
    await expect(second.getByRole("button", { name: "Move down" })).toBeDisabled();
    await waitFor(() => expect(second.getByRole("button", { name: "Move up" })).toHaveFocus());
  },
};

export const IndentAndOutdentMoveABlockBetweenLevels: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    // The nested table can leave the For each; the first top-level heading cannot go anywhere.
    const nested = within(card(canvas, "For each record block 2").getByRole("listitem", { name: "Table block 2" }));
    await userEvent.click(nested.getByRole("button", { name: "Move out of this block" }));
    await waitFor(() => expect(treeOf(canvasElement).nodes.map((n) => n.type)).toEqual(["heading", "each", "table"]));
    // Now the table follows the For each, so it can move back into it.
    const table = card(canvas, "Table block 3");
    await expect(table.getByRole("button", { name: "Move out of this block" })).toBeDisabled();
    await userEvent.click(table.getByRole("button", { name: "Move into the block above" }));
    await waitFor(() => expect(treeOf(canvasElement).nodes.map((n) => n.type)).toEqual(["heading", "each"]));
  },
};

export const DuplicateAndDeleteWork: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(card(canvas, "Heading block 1").getByRole("button", { name: "Duplicate" }));
    await waitFor(() => expect(treeOf(canvasElement).nodes.map((n) => n.type)).toEqual(["heading", "heading", "each"]));
    await userEvent.click(card(canvas, "Heading block 2").getByRole("button", { name: "Delete block" }));
    await waitFor(() => expect(treeOf(canvasElement).nodes.map((n) => n.type)).toEqual(["heading", "each"]));
  },
};

export const ACollapsedBlockHidesItsForm: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const heading = card(canvas, "Heading block 1");
    await userEvent.click(heading.getByRole("button", { name: "Hide details: Heading 1" }));
    await expect(heading.queryByRole("textbox", { name: "Heading" })).not.toBeInTheDocument();
    await userEvent.click(heading.getByRole("button", { name: "Show details: Heading 1" }));
    await expect(heading.getByRole("textbox", { name: "Heading" })).toBeInTheDocument();
  },
};

export const ProblemsShowOnTheBlockAndItsField: Story = {
  args: {
    problems: [
      { path: "nodes[0].text", message: "Must not be empty." },
      { path: "nodes[1].children[1].source.record_type", message: "Must be a reportable record type." },
      { path: "nodes[1].children", message: "Blocks are nested too deeply." },
    ],
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const heading = card(canvas, "Heading block 1");
    await expect(heading.getByText("1 problem")).toBeInTheDocument();
    await expect(heading.getByText("Must not be empty.")).toBeInTheDocument();
    // The table's source problem is on the table, under its Records fieldset; the For each shows only its container's.
    const table = card(canvas, "Table block 2");
    await expect(table.getByText("Must be a reportable record type.")).toBeInTheDocument();
    await expect(canvas.getByRole("listitem", { name: "For each record block 2" })).toHaveAttribute("data-invalid", "true");
    await expect(canvas.getByText("Blocks are nested too deeply.")).toBeInTheDocument();
  },
};

export const ALayoutLevelProblemShowsAboveTheBlocks: Story = {
  args: { problems: [{ path: "family", message: "This layout is a document layout; the tree says table." }] },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("family: This layout is a document layout; the tree says table.")).toBeInTheDocument();
  },
};

export const ReadOnlyShowsTheLayoutWithoutControls: Story = {
  args: { readOnly: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByRole("button", { name: "Add block" })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Move down" })).not.toBeInTheDocument();
    await expect(card(canvas, "Heading block 1").getByRole("textbox", { name: "Heading" })).toBeDisabled();
  },
};

/** Names given by the enclosing For each are what a nested block can link from. */
export const ANestedBlockCanLinkFromTheNameAboveIt: Story = {
  play: async ({ canvasElement }) => {
    const table = within(within(canvasElement).getByRole("listitem", { name: "Table block 2" }));
    const linked = table.getByRole("combobox", { name: "Linked from" }) as HTMLSelectElement;
    await expect(linked.value).toBe("req");
    await expect(Array.from(linked.options).map((o) => o.value)).toEqual(["", "req"]);
  },
};

export const ABlockOfAnUnknownTypeIsEditableAsJson: Story = {
  args: { initial: { schema_version: 1, family: "document", nodes: [{ type: "mystery", size: 3 }] } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const box = canvas.getByRole("textbox", { name: "mystery block (no form available) (JSON)" });
    await expect(box).toHaveValue(JSON.stringify({ type: "mystery", size: 3 }, null, 2));
    await userEvent.clear(box);
    await userEvent.type(box, '{{"type":"mystery","size":4}');
    await waitFor(() => expect(treeOf(canvasElement).nodes[0]).toEqual({ type: "mystery", size: 4 }));
  },
};

export const LayoutSettingsHoldOrientationAndVariables: Story = {
  args: { problems: [{ path: "variables[0].name", message: "Must be lower-case letters." }] },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Layout settings")).toBeInTheDocument();
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Page orientation" }), "landscape");
    await waitFor(() => expect(treeOf(canvasElement).orientation).toBe("landscape"));
    // A problem on the layout's own variables is shown there, and the settings open on it.
    await expect(canvas.getByText("Must be lower-case letters.")).toBeInTheDocument();
  },
};
