import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, fn, userEvent, within } from "storybook/test";

import { expectStressStable, STRESS_TEXT } from "../../testing/stressFixtures";
import { TextStress } from "../../testing/TextStress";
import { BaselineSettingsFields } from "./BaselineSettingsFields";
import { BASELINE_CHECKS, BASELINE_TYPES, EMPTY_BASELINE, FIELD_OPTIONS, FILLED_BASELINE } from "./policyFixtures";
import type { BaselineSettings } from "./types";

/** Holds the policy the fields edit, and reports each change to `onChange`. */
function Harness({
  initial, onChange, checks = BASELINE_CHECKS, types = BASELINE_TYPES, long = false,
}: {
  initial: BaselineSettings; onChange: (settings: BaselineSettings) => void; checks?: typeof BASELINE_CHECKS; types?: typeof BASELINE_TYPES; long?: boolean;
}) {
  const [settings, setSettings] = useState(initial);
  const options = long
    ? { requirement: [{ key: "reasoning", label: STRESS_TEXT.name }], risk: [{ key: "statement", label: STRESS_TEXT.word }] }
    : FIELD_OPTIONS;
  return (
    <BaselineSettingsFields
      settings={settings} checkOptions={checks} types={types} fieldOptions={options}
      onChange={(next) => { setSettings(next); onChange(next); }}
    />
  );
}

const meta: Meta<typeof Harness> = {
  title: "Modules/Governance/BaselineSettingsFields",
  component: Harness,
  args: { initial: FILLED_BASELINE, onChange: fn() },
};
export default meta;

type Story = StoryObj<typeof Harness>;

export const ShowsTheCurrentPolicy: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("checkbox", { name: "Stage baseline" })).toBeChecked();
    await expect(canvas.getByRole("checkbox", { name: "Manual baseline" })).toBeChecked();
    await expect(canvas.getByRole("checkbox", { name: "Required fields" })).toBeChecked();
    await expect(canvas.getByRole("checkbox", { name: "Required approvals" })).not.toBeChecked();
    await expect(canvas.getByText("Record types: Requirement")).toBeInTheDocument();
    await expect(canvas.getByText("Requirement · Reasoning")).toBeInTheDocument();
  },
};

export const TheFieldListAppearsOnlyWithTheRequiredFieldsCheck: Story = {
  args: { initial: EMPTY_BASELINE },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByText("Required fields", { selector: "span" })).not.toBeInTheDocument();
    await userEvent.click(canvas.getByRole("checkbox", { name: "Required fields" }));
    await expect(args.onChange).toHaveBeenLastCalledWith(expect.objectContaining({ checks: ["traceability:required_fields"] }));
    await expect(await canvas.findByRole("button", { name: "Add required field" })).toBeInTheDocument();
  },
};

export const NeitherKindOfBaselineShowsTheRule: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("checkbox", { name: "Stage baseline" }));
    await userEvent.click(canvas.getByRole("checkbox", { name: "Manual baseline" }));
    await expect(canvas.getByRole("alert")).toHaveTextContent("Select at least one kind of baseline or approval");
  },
};

export const CheckingApprovalsAloneIsEnough: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("checkbox", { name: "Stage baseline" }));
    await userEvent.click(canvas.getByRole("checkbox", { name: "Manual baseline" }));
    const select = canvas.getByRole("combobox", { name: "Check record approvals" });
    await expect(select).toHaveValue("off");
    await expect(within(select).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "Off", "Manual approvals only", "Automated approvals only", "Manual and automated approvals",
    ]);
    await userEvent.selectOptions(select, "manual");
    await expect(args.onChange).toHaveBeenLastCalledWith(expect.objectContaining({ approval_checks: "manual" }));
    await expect(canvas.queryByRole("alert")).not.toBeInTheDocument();
  },
};

export const AddingARequiredFieldUsesADialog: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Add required field" }));
    const dialog = within(await within(document.body).findByRole("dialog", { name: "Add required field" }));
    await expect(dialog.getByRole("combobox", { name: "Field" })).toBeDisabled();
    await userEvent.selectOptions(dialog.getByRole("combobox", { name: "Record type" }), "risk");
    await userEvent.selectOptions(dialog.getByRole("combobox", { name: "Field" }), "statement");
    await userEvent.click(dialog.getByRole("button", { name: "Add" }));
    await expect(args.onChange).toHaveBeenLastCalledWith(expect.objectContaining({
      required_fields: [{ artefact_type: "requirement", field_key: "reasoning" }, { artefact_type: "risk", field_key: "statement" }],
    }));
    await expect(await canvas.findByText("Risk · Risk statement")).toBeInTheDocument();
  },
};

export const AFieldAlreadyRequiredIsNotOfferedAgain: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Add required field" }));
    const dialog = within(await within(document.body).findByRole("dialog", { name: "Add required field" }));
    await userEvent.selectOptions(dialog.getByRole("combobox", { name: "Record type" }), "requirement");
    await expect(dialog.queryByRole("option", { name: "Reasoning" })).not.toBeInTheDocument();
    await expect(dialog.getByRole("option", { name: "Owner" })).toBeInTheDocument();
  },
};

export const RemovingARequiredField: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Actions for Requirement · Reasoning" }));
    await userEvent.click(await within(document.body).findByRole("menuitem", { name: "Remove" }));
    await expect(args.onChange).toHaveBeenLastCalledWith(expect.objectContaining({ required_fields: [] }));
    await expect(await canvas.findByText("No fields are required.")).toBeInTheDocument();
  },
};

export const AFieldTheOptionsNoLongerHoldShowsItsKey: Story = {
  args: { initial: { ...FILLED_BASELINE, required_fields: [{ artefact_type: "risk", field_key: "custom_gone" }] } },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("Risk · custom_gone")).toBeInTheDocument();
  },
};

export const NoChecksAreAvailable: Story = {
  args: { initial: EMPTY_BASELINE, checks: [] },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("No baseline checks are available.")).toBeInTheDocument();
  },
};

export const LongText: Story = {
  render: (args) => <TextStress render={(long) => <Harness {...args} long={long} />} width={640} />,
  play: async ({ canvasElement }) => {
    await expectStressStable(canvasElement);
  },
};

export const DarkTheme: Story = { ...ShowsTheCurrentPolicy, globals: { theme: "dark" } };
