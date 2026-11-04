import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, screen, userEvent, waitFor, within } from "storybook/test";

import type { BlockField } from "../api/reportLayouts";
import { buildBlockCatalogue, buildFieldCatalogue, buildImageLibrary, buildWidgets } from "../testing/reportLayoutFixtures";
import { requiredCaptions } from "../testing/requiredMarkers";
import { buildUser, withStatefulAuth } from "../testing/storybook-helpers";
import type { NameInScope, TreeNode } from "../utils/reportLayoutTree";
import { ReportLayoutBlockField, type BlockEnv } from "./ReportLayoutBlockField";

const env: BlockEnv = { blocks: buildBlockCatalogue(), catalogue: buildFieldCatalogue(), widgets: buildWidgets(), variables: [], pageStyles: [], readOnly: false };
const blockOf = (type: string) => buildBlockCatalogue().blocks.find((b) => b.type === type)!;
const fieldOf = (type: string, key: string): BlockField => blockOf(type).fields.find((f) => f.key === key)!;

function Harness({ field, initial, names = [], problems = [], environment = env }: {
  field: BlockField; initial: TreeNode; names?: NameInScope[]; problems?: string[]; environment?: BlockEnv;
}) {
  const [node, setNode] = useState(initial);
  return (
    <>
      <ReportLayoutBlockField
        field={field} node={node} names={names} env={environment} problems={problems}
        onChange={(key, value) => setNode((current) => {
          const next = { ...current, [key]: value };
          if (value === undefined) delete next[key];
          return next;
        })}
      />
      <pre data-testid="node" hidden>{JSON.stringify(node)}</pre>
    </>
  );
}

/** One field of a block, drawn by its kind from the block's schema, with the server's problems for it beneath. */
const meta: Meta<typeof Harness> = {
  title: "Components/ReportLayoutBlockField",
  component: Harness,
  decorators: [withStatefulAuth(buildUser({ ui_preferences: {} }))],
  args: { field: fieldOf("heading", "text"), initial: { type: "heading", text: "Hello" } },
};
export default meta;

type Story = StoryObj<typeof Harness>;

const nodeOf = (el: HTMLElement) => JSON.parse(within(el).getByTestId("node").textContent ?? "null");

export const ARequiredFieldIsMarkedAndAnOptionalOneIsNot: Story = {
  render: () => (
    <div>
      <Harness field={fieldOf("heading", "text")} initial={{ type: "heading", text: "x" }} />
      <Harness field={fieldOf("each", "empty_text")} initial={{ type: "each" }} />
    </div>
  ),
  play: async ({ canvasElement }) => {
    await expect(requiredCaptions(canvasElement)).toEqual(["Heading"]);
  },
};

export const AnEmptiedOptionalTextIsRemovedButARequiredOneKeepsItsKey: Story = {
  render: () => (
    <div>
      <Harness field={fieldOf("heading", "text")} initial={{ type: "heading", text: "x" }} />
      <Harness field={fieldOf("each", "empty_text")} initial={{ type: "each", empty_text: "none" }} />
    </div>
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.clear(canvas.getByRole("textbox", { name: "Heading" }));
    await userEvent.clear(canvas.getByRole("textbox", { name: "Text when there is nothing" }));
    const nodes = canvas.getAllByTestId("node").map((n) => JSON.parse(n.textContent ?? "null"));
    await expect(nodes[0]).toEqual({ type: "heading", text: "" });
    await expect(nodes[1]).toEqual({ type: "each" });
  },
};

export const TextThatAllowsPlaceholdersOffersTheNamesInScope: Story = {
  args: { names: [{ name: "req", kind: "record", recordType: "requirement" }] },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByText("Insert a field")).not.toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Insert a field into Heading" }));
    await userEvent.click(await within(document.body).findByRole("button", { name: "Insert {{req.status}}" }));
    await waitFor(() => expect(nodeOf(canvasElement).text).toBe("Hello{{req.status}}"));
    // A choice closes the list.
    await waitFor(() => expect(within(document.body).queryByRole("dialog")).toBeNull());
  },
};

