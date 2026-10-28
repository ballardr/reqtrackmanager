import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, fn, userEvent, within } from "storybook/test";

import type { LayoutChoice } from "../utils/reportPackDraft";
import { ReportPackEntriesEditor, type DraftEntry, type ReportChoice } from "./ReportPackEntriesEditor";

/** The Reports tab of the pack editor: layouts and module reports in order, each with format, file name and pinned values. */
const meta: Meta<typeof ReportPackEntriesEditor> = {
  title: "Components/Reports/ReportPackEntriesEditor",
  component: ReportPackEntriesEditor,
};
export default meta;

type Story = StoryObj<typeof ReportPackEntriesEditor>;

const layouts: LayoutChoice[] = [
  { name: "Requirements overview", family: "document" },
  { name: "Requirement rows", family: "table" },
];
const reports: ReportChoice[] = [{ module_key: "decisions", report: "d1", title: "Decisions: Decision register" }];

const initial: DraftEntry[] = [
  { uid: "a", entry: { kind: "layout", name: "Requirements overview", format: "pdf", filename: "overview", variables: { categories: ["Security"] } } },
  { uid: "b", entry: { kind: "report", module_key: "decisions", report: "d1", format: "csv" } },
];

function Harness({ onChange, inProject = true, disabled = false, start = initial }: {
  onChange?: (next: DraftEntry[]) => void; inProject?: boolean; disabled?: boolean; start?: DraftEntry[];
}) {
  const [entries, setEntries] = useState(start);
  return (
    <ReportPackEntriesEditor
      entries={entries} layouts={layouts} reports={reports} inProject={inProject} disabled={disabled}
      onChange={(next) => { setEntries(next); onChange?.(next); }}
    />
  );
}

export const ListsEachReportWithItsOptions: Story = {
  render: () => <Harness />,
  play: async ({ canvasElement }) => {
    const first = within(await within(canvasElement).findByRole("region", { name: "Report 1" }));
    await expect(first.getByRole("combobox", { name: /^Layout/ })).toHaveValue("Requirements overview");
    await expect(first.getByRole("combobox", { name: "Which layout" })).toBeInTheDocument();
    await expect(first.getByRole("textbox", { name: "File name" })).toHaveValue("overview");
    await expect(first.getByRole("textbox", { name: "Fixed values (JSON)" })).toHaveValue('{"categories":["Security"]}');
    const second = within(await within(canvasElement).findByRole("region", { name: "Report 2" }));
    await expect(second.getByRole("combobox", { name: /^Report/ })).toHaveValue("decisions|d1");
    await expect(second.getByRole("textbox", { name: "Report options (JSON)" })).toBeInTheDocument();
  },
};

export const AnOrganisationPackHasNoOwnerTier: Story = {
  render: () => <Harness inProject={false} />,
  play: async ({ canvasElement }) => {
    const first = within(await within(canvasElement).findByRole("region", { name: "Report 1" }));
    await expect(first.queryByRole("combobox", { name: "Which layout" })).not.toBeInTheDocument();
  },
};

export const ChoosingATableLayoutOffersItsFormats: Story = {
  render: () => <Harness />,
  play: async ({ canvasElement }) => {
    const first = within(await within(canvasElement).findByRole("region", { name: "Report 1" }));
    await userEvent.selectOptions(first.getByRole("combobox", { name: /^Layout/ }), "Requirement rows");
    const format = first.getByRole("combobox", { name: /^Format/ });
    await expect(within(format).getAllByRole("option").map((o) => o.textContent)).toEqual(["CSV", "Excel workbook", "OpenDocument spreadsheet"]);
    await expect(format).toHaveValue("csv");
  },
};

export const ReorderingKeepsEachBoxWithItsReport: Story = {
  render: () => <Harness />,
  play: async ({ canvasElement }) => {
    await userEvent.click(within(await within(canvasElement).findByRole("region", { name: "Report 2" })).getByRole("button", { name: "Move up" }));
    const first = within(await within(canvasElement).findByRole("region", { name: "Report 1" }));
    await expect(first.getByRole("combobox", { name: /^Report/ })).toHaveValue("decisions|d1");
    const second = within(await within(canvasElement).findByRole("region", { name: "Report 2" }));
    await expect(second.getByRole("textbox", { name: "Fixed values (JSON)" })).toHaveValue('{"categories":["Security"]}');
  },
};

export const AddingAndRemovingEntries: Story = {
  render: () => <Harness start={[]} />,
  play: async ({ canvasElement }) => {
    const view = within(canvasElement);
    await expect(await view.findByText("No reports in this pack yet.")).toBeInTheDocument();
    await userEvent.click(view.getByRole("button", { name: "Add a layout" }));
    await userEvent.click(view.getByRole("button", { name: "Add a module report" }));
    await expect(view.getByRole("region", { name: "Report 2" })).toBeInTheDocument();
    await userEvent.click(within(view.getByRole("region", { name: "Report 1" })).getByRole("button", { name: "Remove report" }));
    await expect(view.queryByRole("region", { name: "Report 2" })).not.toBeInTheDocument();
  },
};

export const ASharedPackIsReadOnly: Story = {
  render: () => <Harness disabled onChange={fn()} />,
  play: async ({ canvasElement }) => {
    const view = within(canvasElement);
    const first = within(await view.findByRole("region", { name: "Report 1" }));
    await expect(first.getByRole("combobox", { name: /^Format/ })).toBeDisabled();
    await expect(view.queryByRole("button", { name: "Add a layout" })).not.toBeInTheDocument();
    await expect(view.queryByRole("button", { name: "Remove report" })).not.toBeInTheDocument();
  },
};
