import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, screen, userEvent, waitFor, within } from "storybook/test";

import type { BlockField } from "../api/reportLayouts";
import { buildBlockCatalogue, buildFieldCatalogue, buildImageLibrary, buildWidgets } from "../testing/reportLayoutFixtures";
import { requiredCaptions } from "../testing/requiredMarkers";
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
    await userEvent.click(canvas.getByText("Insert a field"));
    await userEvent.click(await canvas.findByRole("button", { name: "Insert {{req.status}}" }));
    await waitFor(() => expect(nodeOf(canvasElement).text).toBe("Hello{{req.status}}"));
  },
};

export const ANumberFieldShowsItsBoundsAndDefault: Story = {
  args: { field: fieldOf("heading", "level"), initial: { type: "heading", text: "x" } },
  play: async ({ canvasElement }) => {
    const level = within(canvasElement).getByRole("spinbutton", { name: "Level" });
    await expect(level).toHaveAttribute("min", "1");
    await expect(level).toHaveAttribute("max", "4");
    await expect(level).toHaveAttribute("placeholder", "Default (1)");
    await userEvent.type(level, "3");
    await waitFor(() => expect(nodeOf(canvasElement).level).toBe(3));
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
    await expect(within(canvasElement).queryByText("Insert a field")).not.toBeInTheDocument();
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
  maximum: null, default: null, choices: [], features: [], depends_on: null, families: [],
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
    await expect(canvas.queryByRole("group", { name: /images attached/ })).not.toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Add images column" }));
    await waitFor(() => expect(nodeOf(canvasElement).columns).toEqual([{ field: "code" }, { images: {} }]));
    const group = within(await canvas.findByRole("group", { name: "Column 2: images attached to the record" }));
    await userEvent.type(group.getByRole("textbox", { name: "Column 2 heading" }), "Photos");
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
    const group = within(await canvas.findByRole("group", { name: "Column 1: images attached to the record" }));
    await userEvent.clear(group.getByRole("textbox", { name: "File names" }));
    await waitFor(() => expect(nodeOf(canvasElement).columns[0]).toEqual({ images: { max_count: 2 } }));
    await userEvent.click(group.getByRole("button", { name: "Move column 1 down" }));
    await waitFor(() => expect(nodeOf(canvasElement).columns).toEqual([{ field: "title" }, { images: { max_count: 2 } }]));
    await userEvent.click(canvas.getByRole("button", { name: /Remove column 2/ }));
    await waitFor(() => expect(nodeOf(canvasElement).columns).toEqual([{ field: "title" }]));
  },
};

export const ReadOnlyHasNoAddImagesColumn: Story = {
  render: () => (
    <Harness field={columnsField()} names={tableNames} initial={{ type: "table", columns: [{ images: {} }] }} environment={{ ...env, readOnly: true }} />
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("group", { name: "Column 1: images attached to the record" })).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Add images column" })).not.toBeInTheDocument();
    await expect(canvas.getByRole("textbox", { name: "File names" })).toBeDisabled();
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