/** A heading's words offer Bold and Italic, which wrap the selected words in the marks the server reads and store nothing else. */
export const AHeadingTextOffersBoldAndItalicOverTheSelection: Story = {
  args: { initial: { type: "heading", text: "Draft copy" } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const field = canvas.getByRole("textbox", { name: "Heading" }) as HTMLInputElement;
    field.focus();
    field.setSelectionRange(0, 5);
    await userEvent.click(canvas.getByRole("button", { name: "Heading: Bold" }));
    await waitFor(() => expect(nodeOf(canvasElement).text).toBe("**Draft** copy"));
    // The field puts the selection back on the wrapped words on the next frame; wait it out before selecting again.
    await new Promise((resolve) => requestAnimationFrame(() => resolve(null)));
    await waitFor(() => expect(field.selectionStart).toBe(2));
    field.focus();
    field.setSelectionRange(10, 14);
    await userEvent.click(canvas.getByRole("button", { name: "Heading: Italic" }));
    await waitFor(() => expect(nodeOf(canvasElement).text).toBe("**Draft** *copy*"));
    await expect(Object.keys(nodeOf(canvasElement)).sort()).toEqual(["text", "type"]);
  },
};

/** A text block's paragraphs offer the same two buttons; with nothing selected every line of the box is marked, bullets left outside the mark. */
export const ATextBlockMarksTheWholeBoxWhenNothingIsSelected: Story = {
  args: { field: fieldOf("text", "text"), initial: { type: "text", text: "First line\n\n- a point  " } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const field = canvas.getByRole("textbox", { name: "Text" }) as HTMLTextAreaElement;
    field.focus();
    field.setSelectionRange(4, 4);
    await userEvent.click(canvas.getByRole("button", { name: "Text: Italic" }));
    await waitFor(() => expect(nodeOf(canvasElement).text).toBe("*First line*\n\n- *a point*  "));
  },
};

/** In an empty box a mark pair is written so typing continues inside it. */
export const AnEmptyTextBlockGetsAMarkPair: Story = {
  args: { field: fieldOf("text", "text"), initial: { type: "text", text: "" } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("textbox", { name: "Text" }));
    await userEvent.click(canvas.getByRole("button", { name: "Text: Bold" }));
    await waitFor(() => expect(nodeOf(canvasElement).text).toBe("****"));
  },
};

/** Fields that do not read marks (a heading's font, a title) get no buttons, and a read-only form shows none. */
export const OnlyATextThatReadsMarksOffersTheButtons: Story = {
  render: () => (
    <div>
      <Harness field={fieldOf("contents", "title")} initial={{ type: "contents" }} />
      <Harness field={fieldOf("heading", "text")} initial={{ type: "heading", text: "x" }} environment={{ ...env, readOnly: true }} />
    </div>
  ),
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).queryByRole("button", { name: /Bold/ })).toBeNull();
  },
};

export const ANumberFieldShowsItsBoundsAndDefault: Story = {
  args: { field: fieldOf("contents", "levels"), initial: { type: "contents" } },
  play: async ({ canvasElement }) => {
    const levels = within(canvasElement).getByRole("spinbutton", { name: "Levels" });
    await expect(levels).toHaveAttribute("min", "1");
    await expect(levels).toHaveAttribute("max", "3");
    await expect(levels).toHaveAttribute("placeholder", "Default (3)");
    await userEvent.type(levels, "2");
    await waitFor(() => expect(nodeOf(canvasElement).levels).toBe(2));
  },
};

/** A heading's level is four buttons in one radio group; the default stores nothing and one tab stop reaches the group. */
export const AHeadingLevelIsAButtonGroupThatStoresTheNumber: Story = {
  args: { field: fieldOf("heading", "level"), initial: { type: "heading", text: "x", level: 2 } },
  play: async ({ canvasElement }) => {
    const group = within(canvasElement).getByRole("radiogroup", { name: "Level" });
    const radios = within(group).getAllByRole("radio");
    await expect(radios.map((r) => r.textContent)).toEqual(["1", "2", "3", "4"]);
    await expect(within(group).getByRole("radio", { name: "2" })).toHaveAttribute("aria-checked", "true");
    await userEvent.click(within(group).getByRole("radio", { name: "3" }));
    await waitFor(() => expect(nodeOf(canvasElement).level).toBe(3));
    await expect(within(group).getByRole("radio", { name: "3" })).toHaveAttribute("aria-checked", "true");
    // Choosing the default removes the key: a heading that never set a level stays as it was.
    await userEvent.click(within(group).getByRole("radio", { name: "1" }));
    await waitFor(() => expect(nodeOf(canvasElement).level).toBeUndefined());
    await expect(within(group).getByRole("radio", { name: "1" })).toHaveAttribute("aria-checked", "true");
  },
};

