import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, screen, userEvent, waitFor, within } from "storybook/test";

import type { TreeProblem } from "../api/reportLayouts";
import { buildBlockCatalogue, buildFieldCatalogue, buildOutlineTree, buildWidgets } from "../testing/reportLayoutFixtures";
import type { Tree } from "../utils/reportLayoutTree";
import { ReportLayoutRichText } from "./ReportLayoutRichText";

/** Keeps the tree in state, as the designer does, and prints it so a story can read what an edit produced. */
function Harness({ initial, problems = [], readOnly = false, family = "document" }: {
  initial: Tree; problems?: TreeProblem[]; readOnly?: boolean; family?: "document" | "table";
}) {
  const [tree, setTree] = useState(initial);
  return (
    <>
      <ReportLayoutRichText
        tree={tree} onChange={setTree} family={family} blocks={buildBlockCatalogue()} catalogue={buildFieldCatalogue()}
        widgets={buildWidgets()} problems={problems} readOnly={readOnly}
      />
      <pre data-testid="tree" hidden>{JSON.stringify(tree)}</pre>
      <button type="button" onClick={() => setTree({ ...initial, nodes: [{ type: "heading", text: "Replaced from outside" }] })}>Replace tree</button>
    </>
  );
}

/** The document view: headings and text typed in place, every other block a framed card with the outline's settings forms. */
const meta: Meta<typeof Harness> = { title: "Components/ReportLayoutRichText", component: Harness, args: { initial: buildOutlineTree() } };
export default meta;

type Story = StoryObj<typeof Harness>;

const treeOf = (el: HTMLElement): { nodes: Record<string, unknown>[] } & Tree => JSON.parse(within(el).getByTestId("tree").textContent ?? "{}");
const doc = (el: HTMLElement) => within(el).findByRole("region", { name: "Layout document" });
/** The editable text with this visible content. */
const editable = async (canvas: ReturnType<typeof within>, shown: string) => canvas.findByText(shown);

/** Puts the caret at the end of an element's text, as a click at its end would, then waits for the editor to see it. */
async function caretAtEnd(element: HTMLElement) {
  await userEvent.click(element);
  const selection = window.getSelection();
  selection?.selectAllChildren(element);
  selection?.collapseToEnd();
  await new Promise((resolve) => setTimeout(resolve, 50));
}

export const ShowsTheLayoutAsFramedBlocksAroundEditableProse: Story = {
  play: async ({ canvasElement }) => {
    const region = within(await doc(canvasElement));
    await expect(await region.findByText("Requirements of {{project_name}}")).toBeInTheDocument();
    await expect(region.getByText("For each record")).toBeInTheDocument();
    await expect(region.getByRole("group", { name: "Contents contents" })).toBeInTheDocument();
    await expect(region.getAllByText("Table").length).toBeGreaterThan(0);
    // The heading text is real editable content; the table is a card with a summary.
    const heading = await editable(region, "Requirements of {{project_name}}");
    await expect(heading.closest("[contenteditable='true']")).not.toBeNull();
  },
};

export const TypingInAHeadingChangesTheTree: Story = {
  play: async ({ canvasElement }) => {
    const region = within(await doc(canvasElement));
    const heading = await editable(region, "Requirements of {{project_name}}");
    await caretAtEnd(heading);
    await userEvent.keyboard(" (draft)");
    await waitFor(() => expect(treeOf(canvasElement).nodes[0].text).toBe("Requirements of {{project_name}} (draft)"));
    // Nothing else about the layout moved.
    await expect(treeOf(canvasElement).nodes).toHaveLength(2);
    await expect(treeOf(canvasElement).orientation).toBe("portrait");
  },
};

export const ATextBlockIsEditedAsParagraphsAndLists: Story = {
  args: { initial: { schema_version: 1, family: "document", nodes: [{ type: "text", text: "First paragraph." }] } },
  play: async ({ canvasElement }) => {
    const region = within(await doc(canvasElement));
    const paragraph = await editable(region, "First paragraph.");
    await caretAtEnd(paragraph);
    await userEvent.keyboard("{Enter}Second paragraph.{Enter}- item one{Enter}item two");
    await waitFor(() => expect(treeOf(canvasElement).nodes[0].text).toBe("First paragraph.\n\nSecond paragraph.\n\n- item one\n- item two"));
  },
};

