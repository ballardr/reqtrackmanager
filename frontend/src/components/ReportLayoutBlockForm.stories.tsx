import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, userEvent, waitFor, within } from "storybook/test";

import type { BlockType } from "../api/reportLayouts";
import { buildBlockCatalogue, buildFieldCatalogue, buildWidgets } from "../testing/reportLayoutFixtures";
import { buildUser, withStatefulAuth } from "../testing/storybook-helpers";
import type { TreeNode } from "../utils/reportLayoutTree";
import type { BlockEnv } from "./ReportLayoutBlockField";
import { ReportLayoutBlockForm } from "./ReportLayoutBlockForm";

const env: BlockEnv = { blocks: buildBlockCatalogue(), catalogue: buildFieldCatalogue(), widgets: buildWidgets(), variables: [], pageStyles: [], readOnly: false };
const typeOf = (type: string): BlockType => buildBlockCatalogue().blocks.find((b) => b.type === type)!;

function Harness({ type, initial, problems = {} }: { type: BlockType; initial: TreeNode; problems?: Record<string, string[]> }) {
  const [node, setNode] = useState<TreeNode>(initial);
  const set = (patch: Record<string, unknown>) => setNode((current) => {
    const next = { ...current, ...patch };
    for (const [key, value] of Object.entries(patch)) if (value === undefined) delete next[key];
    return next;
  });
  return (
    <>
      <ReportLayoutBlockForm
        type={type} node={node} names={[]} env={env} problemsByKey={new Map(Object.entries(problems))}
        onChange={(key, value) => set({ [key]: value })} onChangeMany={set}
      />
      <pre data-testid="node" hidden>{JSON.stringify(node)}</pre>
    </>
  );
}

/** The form with a button that swaps in another block of the same type (a fresh form, as selecting another block does). */
function NextBlock(args: Parameters<typeof Harness>[0]) {
  const [which, setWhich] = useState(1);
  return (
    <>
      <button type="button" onClick={() => setWhich(2)}>Next block</button>
      <Harness key={which} {...args} />
    </>
  );
}

/** A selected block's form: basic fields first, then the collapsible groups its schema declares. */
const meta: Meta<typeof Harness> = {
  title: "Components/ReportLayoutBlockForm", component: Harness, decorators: [withStatefulAuth(buildUser({ ui_preferences: {} }))],
  args: { type: typeOf("grid"), initial: { type: "grid", columns: [{}, {}], rows: [{ cells: [{ text: "a" }, { text: "b" }] }] } },
};
export default meta;

type Story = StoryObj<typeof Harness>;

const nodeOf = (el: HTMLElement) => JSON.parse(within(el).getByTestId("node").textContent ?? "null");

export const ACustomTableShowsItsBasicFieldsAndClosedGroups: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("spinbutton", { name: "Header rows" })).toBeVisible();
    await expect(canvas.getByRole("textbox", { name: "Label" })).toBeVisible();
    for (const name of ["Borders", "Cell style", "Look"]) {
      await expect(canvas.getByRole("button", { name: `${name} section` })).toHaveAttribute("aria-expanded", "false");
    }
    // Hidden settings are not in the page until their group opens.
    await expect(canvas.queryByRole("combobox", { name: "Borders" })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("radiogroup", { name: "Alignment" })).not.toBeInTheDocument();
  },
};

export const OpeningAGroupShowsItsControlsAndAChangeIsSaved: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Borders section" }));
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Borders" }), "outer");
    await waitFor(() => expect(nodeOf(canvasElement).borders).toBe("outer"));
    await userEvent.click(canvas.getByRole("button", { name: "Cell style section" }));
    await userEvent.click(canvas.getByRole("radio", { name: "Right" }));
    await userEvent.click(canvas.getByRole("button", { name: "Bold" }));
    await waitFor(() => expect(nodeOf(canvasElement)).toMatchObject({ align: "right", bold: true }));
  },
};

/** A hidden non-default value says so on the closed bar, so a plain-looking block is not misread. */
export const AClosedGroupCountsItsNonDefaultSettings: Story = {
  args: { initial: { type: "grid", columns: [{}], rows: [], borders: "none", align: "right", bold: true, size: 11 } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("button", { name: "Borders section" })).toHaveAccessibleDescription("1 changed");
    await expect(canvas.getByRole("button", { name: "Cell style section" })).toHaveAccessibleDescription("2 changed");
    await expect(canvas.getByRole("button", { name: "Look section" })).toHaveAccessibleDescription("1 changed");
  },
};