export const AButtonGroupMovesWithTheArrowKeysFromOneTabStop: Story = {
  args: { field: fieldOf("heading", "level"), initial: { type: "heading", text: "x", level: 2 } },
  play: async ({ canvasElement }) => {
    const group = within(canvasElement).getByRole("radiogroup", { name: "Level" });
    const tabStops = within(group).getAllByRole("radio").filter((r) => r.getAttribute("tabindex") === "0");
    await expect(tabStops).toHaveLength(1);
    tabStops[0].focus();
    await userEvent.keyboard("{ArrowRight}");
    await waitFor(() => expect(nodeOf(canvasElement).level).toBe(3));
    await expect(within(group).getByRole("radio", { name: "3" })).toHaveFocus();
    await userEvent.keyboard("{ArrowLeft}{ArrowLeft}");
    await waitFor(() => expect(nodeOf(canvasElement).level).toBeUndefined());
  },
};

/** A level the buttons do not offer (set through the text view or the API) leaves every button unchecked and is kept until one is pressed. */
export const AValueTheButtonsDoNotOfferIsKeptUntilOneIsPressed: Story = {
  args: { field: fieldOf("heading", "level"), initial: { type: "heading", text: "x", level: 9 } },
  play: async ({ canvasElement }) => {
    const group = within(canvasElement).getByRole("radiogroup", { name: "Level" });
    for (const radio of within(group).getAllByRole("radio")) await expect(radio).toHaveAttribute("aria-checked", "false");
    await expect(nodeOf(canvasElement).level).toBe(9);
    await userEvent.click(within(group).getByRole("radio", { name: "4" }));
    await waitFor(() => expect(nodeOf(canvasElement).level).toBe(4));
  },
};

export const AChoiceDrawnAsButtonsUsesTheSameLabelsAsTheSelect: Story = {
  args: { field: fieldOf("grid", "align"), initial: { type: "grid" } },
  play: async ({ canvasElement }) => {
    const group = within(canvasElement).getByRole("radiogroup", { name: "Alignment" });
    await expect(within(group).getAllByRole("radio").map((r) => r.textContent)).toEqual(["Left", "Centre", "Right", "Justify"]);
    await expect(within(group).getByRole("radio", { name: "Left" })).toHaveAttribute("aria-checked", "true");
    await userEvent.click(within(group).getByRole("radio", { name: "Centre" }));
    await waitFor(() => expect(nodeOf(canvasElement).align).toBe("center"));
    await userEvent.click(within(group).getByRole("radio", { name: "Left" }));
    await waitFor(() => expect(nodeOf(canvasElement).align).toBeUndefined());
  },
};

export const AToggleIsAPressedButtonThatStoresTrueOrNothing: Story = {
  args: { field: fieldOf("grid", "bold"), initial: { type: "grid" } },
  play: async ({ canvasElement }) => {
    const bold = within(canvasElement).getByRole("button", { name: "Bold" });
    await expect(bold).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(bold);
    await waitFor(() => expect(nodeOf(canvasElement).bold).toBe(true));
    await expect(bold).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(bold);
    await waitFor(() => expect(nodeOf(canvasElement).bold).toBeUndefined());
  },
};

export const ButtonControlsAreDisabledWhenReadOnly: Story = {
  render: () => (
    <div>
      <Harness field={fieldOf("grid", "align")} initial={{ type: "grid" }} environment={{ ...env, readOnly: true }} />
      <Harness field={fieldOf("grid", "bold")} initial={{ type: "grid" }} environment={{ ...env, readOnly: true }} />
    </div>
  ),
  play: async ({ canvasElement }) => {
    for (const radio of within(canvasElement).getAllByRole("radio")) await expect(radio).toBeDisabled();
    await expect(within(canvasElement).getByRole("button", { name: "Bold" })).toBeDisabled();
  },
};

export const ABlockFontIsAnInheritingSelectThatStoresOnlyWhatWasChosen: Story = {
  args: { field: fieldOf("text", "font"), initial: { type: "text", text: "x" } },
  play: async ({ canvasElement }) => {
    const select = within(canvasElement).getByRole("combobox", { name: "Font" }) as HTMLSelectElement;
    await expect(Array.from(select.options).map((o) => o.text)).toEqual(["Document font", "Sans", "Serif", "Mono", "Unicode Sans"]);
    await userEvent.selectOptions(select, "serif");
    await waitFor(() => expect(nodeOf(canvasElement).font).toBe("serif"));
    await userEvent.selectOptions(select, "");
    await waitFor(() => expect(nodeOf(canvasElement)).toEqual({ type: "text", text: "x" }));
  },
};