export const EnterEndsAHeadingAndStartsATextBlockAfterIt: Story = {
  args: { initial: { schema_version: 1, family: "document", nodes: [{ type: "heading", text: "Title" }] } },
  play: async ({ canvasElement }) => {
    const region = within(await doc(canvasElement));
    await caretAtEnd(await editable(region, "Title"));
    await userEvent.keyboard("{Enter}Body words");
    await waitFor(() => expect(treeOf(canvasElement).nodes).toEqual([{ type: "heading", text: "Title" }, { type: "text", text: "Body words" }]));
  },
};

export const SettingsOfABlockUseTheOutlinesForms: Story = {
  play: async ({ canvasElement }) => {
    const region = within(await doc(canvasElement));
    await userEvent.click(region.getAllByRole("button", { name: "Settings: Table" })[0]);
    // The table's own forms appear (the same as the outline's), with the For each's name in scope for "Linked from".
    const linked = (await region.findByRole("combobox", { name: "Linked from" })) as HTMLSelectElement;
    await expect(Array.from(linked.options).map((o) => o.value)).toEqual(["", "req"]);
    await userEvent.type(region.getByRole("textbox", { name: "Column 2 heading" }), " (renamed)");
    await waitFor(() => expect((treeOf(canvasElement).nodes[1].children as Record<string, unknown>[])[1].columns).toEqual([{ field: "code" }, { field: "title", label: "Pain point (renamed)" }]));
  },
};

export const AHeadingsLevelIsASetting: Story = {
  args: { initial: { schema_version: 1, family: "document", nodes: [{ type: "heading", text: "Title", level: 2 }] } },
  play: async ({ canvasElement }) => {
    const region = within(await doc(canvasElement));
    await userEvent.click(region.getByRole("button", { name: "Settings: Heading" }));
    const level = await region.findByRole("spinbutton", { name: "Level" });
    await userEvent.clear(level);
    await userEvent.type(level, "3");
    await waitFor(() => expect(treeOf(canvasElement).nodes[0]).toEqual({ type: "heading", text: "Title", level: 3 }));
    // The heading's own text is not a settings field: it is typed in the document.
    await expect(region.queryByRole("textbox", { name: "Heading" })).not.toBeInTheDocument();
  },
};

export const MovingABlockRedrawsTheDocumentFromTheEditedTree: Story = {
  play: async ({ canvasElement }) => {
    const region = within(await doc(canvasElement));
    await region.findByText("Requirements of {{project_name}}");
    await userEvent.click(region.getAllByRole("button", { name: "Move down" })[0]);
    await waitFor(() => expect(treeOf(canvasElement).nodes.map((n) => n.type)).toEqual(["each", "heading"]));
    await expect(await region.findByText("Requirements of {{project_name}}")).toBeInTheDocument();
  },
};

export const IndentAndDuplicateAndDeleteWork: Story = {
  args: { initial: { schema_version: 1, family: "document", nodes: [{ type: "each", source: { record_type: "requirement" }, children: [] }, { type: "page_break" }] } },
  play: async ({ canvasElement }) => {
    const region = within(await doc(canvasElement));
    // The page break (second block) can go into the For each above it.
    const indents = await region.findAllByRole("button", { name: "Move into the block above" });
    await userEvent.click(indents[1]);
    await waitFor(() => expect((treeOf(canvasElement).nodes[0].children as unknown[]).length).toBe(1));
    await userEvent.click(region.getAllByRole("button", { name: "Duplicate" })[1]);
    await waitFor(() => expect((treeOf(canvasElement).nodes[0].children as unknown[]).length).toBe(2));
    await userEvent.click(region.getAllByRole("button", { name: "Delete block" })[1]);
    await userEvent.click(region.getAllByRole("button", { name: "Delete block" })[1]);
    await waitFor(() => expect((treeOf(canvasElement).nodes[0].children as unknown[]).length).toBe(0));
  },
};