export const AValueAtItsDefaultIsNotCounted: Story = {
  args: { initial: { type: "grid", columns: [{}], rows: [], borders: "all", align: "left", bold: false } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    for (const name of ["Borders", "Cell style", "Look"]) {
      await expect(canvas.getByRole("button", { name: `${name} section` })).not.toHaveAccessibleDescription(/changed/);
    }
  },
};

export const AGroupStaysOpenForTheNextBlockOfTheSameType: Story = {
  render: (args) => <NextBlock {...args} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Look section" }));
    await expect(canvas.getByRole("spinbutton", { name: "Size" })).toBeVisible();
    await userEvent.click(canvas.getByRole("button", { name: "Next block" }));
    await expect(canvas.getByRole("button", { name: "Look section" })).toHaveAttribute("aria-expanded", "true");
    await expect(canvas.getByRole("button", { name: "Borders section" })).toHaveAttribute("aria-expanded", "false");
  },
};

export const AServerProblemOpensItsGroupAndSaysSo: Story = {
  args: { problems: { border_color: ["Border colour is not a colour."] } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("button", { name: "Borders section" })).toHaveAccessibleDescription("1 problem");
    await expect(canvas.getByText("Border colour is not a colour.")).toBeVisible();
  },
};

/** A type that declares no groups is drawn flat, as before. */
export const ATypeWithNoGroupsIsFlat: Story = {
  args: { type: typeOf("heading"), initial: { type: "heading", text: "x" } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("textbox", { name: "Heading" })).toBeVisible();
    await expect(canvas.getByRole("radiogroup", { name: "Level" })).toBeVisible();
    await expect(canvas.getByRole("combobox", { name: "Font" })).toBeVisible();
    await expect(canvas.queryByRole("button", { name: /section$/ })).not.toBeInTheDocument();
  },
};

/** A field naming a group the schema does not declare is still drawn, in an Other group. */
export const AFieldWithAnUndeclaredGroupLandsInOther: Story = {
  args: {
    type: {
      ...typeOf("grid"),
      fields: typeOf("grid").fields.map((f) => (f.key === "size" ? { ...f, group: "typography" } : f)),
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Other section" }));
    await expect(canvas.getByRole("spinbutton", { name: "Size" })).toBeVisible();
  },
};

/** A block type a module registers is arranged by its own declaration, with no edit to the form. */
export const AModuleBlockWithGroupsIsArrangedByItsOwnSchema: Story = {
  args: {
    type: {
      ...typeOf("equation"), type: "module_note", label: "Module note",
      fields: [
        { ...typeOf("grid").fields[0], key: "note", label: "Note", kind: "text", required: true, group: "", basic: true },
        { ...typeOf("grid").fields[0], key: "tone", label: "Tone", kind: "text", required: false, group: "style", basic: false },
      ],
      groups: [{ key: "style", label: "Style", open: false }],
    },
    initial: { type: "module_note", note: "x", tone: "calm" },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("textbox", { name: "Note" })).toBeVisible();
    await expect(canvas.getByRole("button", { name: "Style section" })).toHaveAccessibleDescription("1 changed");
    await userEvent.click(canvas.getByRole("button", { name: "Style section" }));
    await expect(canvas.getByRole("textbox", { name: "Tone" })).toHaveValue("calm");
  },
};

/** A group the schema opens (a block with no basic fields) starts open. */
export const ASchemaCanOpenAGroupByDefault: Story = {
  args: {
    type: {
      ...typeOf("grid"),
      fields: typeOf("grid").fields.filter((f) => f.group === "look"),
      groups: [{ key: "look", label: "Look", open: true }],
    },
  },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("spinbutton", { name: "Size" })).toBeVisible();
  },
};