export const ABlockSizeSaysItFollowsTheDocumentWhenEmpty: Story = {
  args: { field: fieldOf("text", "size"), initial: { type: "text", text: "x" } },
  play: async ({ canvasElement }) => {
    const size = within(canvasElement).getByRole("spinbutton", { name: "Size" });
    await expect(size).toHaveAttribute("placeholder", "Document size");
    await userEvent.type(size, "11.5");
    await waitFor(() => expect(nodeOf(canvasElement).size).toBe(11.5));
  },
};

export const AHeadingColourOffersNoNoneOptionBecauseEmptyMeansTheDocumentsColour: Story = {
  args: { field: fieldOf("heading", "colour"), initial: { type: "heading", text: "x" } },
  play: async ({ canvasElement }) => {
    const button = within(canvasElement).getByRole("button", { name: /^Colour:/ });
    await expect(button).toHaveTextContent("Document heading colour");
    await userEvent.click(button);
    await expect(within(await screen.findByRole("dialog")).queryByText("No colour")).not.toBeInTheDocument();
  },
};

export const AChoiceShowsItsDefaultAndNamesTheOptions: Story = {
  args: { field: { ...fieldOf("heading", "text"), key: "orientation", label: "Page orientation", kind: "choice", choices: ["portrait", "landscape"], default: "portrait", features: [] }, initial: {} },
  play: async ({ canvasElement }) => {
    const select = within(canvasElement).getByRole("combobox", { name: "Page orientation" }) as HTMLSelectElement;
    await expect(Array.from(select.options).map((o) => o.text)).toEqual(["Default (portrait)", "Portrait", "Landscape"]);
    await userEvent.selectOptions(select, "landscape");
    await waitFor(() => expect(nodeOf(canvasElement).orientation).toBe("landscape"));
  },
};

export const AGroupByFieldOffersTheFieldsOfItsSource: Story = {
  args: { field: fieldOf("group", "by"), initial: { type: "group", source: { record_type: "requirement" }, by: "" } },
  play: async ({ canvasElement }) => {
    const select = within(canvasElement).getByRole("combobox", { name: "Group by" }) as HTMLSelectElement;
    await expect(Array.from(select.options).map((o) => o.value)).toEqual(["", "code", "title", "status", "description"]);
  },
};

export const AGroupByFieldWaitsForASource: Story = {
  args: { field: fieldOf("group", "by"), initial: { type: "group", source: {}, by: "" } },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("combobox", { name: "Group by" })).toBeDisabled();
  },
};

export const AnIfOffersAModuleTestWhenModulesExist: Story = {
  args: { field: fieldOf("if", "when"), initial: { type: "if", when: { ref: "", op: "eq", value: "" } } },
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "A module is available" }));
    await waitFor(() => expect(nodeOf(canvasElement).when).toEqual({ module: "" }));
    await expect(within(canvasElement).getByRole("combobox", { name: "Module" })).toBeInTheDocument();
  },
};

export const AKindTheOutlineDoesNotKnowFallsBackToJson: Story = {
  args: { field: { ...fieldOf("heading", "text"), key: "extra", label: "Extra", kind: "from_a_module", required: false }, initial: { type: "heading", extra: [1, 2] } },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("textbox", { name: "Extra (JSON)" })).toHaveValue(JSON.stringify([1, 2], null, 2));
  },
};

export const ProblemsAreListedBeneathTheControl: Story = {
  args: { problems: ["Must not be empty.", "Too long."] },
  play: async ({ canvasElement }) => {
    const alert = within(canvasElement).getByRole("alert");
    await expect(within(alert).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["Must not be empty.", "Too long."]);
  },
};

export const ReadOnlyDisablesTheControl: Story = {
  args: { environment: { ...env, readOnly: true } },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("textbox", { name: "Heading" })).toBeDisabled();
    await expect(within(canvasElement).queryByRole("button", { name: /^Insert a field into/ })).not.toBeInTheDocument();
  },
};

export const LayoutVariablesAreDeclaredWithTheSharedEditor: Story = {
  args: { field: { ...fieldOf("heading", "text"), key: "variables", label: "Variables", kind: "variables" }, initial: {} },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("This layout has no variables.")).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Add a variable" }));
    await waitFor(() => expect(nodeOf(canvasElement).variables).toHaveLength(1));
    await userEvent.click(canvas.getByRole("button", { name: /Remove variable/ }));
    // The last variable removed takes the whole key with it.
    await waitFor(() => expect(nodeOf(canvasElement)).not.toHaveProperty("variables"));
  },
};

const withStyles: BlockEnv = { ...env, pageStyles: ["Wide tables", "Narrow"] };

