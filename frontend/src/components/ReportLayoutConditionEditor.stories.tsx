import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, userEvent, waitFor, within } from "storybook/test";

import { buildBlockCatalogue, buildFieldCatalogue } from "../testing/reportLayoutFixtures";
import { ConditionListEditor, ConditionNodeEditor, type Condition, type ConditionEnv } from "./ReportLayoutConditionEditor";

const env = (over: Partial<ConditionEnv> = {}): ConditionEnv => ({
  mode: "record", recordType: "requirement", catalogue: buildFieldCatalogue(), blocks: buildBlockCatalogue(), variables: [], modules: [], ...over,
});

/** Keeps the condition in state and prints it, so a story can read what an edit produced. */
function Harness({ initial, environment }: { initial: Condition; environment: ConditionEnv }) {
  const [value, setValue] = useState(initial);
  return (
    <>
      <ConditionNodeEditor env={environment} node={value} onChange={setValue} />
      <pre data-testid="value" hidden>{JSON.stringify(value)}</pre>
    </>
  );
}

function ListHarness({ initial, environment }: { initial: Condition[]; environment: ConditionEnv }) {
  const [value, setValue] = useState(initial);
  return (
    <>
      <ConditionListEditor env={environment} value={value} onChange={setValue} />
      <pre data-testid="value" hidden>{JSON.stringify(value)}</pre>
    </>
  );
}

/** A layout condition: one test, or all / any / not groups of tests, with operators and values that suit the field. */
const meta: Meta<typeof Harness> = {
  title: "Components/ReportLayoutConditionEditor",
  component: Harness,
  args: { initial: { field: "status", op: "eq", value: "Draft" }, environment: env() },
};
export default meta;

type Story = StoryObj<typeof Harness>;

const valueOf = (el: HTMLElement) => JSON.parse(within(el).getByTestId("value").textContent ?? "null");

export const OperatorsFollowTheFieldsKind: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const op = canvas.getByRole("combobox", { name: "Test" }) as HTMLSelectElement;
    // An enum field takes is / is not / is any of / is none of / is empty / is not empty, but not "contains".
    await expect(Array.from(op.options).map((o) => o.value)).toEqual(["", "eq", "ne", "in", "not_in", "empty", "not_empty"]);
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Field" }), "title");
    // Choosing a text field resets the test and offers "contains".
    await waitFor(async () => expect(Array.from((canvas.getByRole("combobox", { name: "Test" }) as HTMLSelectElement).options).map((o) => o.value)).toContain("contains"));
    await expect(valueOf(canvasElement)).toEqual({ field: "title", op: "eq", value: "" });
  },
};

export const AnEnumValueIsChosenFromItsChoices: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const value = canvas.getByRole("combobox", { name: "Value" }) as HTMLSelectElement;
    await expect(Array.from(value.options).map((o) => o.value)).toEqual(["", "Draft", "Approved"]);
    await userEvent.selectOptions(value, "Approved");
    await waitFor(() => expect(valueOf(canvasElement)).toEqual({ field: "status", op: "eq", value: "Approved" }));
  },
};

export const ATestWithoutAValueDropsIt: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Test" }), "empty");
    await waitFor(() => expect(valueOf(canvasElement)).toEqual({ field: "status", op: "empty" }));
    await expect(canvas.queryByRole("combobox", { name: "Value" })).not.toBeInTheDocument();
  },
};

export const SeveralValuesAreTypedSeparatedByCommas: Story = {
  args: { initial: { field: "title", op: "in", value: ["a"] } },
  play: async ({ canvasElement }) => {
    const box = within(canvasElement).getByRole("textbox", { name: "Values (separated by commas)" });
    await userEvent.clear(box);
    await userEvent.type(box, "x, y ,z");
    await waitFor(() => expect(valueOf(canvasElement)).toEqual({ field: "title", op: "in", value: ["x", "y", "z"] }));
  },
};

export const ANumberFieldTakesANumber: Story = {
  args: { initial: { field: "severity", op: "gt", value: 1 }, environment: env({ recordType: "pain_point" }) },
  play: async ({ canvasElement }) => {
    const box = within(canvasElement).getByRole("spinbutton", { name: "Value" });
    await userEvent.clear(box);
    await userEvent.type(box, "7");
    await waitFor(() => expect(valueOf(canvasElement)).toEqual({ field: "severity", op: "gt", value: 7 }));
  },
};