export const AddBlockAddsAtTheEndAndInsideAList: Story = {
  args: { initial: { schema_version: 1, family: "document", nodes: [{ type: "each", source: { record_type: "requirement" }, children: [] }] } },
  play: async ({ canvasElement }) => {
    const region = within(await doc(canvasElement));
    await userEvent.click(await region.findByRole("button", { name: "Add to Contents" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Heading" }));
    await waitFor(() => expect((treeOf(canvasElement).nodes[0].children as Record<string, unknown>[])[0]).toEqual({ type: "heading", text: "Heading", level: 2 }));
    await userEvent.click(region.getByRole("button", { name: "Add block" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Page break" }));
    await waitFor(() => expect(treeOf(canvasElement).nodes.map((n) => n.type)).toEqual(["each", "page_break"]));
  },
};

/** Markdown the document view cannot draw as prose stays as written, in a source box. */
export const MarkdownItCannotDrawAsProseIsKeptAsSource: Story = {
  args: { initial: { schema_version: 1, family: "document", nodes: [{ type: "text", text: "1) one\n2) two" }] } },
  play: async ({ canvasElement }) => {
    const region = within(await doc(canvasElement));
    const source = (await region.findByRole("textbox", { name: "Text (Markdown source)" })) as HTMLTextAreaElement;
    await expect(source.value).toBe("1) one\n2) two");
    await userEvent.type(source, "\n3) three");
    await waitFor(() => expect(treeOf(canvasElement).nodes).toEqual([{ type: "text", text: "1) one\n2) two\n3) three" }]));
  },
};

export const ProblemsShowOnTheBlockTheyBelongTo: Story = {
  args: { problems: [{ path: "nodes[1].children[1].source.record_type", message: "Must be a reportable record type." }, { path: "nodes[0].text", message: "Must not be empty." }] },
  play: async ({ canvasElement }) => {
    const region = within(await doc(canvasElement));
    await expect(await region.findByText("Must be a reportable record type.")).toBeInTheDocument();
    await expect(region.getByText("Must not be empty.")).toBeInTheDocument();
    await expect(region.getAllByText("1 problem").length).toBe(2);
  },
};

export const ALayoutLevelProblemShowsWithTheSettings: Story = {
  args: { problems: [{ path: "orientation", message: "Must be one of: portrait, landscape." }] },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByText("Must be one of: portrait, landscape.")).toBeInTheDocument();
  },
};

export const ATreeChangedFromOutsideRedrawsTheDocument: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByText("Requirements of {{project_name}}");
    await userEvent.click(canvas.getByRole("button", { name: "Replace tree" }));
    await expect(await canvas.findByText("Replaced from outside")).toBeInTheDocument();
    await expect(canvas.queryByText("Requirements of {{project_name}}")).not.toBeInTheDocument();
  },
};

export const ATreeItCannotShowWithoutChangingIsRefusedWithTheReason: Story = {
  args: { initial: { schema_version: 1, family: "document", nodes: [{ type: "each", children: "nope" }] } },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByRole("alert")).toHaveTextContent('The document view cannot show this layout without changing it: nodes[0].children: "children" is not a list of blocks.');
  },
};

export const ATableLayoutHasNoDocument: Story = {
  args: { initial: { schema_version: 1, family: "table", nodes: [] }, family: "table" },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("note")).toHaveTextContent("A table layout has no document to show; use the outline or the text.");
  },
};

export const ReadOnlyShowsTheDocumentWithoutControls: Story = {
  args: { readOnly: true },
  play: async ({ canvasElement }) => {
    const region = within(await doc(canvasElement));
    await region.findByText("Requirements of {{project_name}}");
    await expect(region.queryByRole("button", { name: "Add block" })).not.toBeInTheDocument();
    await expect(region.queryByRole("button", { name: "Move down" })).not.toBeInTheDocument();
    const heading = await editable(region, "Requirements of {{project_name}}");
    await expect(heading.closest("[contenteditable='true']")).toBeNull();
  },
};

// ---- formatting ---------------------------------------------------------------------------------------------------

/** Selects characters `from`..`to` of an element's text, as dragging across them would, and lets the editor see it. */
async function selectText(element: HTMLElement, from: number, to: number) {
  const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
  const node = walker.nextNode() as Text;
  const range = document.createRange();
  range.setStart(node, from);
  range.setEnd(node, to);
  const selection = window.getSelection();
  selection?.removeAllRanges();
  selection?.addRange(range);
  await new Promise((resolve) => setTimeout(resolve, 80));
}

const oneText = (markdown: string): Tree => ({ schema_version: 1, family: "document", nodes: [{ type: "text", text: markdown }] });

export const StylesInATextBlockAreDrawnAsStyles: Story = {
  args: { initial: oneText("A **bold**, *italic* and `code` line.\n\n1. one\n2. two") },
  play: async ({ canvasElement }) => {
    const region = within(await doc(canvasElement));
    await expect((await region.findByText("bold")).tagName).toBe("STRONG");
    await expect(region.getByText("italic").tagName).toBe("EM");
    await expect(region.getByText("code").tagName).toBe("CODE");
    await expect(region.getByText("two").closest("ol")).not.toBeNull();
  },
};