/** A section chooses one of the layout's page styles, and a name that is no longer one is still shown. */
export const ASectionChoosesOneOfTheLayoutsPageStyles: Story = {
  args: { field: fieldOf("section", "page_style"), initial: { type: "section", page_style: "Wide tables", children: [] }, environment: withStyles },
  play: async ({ canvasElement }) => {
    const select = within(canvasElement).getByRole("combobox", { name: "Page style" });
    await expect(select).toHaveValue("Wide tables");
    await userEvent.selectOptions(select, "Narrow");
    await waitFor(() => expect(nodeOf(canvasElement).page_style).toBe("Narrow"));
  },
};

export const ASectionNamingAMissingStyleSaysSo: Story = {
  args: { field: fieldOf("section", "page_style"), initial: { type: "section", page_style: "Gone", children: [] }, environment: withStyles },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("option", { name: "Gone (not a page style of this layout)" })).toBeInTheDocument();
  },
};

export const ASectionWithNoStylesPointsToThePageStyles: Story = {
  args: { field: fieldOf("section", "page_style"), initial: { type: "section", page_style: "", children: [] } },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("option", { name: "Add a page style under the layout's page styles first." })).toBeInTheDocument();
  },
};

const withImages: BlockEnv = { ...env, images: { library: buildImageLibrary(), scope: "project" } };

/** An image block's file field is the picture picker, and its sizes are decimal numbers that can be emptied again. */
export const AnImageBlockChoosesAPictureAndTakesDecimalSizes: Story = {
  args: { field: fieldOf("image", "file"), initial: { type: "image", file: "", alt: "" }, environment: withImages },
  render: (args) => (
    <div>
      <Harness {...args} />
      <Harness field={fieldOf("image", "width")} initial={{ type: "image", file: "image-1" }} environment={withImages} />
    </div>
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Choose image…" }));
    const dialog = within(await screen.findByRole("dialog"));
    await userEvent.click(await dialog.findByRole("button", { name: "Select site-logo.png" }));
    await userEvent.click(dialog.getByRole("button", { name: "Use image" }));
    await waitFor(() => expect(JSON.parse(canvas.getAllByTestId("node")[0].textContent ?? "{}").file).toBe("image-1"));
    const width = canvas.getByRole("spinbutton", { name: "Width" });
    await userEvent.type(width, "8.5");
    await waitFor(() => expect(JSON.parse(canvas.getAllByTestId("node")[1].textContent ?? "{}").width).toBe(8.5));
    await userEvent.clear(width);
    await waitFor(() => expect(JSON.parse(canvas.getAllByTestId("node")[1].textContent ?? "{}")).not.toHaveProperty("width"));
  },
};

/** An empty Width or Height says Auto in its box, so the ratio-keeping state is visible; typing replaces it and emptying restores it. */
export const AnEmptyImageSizeSaysAuto: Story = {
  args: { field: fieldOf("image", "width"), initial: { type: "image", file: "image-1" }, environment: withImages },
  render: (args) => (
    <div>
      <Harness {...args} />
      <Harness field={fieldOf("image", "height")} initial={{ type: "image", file: "image-1", height: 4 }} environment={withImages} />
    </div>
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("spinbutton", { name: "Width" })).toHaveAttribute("placeholder", "Auto");
    const height = canvas.getByRole("spinbutton", { name: "Height" });
    await expect(height).toHaveValue(4);
    await userEvent.clear(height);
    await expect(height).toHaveAttribute("placeholder", "Auto");
    await waitFor(() => expect(JSON.parse(canvas.getAllByTestId("node")[1].textContent ?? "{}")).not.toHaveProperty("height"));
  },
};

/** A picture's placement is a choice in plain words, and a position is a signed decimal that can be emptied again. */
export const AnImageBlockChoosesWhereItSitsAndPositionsALayer: Story = {
  args: { field: fieldOf("image", "placement"), initial: { type: "image", file: "image-1", alt: "a" }, environment: withImages },
  render: (args) => (
    <div>
      <Harness {...args} />
      <Harness field={fieldOf("image", "anchor")} initial={{ type: "image", file: "image-1", placement: "behind" }} environment={withImages} />
      <Harness field={fieldOf("image", "offset_x")} initial={{ type: "image", file: "image-1", placement: "behind" }} environment={withImages} />
    </div>
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const node = (index: number) => JSON.parse(canvas.getAllByTestId("node")[index].textContent ?? "{}");
    expect(canvas.getAllByRole("option").map((option) => option.textContent)).toEqual(expect.arrayContaining(["Text wraps beside it", "Behind the text", "In front of the text"]));
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Placement" }), "In front of the text");
    await waitFor(() => expect(node(0).placement).toBe("front"));
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Position from" }), "The corner of the page");
    await waitFor(() => expect(node(1).anchor).toBe("page"));
    const across = canvas.getByRole("spinbutton", { name: "Across (cm)" });
    await userEvent.type(across, "-2.5");
    await waitFor(() => expect(node(2).offset_x).toBe(-2.5));
    await userEvent.clear(across);
    await waitFor(() => expect(node(2)).not.toHaveProperty("offset_x"));
  },
};

