import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, userEvent, waitFor, within } from "storybook/test";

import type { BlockField } from "../api/reportLayouts";
import { buildBlockCatalogue, buildFieldCatalogue, buildWidgets } from "../testing/reportLayoutFixtures";
import { requiredCaptions } from "../testing/requiredMarkers";
import type { NameInScope, TreeNode } from "../utils/reportLayoutTree";
import { ReportLayoutBlockField, type BlockEnv } from "./ReportLayoutBlockField";

const env: BlockEnv = { blocks: buildBlockCatalogue(), catalogue: buildFieldCatalogue(), widgets: buildWidgets(), variables: [], readOnly: false };
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