export const BoldAppliedToASelectionIsWrittenAsMarkdown: Story = {
  args: { initial: oneText("Hello world") },
  play: async ({ canvasElement }) => {
    const region = within(await doc(canvasElement));
    const paragraph = await region.findByText("Hello world");
    await userEvent.click(paragraph);
    await selectText(paragraph, 6, 11);
    await userEvent.click(region.getByRole("button", { name: "Bold" }));
    await waitFor(() => expect(treeOf(canvasElement).nodes[0].text).toBe("Hello **world**"));
    await expect(region.getByRole("button", { name: "Bold" })).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(region.getByRole("button", { name: "Italic" }));
    await waitFor(() => expect(treeOf(canvasElement).nodes[0].text).toBe("Hello ***world***"));
    await userEvent.click(region.getByRole("button", { name: "Bold" }));
    await waitFor(() => expect(treeOf(canvasElement).nodes[0].text).toBe("Hello *world*"));
  },
};

export const ACodeSpanAndAListAreMadeFromTheToolbar: Story = {
  args: { initial: oneText("Use the flag") },
  play: async ({ canvasElement }) => {
    const region = within(await doc(canvasElement));
    const paragraph = await region.findByText("Use the flag");
    await userEvent.click(paragraph);
    await selectText(paragraph, 8, 12);
    await userEvent.click(region.getByRole("button", { name: "Code" }));
    await waitFor(() => expect(treeOf(canvasElement).nodes[0].text).toBe("Use the `flag`"));
    await userEvent.click(region.getByRole("button", { name: "Numbered list" }));
    await waitFor(() => expect(treeOf(canvasElement).nodes[0].text).toBe("1. Use the `flag`"));
    await userEvent.click(region.getByRole("button", { name: "Bullet list" }));
    await waitFor(() => expect(treeOf(canvasElement).nodes[0].text).toBe("- Use the `flag`"));
  },
};

export const TypedMarkersBecomeStylesAsTheyAreClosed: Story = {
  args: { initial: oneText("Start") },
  play: async ({ canvasElement }) => {
    const region = within(await doc(canvasElement));
    await caretAtEnd(await region.findByText("Start"));
    await userEvent.keyboard(" **big** and *slanted* ");
    await waitFor(() => expect(treeOf(canvasElement).nodes[0].text).toBe("Start **big** and *slanted*"));
  },
};

export const AHeadingHoldsNoStyles: Story = {
  args: { initial: { schema_version: 1, family: "document", nodes: [{ type: "heading", text: "Plain heading" }] } },
  play: async ({ canvasElement }) => {
    const region = within(await doc(canvasElement));
    const heading = await region.findByText("Plain heading");
    await userEvent.click(heading);
    await selectText(heading, 0, 5);
    await expect(region.getByRole("button", { name: "Bold" })).toBeDisabled();
    await expect(region.getByRole("button", { name: "Numbered list" })).toBeDisabled();
  },
};

export const ReadOnlyDisablesTheFormattingButtons: Story = {
  args: { readOnly: true, initial: oneText("Words") },
  play: async ({ canvasElement }) => {
    const region = within(await doc(canvasElement));
    await expect(await region.findByRole("button", { name: "Bold" })).toBeDisabled();
  },
};

// ---- links --------------------------------------------------------------------------------------------------------

export const ALinkInATextBlockIsDrawnAsALinkThatIsNotFollowed: Story = {
  args: { initial: oneText("See [the spec](https://example.org/spec) and [details](#overview).") },
  play: async ({ canvasElement }) => {
    const region = within(await doc(canvasElement));
    const link = (await region.findByText("the spec")).closest("a") as HTMLAnchorElement;
    await expect(link.getAttribute("href")).toBe("https://example.org/spec");
    await expect(region.getByText("details").closest("a")?.getAttribute("href")).toBe("#overview");
    // Clicking it stays in the editor: the document does not navigate.
    const before = window.location.href;
    await userEvent.click(link);
    await expect(window.location.href).toBe(before);
  },
};

export const SelectedWordsBecomeALinkThroughTheDialog: Story = {
  args: { initial: oneText("Read the spec today") },
  play: async ({ canvasElement }) => {
    const region = within(await doc(canvasElement));
    const paragraph = await region.findByText("Read the spec today");
    await userEvent.click(paragraph);
    await expect(region.getByRole("button", { name: "Link" })).toBeDisabled(); // nothing selected yet
    await selectText(paragraph, 9, 13);
    await userEvent.click(region.getByRole("button", { name: "Link" }));
    const dialog = within(await screen.findByRole("dialog", { name: "Link" }));
    await userEvent.type(dialog.getByRole("textbox", { name: /Web address/ }), "https://example.org/spec");
    await userEvent.click(dialog.getByRole("button", { name: "Apply" }));
    await waitFor(() => expect(treeOf(canvasElement).nodes[0].text).toBe("Read the [spec](https://example.org/spec) today"));
  },
};