const layoutField = (key: string): BlockField => buildBlockCatalogue().layout_fields.find((f) => f.key === key)!;

/** The layout's margins use the shared margin fields; emptying the last one removes the key. */
export const LayoutMarginsUseTheSharedMarginFields: Story = {
  args: { field: layoutField("margins"), initial: { schema_version: 1, family: "document", nodes: [] } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByRole("spinbutton", { name: "Top" }), "2");
    await waitFor(() => expect(nodeOf(canvasElement).margins).toEqual({ top: 2 }));
    await userEvent.clear(canvas.getByRole("spinbutton", { name: "Top" }));
    await waitFor(() => expect(nodeOf(canvasElement)).not.toHaveProperty("margins"));
  },
};

/** The layout's page styles use the shared editor and are written with the tree's own key names. */
export const LayoutPageStylesUseTheSharedEditor: Story = {
  args: { field: layoutField("page_styles"), initial: { schema_version: 1, family: "document", page_size: "A5", nodes: [] } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Add page style" }));
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Page size" }), "A3");
    await waitFor(() => expect(nodeOf(canvasElement).page_styles).toEqual([{ name: "Style 1", page_size: "A3" }]));
    await expect(canvas.getByRole("option", { name: "Same as the layout (A5)" })).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Remove page style Style 1" }));
    await waitFor(() => expect(nodeOf(canvasElement)).not.toHaveProperty("page_styles"));
  },
};

/** The layout's header uses the shared band editor: its own text is written to the tree, and "inherit" removes the key. */
export const LayoutHeaderUsesTheSharedBandEditor: Story = {
  args: { field: layoutField("header"), initial: { schema_version: 1, family: "document", nodes: [] } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Header: print" }), "custom");
    await userEvent.type(canvas.getByRole("textbox", { name: "Header, left cell" }), "Acme");
    await waitFor(() => expect(nodeOf(canvasElement).header).toEqual({ left: "Acme" }));
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Header: print" }), "none");
    await waitFor(() => expect(nodeOf(canvasElement).header).toEqual({}));
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Header: print" }), "inherit");
    await waitFor(() => expect(nodeOf(canvasElement)).not.toHaveProperty("header"));
  },
};

/** The footer is checked against the bottom margin of the layout. */
export const LayoutFooterIsCheckedAgainstTheBottomMargin: Story = {
  args: { field: layoutField("footer"), initial: { schema_version: 1, family: "document", margins: { bottom: 1 }, footer: { left: "a\nb\nc" }, nodes: [] } },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByRole("alert")).toHaveTextContent("The footer needs a bottom margin of at least 1.7 cm; it is 1 cm.");
  },
};

/** A record-images block's file-name rule is a list of lines; emptying it removes the key; its order is a choice. */
export const ARecordImagesBlockEditsItsRulesAsLists: Story = {
  render: () => (
    <div>
      <Harness field={fieldOf("record_images", "names")} initial={{ type: "record_images" }} />
      <Harness field={fieldOf("record_images", "order")} initial={{ type: "record_images" }} />
    </div>
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const node = (index: number) => JSON.parse(canvas.getAllByTestId("node")[index].textContent ?? "{}");
    const box = canvas.getByRole("textbox", { name: "File names" });
    await userEvent.type(box, "site-*{enter}{{{{rec.code}}-*");
    await waitFor(() => expect(node(0).names).toEqual(["site-*", "{{rec.code}}-*"]));
    await userEvent.clear(box);
    await waitFor(() => expect(node(0)).not.toHaveProperty("names"));
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Order" }), "When attached (oldest first)");
    await waitFor(() => expect(node(1).order).toBe("uploaded"));
  },
};

const fileNameField: BlockField = {
  key: "file_name", label: "File name", kind: "file_name", required: false, help: "", max_length: 200, minimum: null,
  maximum: null, default: null, choices: [], features: [], depends_on: null, families: [], empty_label: "",
  group: "", basic: false, control: "", inline: false,
};

