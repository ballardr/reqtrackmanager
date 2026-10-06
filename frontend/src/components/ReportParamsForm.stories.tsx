import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import type { ReportParam } from "../api/reports";
import { buildReportCatalogueEntry } from "../testing/reportFixtures";
import { ReportParamsForm } from "./ReportParamsForm";

const params: ReportParam[] = [
  ...buildReportCatalogueEntry().params,
  { name: "since", type: "date", default: null, choices: null, minimum: null, maximum: null, description: "Earliest date." },
  { name: "include_detail", type: "boolean", default: false, choices: null, minimum: null, maximum: null, description: "" },
  { name: "standard_id", type: "uuid", default: null, choices: null, minimum: null, maximum: null, description: "" },
];

const meta: Meta<typeof ReportParamsForm> = {
  title: "Components/Reports/ReportParamsForm",
  component: ReportParamsForm,
  args: { params, values: { rollup: "weighted_average", stale_months: 6 }, onChange: fn(), supportsIncludeChildren: true },
};
export default meta;

type Story = StoryObj<typeof ReportParamsForm>;

/** Every declared type gets a labelled control; choices are humanised, never the raw wire value. */
export const ControlPerParameterType: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const rollup = canvas.getByLabelText("Rollup");
    await expect(rollup).toHaveValue("weighted_average");
    await expect(within(rollup).getByRole("option", { name: "Worst case" })).toBeInTheDocument();
    await expect(canvas.getByLabelText("Stale months")).toHaveAttribute("min", "1");
    await expect(canvas.getByLabelText("Stale months")).toHaveAttribute("max", "120");
    await expect(canvas.getByLabelText("Since")).toHaveAttribute("type", "date");
    await expect(canvas.getByRole("switch", { name: "Include detail" })).toBeInTheDocument();
    await expect(canvas.getByLabelText("Standard id")).toBeInTheDocument();
    await expect(canvas.getByRole("switch", { name: "Include child projects" })).toBeInTheDocument();
  },
};

export const ChangesReportValues: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.selectOptions(canvas.getByLabelText("Rollup"), "worst_case");
    await expect(args.onChange).toHaveBeenCalledWith("rollup", "worst_case");
    await userEvent.click(canvas.getByRole("switch", { name: "Include child projects" }));
    await expect(args.onChange).toHaveBeenCalledWith("include_children", true);
    await userEvent.type(canvas.getByLabelText("Since"), "2026-01-31");
    await expect(args.onChange).toHaveBeenCalledWith("since", "2026-01-31");
  },
};

/** Declared labels win over the humanised identifier, for the control and for each choice. */
export const UsesDeclaredLabels: Story = {
  args: {
    params: [{
      name: "model_key", type: "string", default: null, choices: ["sxf", "sxc"], minimum: null, maximum: null,
      description: "", label: "Scoring model", choice_labels: { sxf: "Severity × Frequency" },
    }],
    values: {},
  },
  play: async ({ canvasElement }) => {
    const select = within(canvasElement).getByLabelText("Scoring model");
    await expect(within(select).getByRole("option", { name: "Severity × Frequency" })).toBeInTheDocument();
    await expect(within(select).getByRole("option", { name: "Sxc" })).toBeInTheDocument();
  },
};

/** A parameter a custom view draws its own control for is not drawn twice. */
export const HidesParametersOwnedByAView: Story = {
  args: { hidden: ["rollup", "stale_months"] },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByLabelText("Rollup")).not.toBeInTheDocument();
    await expect(canvas.queryByLabelText("Stale months")).not.toBeInTheDocument();
    await expect(canvas.getByLabelText("Since")).toBeInTheDocument();
  },
};

/** An organisation-wide report offers a Project picker; blank means "All projects" and sends no filter. */
export const ProjectPickerNarrowsAnOrganisationReport: Story = {
  args: {
    params: [],
    supportsIncludeChildren: false,
    projectOptions: [{ value: "project-1", label: "Atlas" }, { value: "project-2", label: "Borealis" }],
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const picker = canvas.getByLabelText("Project");
    await expect(picker).toHaveValue("");
    await expect(within(picker).getByRole("option", { name: "All projects" })).toBeInTheDocument();
    await userEvent.selectOptions(picker, "project-2");
    await expect(args.onChange).toHaveBeenCalledWith("project_id", "project-2");
    await userEvent.selectOptions(picker, "");
    await expect(args.onChange).toHaveBeenCalledWith("project_id", null);
  },
};

export const NothingToConfigureRendersNothing: Story = {
  args: { params: [], supportsIncludeChildren: false },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).queryByRole("group")).not.toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...ControlPerParameterType, globals: { theme: "light" } };
export const DarkTheme: Story = { ...ControlPerParameterType, globals: { theme: "dark" } };