export const AGroupHoldsSeveralTestsAndCanBeUndone: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Kind of condition" }), "all");
    await waitFor(() => expect(valueOf(canvasElement)).toEqual({ all: [{ field: "status", op: "eq", value: "Draft" }, { field: "", op: "eq", value: "" }] }));
    const group = within(canvas.getByRole("group", { name: "All of" }));
    await userEvent.click(group.getByRole("button", { name: "Add condition" }));
    await waitFor(() => expect(valueOf(canvasElement).all).toHaveLength(3));
    await userEvent.click(group.getAllByRole("button", { name: "Remove condition" })[2]);
    await waitFor(() => expect(valueOf(canvasElement).all).toHaveLength(2));
  },
};

export const NotWrapsASingleCondition: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.selectOptions(within(canvasElement).getByRole("combobox", { name: "Kind of condition" }), "not");
    await waitFor(() => expect(valueOf(canvasElement)).toEqual({ not: { field: "status", op: "eq", value: "Draft" } }));
  },
};

export const AVariableValueCanBeReplacedByAPlainOne: Story = {
  args: { initial: { field: "status", op: "eq", value: { var: "wanted" } }, environment: env({ variables: ["wanted"] }) },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Uses variable wanted")).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Use a value" }));
    await waitFor(() => expect(valueOf(canvasElement)).toEqual({ field: "status", op: "eq", value: "" }));
  },
};

export const ADeclaredVariableCanBeUsedAsTheValue: Story = {
  args: { environment: env({ variables: ["wanted"] }) },
  play: async ({ canvasElement }) => {
    await userEvent.selectOptions(within(canvasElement).getByRole("combobox", { name: "Variable" }), "wanted");
    await waitFor(() => expect(valueOf(canvasElement)).toEqual({ field: "status", op: "eq", value: { var: "wanted" } }));
  },
};

/** An `if` tests a field of a name an enclosing block gave, or whether a module is available. */
export const AnIfTestsAFieldOfANameInScope: Story = {
  args: {
    initial: { ref: "req.status", op: "eq", value: "Draft" },
    environment: env({ mode: "ref", names: [{ name: "req", kind: "record", recordType: "requirement" }, { name: "grp", kind: "group", recordType: "requirement" }] }),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect((canvas.getByRole("combobox", { name: "Record" }) as HTMLSelectElement).value).toBe("req");
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Record" }), "grp");
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Field" }), "count");
    await waitFor(() => expect(valueOf(canvasElement)).toEqual({ ref: "grp.count", op: "eq", value: "" }));
    // A group's count is a number, so it takes the number operators.
    await expect(Array.from((canvas.getByRole("combobox", { name: "Test" }) as HTMLSelectElement).options).map((o) => o.value)).toContain("gt");
  },
};

export const AModuleTestChoosesFromTheModules: Story = {
  args: { initial: { module: "" }, environment: env({ mode: "ref", names: [], modules: [{ key: "risk_management", name: "Risk Management" }] }) },
  play: async ({ canvasElement }) => {
    await userEvent.selectOptions(within(canvasElement).getByRole("combobox", { name: "Module" }), "risk_management");
    await waitFor(() => expect(valueOf(canvasElement)).toEqual({ module: "risk_management" }));
  },
};

export const ADisabledEditorHasNoRemoveOrAddButtons: Story = {
  args: { initial: { all: [{ field: "status", op: "eq", value: "Draft" }, { field: "title", op: "empty" }] }, environment: env({ disabled: true }) },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByRole("button", { name: "Add condition" })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Remove condition" })).not.toBeInTheDocument();
    await expect(canvas.getAllByRole("combobox", { name: "Field" })[0]).toBeDisabled();
  },
};

/** A `where` list: every entry must hold. */
export const AWhereListAddsTestsAndGroups: Story = {
  render: () => <ListHarness initial={[]} environment={env()} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Add condition" }));
    await userEvent.click(canvas.getByRole("button", { name: "Add group" }));
    await waitFor(() => expect(valueOf(canvasElement)).toEqual([
      { field: "", op: "eq", value: "" },
      { all: [{ field: "", op: "eq", value: "" }, { field: "", op: "eq", value: "" }] },
    ]));
    await userEvent.click(canvas.getAllByRole("button", { name: "Remove condition" })[0]);
    await waitFor(() => expect(valueOf(canvasElement)).toHaveLength(1));
  },
};
