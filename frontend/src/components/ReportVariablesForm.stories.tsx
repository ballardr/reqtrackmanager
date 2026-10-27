import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, fn, userEvent, within } from "storybook/test";

import { variableDefaults, type VariableValues } from "../api/reports";
import { buildReportVariable } from "../testing/reportFixtures";
import { requiredCaptions } from "../testing/requiredMarkers";
import { ReportVariablesForm } from "./ReportVariablesForm";

/** The run form of a custom report's variables: the control follows the variable's type and options. */
const meta: Meta<typeof ReportVariablesForm> = {
  title: "Components/Reports/ReportVariablesForm",
  component: ReportVariablesForm,
  args: { variables: [buildReportVariable()], values: {}, onChange: fn() },
};
export default meta;

type Story = StoryObj<typeof ReportVariablesForm>;

/** Holds its own values the way the runner does, so a story can click through. */
function Stateful({ variables, initial = {}, onChange }: { variables: Parameters<typeof ReportVariablesForm>[0]["variables"]; initial?: VariableValues; onChange?: (name: string, value: unknown) => void }) {
  const [values, setValues] = useState<VariableValues>({ ...variableDefaults(variables), ...initial });
  return (
    <ReportVariablesForm
      variables={variables}
      values={values}
      onChange={(name, value) => {
        onChange?.(name, value);
        setValues((current) => ({ ...current, [name]: value }));
      }}
    />
  );
}

export const AListOfOptionsIsPickedFromADropdown: Story = {
  render: (args) => <Stateful variables={args.variables} onChange={args.onChange as (n: string, v: unknown) => void} />,
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: /Categories/ }));
    await userEvent.click(await within(document.body).findByRole("checkbox", { name: "Billing" }));
    await userEvent.click(within(document.body).getByRole("checkbox", { name: "Security" }));
    // Chosen in the options' own order, not the order clicked.
    await expect(args.onChange).toHaveBeenLastCalledWith("categories", ["Security", "Billing"]);
  },
};

export const OnlyAVariableWithNoDefaultIsMarkedRequired: Story = {
  args: {
    variables: [
      buildReportVariable({ label: "Categories" }),
      buildReportVariable({ name: "since", type: "date", label: "Since", multiple: false, options: null, default: "2026-10-27" }),
      buildReportVariable({ name: "level", type: "enum", label: "Level", multiple: false, options: ["Must", "Should"], default: "Must" }),
      buildReportVariable({ name: "owner", type: "text", label: "Owner", multiple: false, options: null, default: null }),
    ],
  },
  render: (args) => <Stateful variables={args.variables} />,
  play: async ({ canvasElement }) => {
    await expect(requiredCaptions(canvasElement)).toEqual(["Categories", "Owner"]);
  },
};

export const OneOptionIsPickedFromASelect: Story = {
  args: { variables: [buildReportVariable({ name: "level", label: "Level", multiple: false, options: ["Must", "Should"], default: "Must" })] },
  render: (args) => <Stateful variables={args.variables} onChange={args.onChange as (n: string, v: unknown) => void} />,
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("combobox", { name: "Level" })).toHaveValue("Must");
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Level" }), "Should");
    await expect(args.onChange).toHaveBeenCalledWith("level", "Should");
  },
};

export const FreeInputVariablesUseTheirTypesControl: Story = {
  args: {
    variables: [
      buildReportVariable({ name: "since", type: "date", label: "Since", multiple: false, options: null, default: "2026-10-27" }),
      buildReportVariable({ name: "days", type: "number", label: "Days", multiple: false, options: null, default: 30 }),
      buildReportVariable({ name: "owner", type: "text", label: "Owner", multiple: false, options: null, default: "Sam" }),
      buildReportVariable({ name: "closed", type: "bool", label: "Include closed", multiple: false, options: null, default: false }),
    ],
  },
  render: (args) => <Stateful variables={args.variables} onChange={args.onChange as (n: string, v: unknown) => void} />,
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByLabelText("Since")).toHaveValue("2026-10-27");
    await userEvent.clear(canvas.getByLabelText("Days"));
    await userEvent.type(canvas.getByLabelText("Days"), "45");
    await expect(args.onChange).toHaveBeenLastCalledWith("days", 45);
    await userEvent.click(canvas.getByRole("switch", { name: "Include closed" }));
    await expect(args.onChange).toHaveBeenLastCalledWith("closed", true);
    await userEvent.clear(canvas.getByLabelText("Owner"));
    await expect(args.onChange).toHaveBeenLastCalledWith("owner", null);
  },
};

export const AListOfFreeValuesIsTypedAsCommaSeparatedText: Story = {
  args: { variables: [buildReportVariable({ name: "owners", type: "text", label: "Owners", options: null, source: null })] },
  render: (args) => <Stateful variables={args.variables} onChange={args.onChange as (n: string, v: unknown) => void} />,
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    // A trailing comma is kept in the box while the next value is typed.
    await userEvent.type(canvas.getByLabelText("Owners"), "Sam, Alex,");
    await expect(canvas.getByLabelText("Owners")).toHaveValue("Sam, Alex,");
    await expect(args.onChange).toHaveBeenLastCalledWith("owners", ["Sam", "Alex"]);
  },
};

export const AChosenValueThatIsNoLongerAnOptionStaysVisibleSoItCanBeUnchecked: Story = {
  render: (args) => <Stateful variables={args.variables} initial={{ categories: ["Retired"] }} onChange={args.onChange as (n: string, v: unknown) => void} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: /Categories/ }));
    await expect(await within(document.body).findByRole("checkbox", { name: "Retired" })).toBeChecked();
  },
};

export const ALayoutWithNoVariablesRendersNothing: Story = {
  args: { variables: [] },
  play: async ({ canvasElement }) => {
    await expect(canvasElement.querySelector("[role='group']")).toBeNull();
  },
};