/** The layout's File name is a template field: typing sets the key, emptying removes it, and the example is the server's. */
export const TheLayoutFileNameIsATemplateField: Story = {
  render: () => <Harness field={fileNameField} initial={{ family: "document" }} environment={{ ...env, variables: ["team"] }} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const box = canvas.getByRole("textbox", { name: "File name" });
    await userEvent.type(box, "report-{{{{var.team}}");
    await waitFor(() => expect(nodeOf(canvasElement).file_name).toBe("report-{{var.team}}"));
    await userEvent.clear(box);
    await waitFor(() => expect(nodeOf(canvasElement)).not.toHaveProperty("file_name"));
  },
};

const columnsField = (): BlockField => fieldOf("table", "columns");
const tableNames: NameInScope[] = [{ name: "record", kind: "record", recordType: "pain_point" }];

/** A table's columns offer Add images column, whose settings are the server's image-column fields, drawn with the shared forms. */
export const AnImagesColumnIsAddedAndItsSettingsAreStoredUnderImages: Story = {
  render: () => <Harness field={columnsField()} names={tableNames} initial={{ type: "table", columns: [{ field: "code" }] }} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByRole("button", { name: "Settings for column Images" })).not.toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Add images column" }));
    await waitFor(() => expect(nodeOf(canvasElement).columns).toEqual([{ field: "code" }, { images: {} }]));
    // The new column's settings open at once, in a popover holding the shared image-column forms.
    const group = within(await within(document.body).findByRole("dialog", { name: "Settings for column Images" }));
    await userEvent.type(group.getByRole("textbox", { name: "Heading" }), "Photos");
    await userEvent.type(group.getByRole("textbox", { name: "File names" }), "site-*{enter}");
    await userEvent.type(group.getByRole("spinbutton", { name: "Width" }), "60");
    await userEvent.selectOptions(group.getByRole("combobox", { name: "Arrangement" }), "Side by side, wrapping");
    await waitFor(() => expect(nodeOf(canvasElement).columns[1]).toEqual({
      label: "Photos", images: { names: ["site-*"], width: 60, arrange: "side_by_side" },
    }));
    // The width's unit says it is a share of the column, not of the text.
    const unit = group.getByRole("combobox", { name: "Width unit" });
    await expect(unit).toHaveDisplayValue("Default (percent)");
    await expect(within(unit).getByRole("option", { name: "% of the column's width" })).toBeInTheDocument();
  },
};

/** Emptying a setting removes its key, so the column keeps only what was set; the column can be moved and removed like any other. */
export const AnImagesColumnKeepsOnlyWhatWasSetAndCanBeRemoved: Story = {
  render: () => (
    <Harness field={columnsField()} names={tableNames} initial={{ type: "table", columns: [{ images: { names: ["a"], max_count: 2 } }, { field: "title" }] }} />
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Settings for column Images" }));
    const group = within(await within(document.body).findByRole("dialog", { name: "Settings for column Images" }));
    await userEvent.clear(group.getByRole("textbox", { name: "File names" }));
    await waitFor(() => expect(nodeOf(canvasElement).columns[0]).toEqual({ images: { max_count: 2 } }));
    await userEvent.keyboard("{Escape}");
    await userEvent.click(canvas.getByRole("button", { name: "Move column Images down" }));
    await waitFor(() => expect(nodeOf(canvasElement).columns).toEqual([{ field: "title" }, { images: { max_count: 2 } }]));
    await userEvent.click(canvas.getByRole("button", { name: "Remove column Images" }));
    await waitFor(() => expect(nodeOf(canvasElement).columns).toEqual([{ field: "title" }]));
  },
};

export const ReadOnlyHasNoAddImagesColumn: Story = {
  render: () => (
    <Harness field={columnsField()} names={tableNames} initial={{ type: "table", columns: [{ images: {} }] }} environment={{ ...env, readOnly: true }} />
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Settings for column Images" }));
    await expect(canvas.queryByRole("button", { name: "Add images column" })).not.toBeInTheDocument();
    await expect(await within(document.body).findByRole("textbox", { name: "File names" })).toBeDisabled();
  },
};

const repeatField = (): BlockField => buildBlockCatalogue().layout_fields.find((f) => f.key === "repeat_table_header")!;