export const ALinkIsChangedAndRemovedFromTheCaretInsideIt: Story = {
  args: { initial: oneText("Go [here](https://example.org/old) now") },
  play: async ({ canvasElement }) => {
    const region = within(await doc(canvasElement));
    const link = await region.findByText("here");
    await userEvent.click(link);
    await selectText(link, 1, 1);
    await userEvent.click(region.getByRole("button", { name: "Link" }));
    let dialog = within(await screen.findByRole("dialog", { name: "Link" }));
    const box = dialog.getByRole("textbox", { name: /Web address/ });
    await expect(box).toHaveValue("https://example.org/old");
    await userEvent.clear(box);
    await userEvent.type(box, "https://example.org/new");
    await userEvent.click(dialog.getByRole("button", { name: "Apply" }));
    await waitFor(() => expect(treeOf(canvasElement).nodes[0].text).toBe("Go [here](https://example.org/new) now"));
    await userEvent.click(region.getByRole("button", { name: "Link" }));
    dialog = within(await screen.findByRole("dialog", { name: "Link" }));
    await userEvent.click(dialog.getByRole("button", { name: "Remove link" }));
    await waitFor(() => expect(treeOf(canvasElement).nodes[0].text).toBe("Go here now"));
  },
};

export const ASectionLinkListsTheLayoutsHeadings: Story = {
  args: {
    initial: {
      schema_version: 1, family: "document",
      nodes: [{ type: "heading", text: "Overview" }, { type: "heading", text: "Per {{record.title}}" }, { type: "text", text: "Jump to the details" }],
    },
  },
  play: async ({ canvasElement }) => {
    const region = within(await doc(canvasElement));
    const paragraph = await region.findByText("Jump to the details");
    await userEvent.click(paragraph);
    await selectText(paragraph, 8, 19);
    await userEvent.click(region.getByRole("button", { name: "Link" }));
    const dialog = within(await screen.findByRole("dialog", { name: "Link" }));
    await userEvent.selectOptions(dialog.getByRole("combobox", { name: /Link to/ }), "section");
    const section = dialog.getByRole("combobox", { name: /^Section/ }) as HTMLSelectElement;
    // The heading that holds a value is left out; the rest are offered.
    await expect(Array.from(section.options).map((o) => o.text)).toEqual(["Choose a section…", "Overview"]);
    await userEvent.selectOptions(section, "overview");
    await userEvent.click(dialog.getByRole("button", { name: "Apply" }));
    await waitFor(() => expect(treeOf(canvasElement).nodes[2].text).toBe("Jump to [the details](#overview)"));
  },
};

export const ALinkAndStylesTogetherAreWrittenAsOneLink: Story = {
  args: { initial: oneText("A [**bold** link](https://example.org) here") },
  play: async ({ canvasElement }) => {
    const region = within(await doc(canvasElement));
    await expect((await region.findByText("bold")).closest("a")).not.toBeNull();
    await caretAtEnd(canvasElement.querySelector(".rich-prose p") as HTMLElement);
    await userEvent.keyboard("!");
    await waitFor(() => expect(treeOf(canvasElement).nodes[0].text).toBe("A [**bold** link](https://example.org) here!"));
  },
};

export const AHeadingHoldsNoLinks: Story = {
  args: { initial: { schema_version: 1, family: "document", nodes: [{ type: "heading", text: "Plain heading" }] } },
  play: async ({ canvasElement }) => {
    const region = within(await doc(canvasElement));
    const heading = await region.findByText("Plain heading");
    await userEvent.click(heading);
    await selectText(heading, 0, 5);
    await expect(region.getByRole("button", { name: "Link" })).toBeDisabled();
  },
};

export const ALinkTheServerWouldRefuseIsLeftAsSource: Story = {
  args: { initial: oneText("Do not [click](javascript:alert(1)) this") },
  play: async ({ canvasElement }) => {
    const region = within(await doc(canvasElement));
    const source = (await region.findByRole("textbox", { name: "Text (Markdown source)" })) as HTMLTextAreaElement;
    await expect(source.value).toBe("Do not [click](javascript:alert(1)) this");
    await expect(canvasElement.querySelector("a[href^='javascript']")).toBeNull();
  },
};