/** A picture's file, words and alignment stay visible; its size, position and caption fold away. */
export const AnImageShowsItsBasicFieldsAndClosedGroups: Story = {
  args: { type: typeOf("image"), initial: { type: "image", file: "image-1" } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("textbox", { name: "Alternative text" })).toBeVisible();
    await expect(canvas.getByRole("radiogroup", { name: "Alignment" })).toBeVisible();
    for (const name of ["Size", "Position", "Caption"]) {
      await expect(canvas.getByRole("button", { name: `${name} section` })).toHaveAttribute("aria-expanded", "false");
    }
    await expect(canvas.queryByRole("spinbutton", { name: "Width" })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("combobox", { name: "Placement" })).not.toBeInTheDocument();
  },
};

export const AnImagesHiddenSettingsAreCountedOnTheirBars: Story = {
  args: {
    type: typeOf("image"),
    initial: { type: "image", file: "image-1", width: 85, width_unit: "mm", placement: "behind", caption: "A logo", caption_position: "above" },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("button", { name: "Size section" })).toHaveAccessibleDescription("2 changed");
    await expect(canvas.getByRole("button", { name: "Position section" })).toHaveAccessibleDescription("1 changed");
    await expect(canvas.getByRole("button", { name: "Caption section" })).toHaveAccessibleDescription("2 changed");
  },
};

export const AnImagesCaptionPositionIsAButtonGroupAndSetsTheSameValue: Story = {
  args: { type: typeOf("image"), initial: { type: "image", file: "image-1", caption: "A logo" } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Caption section" }));
    await userEvent.click(canvas.getByRole("radio", { name: "Above the picture" }));
    await waitFor(() => expect(nodeOf(canvasElement).caption_position).toBe("above"));
    await userEvent.click(canvas.getByRole("radio", { name: "Below the picture" }));
    await waitFor(() => expect(nodeOf(canvasElement)).not.toHaveProperty("caption_position"));
  },
};

/** A shape keeps its kind and fill in view; the outline, size, position and custom SVG fold away. */
export const AShapeShowsItsKindAndFillAndClosedGroups: Story = {
  args: { type: typeOf("shape"), initial: { type: "shape", shape: "rectangle", fill: "accent", width: 5, height: 2 } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("combobox", { name: "Shape" })).toBeVisible();
    for (const name of ["Outline", "Size", "Position", "SVG"]) {
      await expect(canvas.getByRole("button", { name: `${name} section` })).toHaveAttribute("aria-expanded", "false");
    }
    await userEvent.click(canvas.getByRole("button", { name: "Position section" }));
    await userEvent.click(canvas.getByRole("radio", { name: "Right" }));
    await waitFor(() => expect(nodeOf(canvasElement).align).toBe("right"));
  },
};

/** Record images has no basic part but its label, so its picture rules start open. */
export const RecordImagesOpensItsPictureRules: Story = {
  args: { type: typeOf("record_images"), initial: { type: "record_images" } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("button", { name: "Which pictures section" })).toHaveAttribute("aria-expanded", "true");
    await expect(canvas.getByRole("textbox", { name: "File names" })).toBeVisible();
    for (const name of ["Caption", "Size", "Position"]) {
      await expect(canvas.getByRole("button", { name: `${name} section` })).toHaveAttribute("aria-expanded", "false");
    }
  },
};

/** A value and its unit share one row, with the same names as when they were stacked. */
export const AValueAndItsUnitShareARow: Story = {
  args: { type: typeOf("image"), initial: { type: "image", file: "image-1" } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Size section" }));
    const width = canvas.getByRole("spinbutton", { name: "Width" });
    const unit = canvas.getByRole("combobox", { name: "Width unit" });
    await expect(width.closest(".block-field-row")).toBe(unit.closest(".block-field-row"));
    await expect(width.closest(".block-field-row")).not.toBeNull();
    const height = canvas.getByRole("spinbutton", { name: "Height" });
    await expect(height.closest(".block-field-row")).toBe(canvas.getByRole("combobox", { name: "Height unit" }).closest(".block-field-row"));
    await expect(height.closest(".block-field-row")).not.toBe(width.closest(".block-field-row"));
    await userEvent.type(width, "60");
    await userEvent.selectOptions(unit, "Millimetres (mm)");
    await waitFor(() => expect(nodeOf(canvasElement)).toMatchObject({ width: 60, width_unit: "mm" }));
  },
};