/** A switch that is on unless set off: absent means on, switching off stores false, switching on again removes the key. */
export const TheRepeatHeaderSwitchIsOnUnlessSetOff: Story = {
  render: () => <Harness field={repeatField()} initial={{ family: "document" }} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const box = canvas.getByRole("checkbox", { name: "Repeat table header rows" });
    await expect(box).toBeChecked();
    await userEvent.click(box);
    await waitFor(() => expect(nodeOf(canvasElement).repeat_table_header).toBe(false));
    await expect(box).not.toBeChecked();
    await userEvent.click(box);
    await waitFor(() => expect(nodeOf(canvasElement)).not.toHaveProperty("repeat_table_header"));
    await expect(box).toBeChecked();
  },
};

export const AnExplicitTrueIsShownOn: Story = {
  render: () => <Harness field={repeatField()} initial={{ family: "document", repeat_table_header: true }} />,
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("checkbox", { name: "Repeat table header rows" })).toBeChecked();
  },
};

/** A spacer's height starts at 1 and its unit is named in words; changing the unit keeps the number. */
export const ASpacerBlockTakesAHeightInCentimetresOrMillimetres: Story = {
  render: () => (
    <div>
      <Harness field={fieldOf("spacer", "height")} initial={{ type: "spacer", height: 1 }} />
      <Harness field={fieldOf("spacer", "height_unit")} initial={{ type: "spacer", height: 1 }} />
    </div>
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const node = (index: number) => JSON.parse(canvas.getAllByTestId("node")[index].textContent ?? "{}");
    await expect(canvas.getByRole("spinbutton", { name: "Height" })).toHaveValue(1);
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Height unit" }), "Millimetres (mm)");
    await waitFor(() => expect(node(1).height_unit).toBe("mm"));
    expect(node(1).height).toBe(1);
  },
};

/** A table of contents takes a title (with placeholders), how many heading levels it lists and whether a new page follows it. */
export const AContentsBlockTakesATitleLevelsAndANewPageSwitch: Story = {
  render: () => (
    <div>
      <Harness field={fieldOf("contents", "title")} initial={{ type: "contents" }} />
      <Harness field={fieldOf("contents", "levels")} initial={{ type: "contents" }} />
      <Harness field={fieldOf("contents", "new_page")} initial={{ type: "contents" }} />
    </div>
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const node = (index: number) => JSON.parse(canvas.getAllByTestId("node")[index].textContent ?? "{}");
    await userEvent.type(canvas.getByRole("textbox", { name: "Title" }), "Index");
    await waitFor(() => expect(node(0).title).toBe("Index"));
    const levels = canvas.getByRole("spinbutton", { name: "Levels" });
    await userEvent.clear(levels);
    await userEvent.type(levels, "2");
    await waitFor(() => expect(node(1).levels).toBe(2));
    await userEvent.click(canvas.getByRole("checkbox", { name: "New page after" }));
    await waitFor(() => expect(node(2).new_page).toBeDefined());
  },
};

/** A shape's kind is named in plain words, its fill is the colour control, and the SVG of a custom shape is a long field that grows. */
export const AShapeBlockNamesItsKindInWordsAndTakesAnSvg: Story = {
  args: { field: fieldOf("shape", "shape"), initial: { type: "shape", shape: "rounded", width: 5, height: 2 } },
  render: (args) => (
    <div>
      <Harness {...args} />
      <Harness field={fieldOf("shape", "fill")} initial={{ type: "shape", shape: "rounded", width: 5, height: 2 }} />
      <Harness field={fieldOf("shape", "svg")} initial={{ type: "shape", shape: "custom" }} />
    </div>
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const node = (index: number) => JSON.parse(canvas.getAllByTestId("node")[index].textContent ?? "{}");
    expect(canvas.getAllByRole("option").map((option) => option.textContent)).toEqual(
      expect.arrayContaining(["Rectangle", "Rounded rectangle", "Ellipse", "Triangle", "Line", "Arrow", "Custom SVG"]),
    );
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Shape" }), "Arrow");
    await waitFor(() => expect(node(0).shape).toBe("arrow"));
    // A colour field is the shared colour control: a button naming the colour that opens the list, ending in a custom hex colour.
    await userEvent.click(canvas.getByRole("button", { name: "Fill: Default (accent)" }));
    const hexBox = within(document.body).getByRole("textbox", { name: "Fill (Custom colour) (hex code)" });
    await userEvent.clear(hexBox);
    await userEvent.type(hexBox, "#475569");
    await waitFor(() => expect(node(1).fill).toBe("#475569"));
    await userEvent.keyboard("{Escape}");
    await userEvent.type(canvas.getByRole("textbox", { name: "SVG" }), "<svg/>");
    await waitFor(() => expect(node(2).svg).toBe("<svg/>"));
  },
};
