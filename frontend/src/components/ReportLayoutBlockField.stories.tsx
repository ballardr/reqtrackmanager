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
