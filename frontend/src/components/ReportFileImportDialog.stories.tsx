import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, screen, userEvent, waitFor, within } from "storybook/test";

import { buildFileApi } from "../testing/reportFileFixtures";
import { requiredCaptions } from "../testing/requiredMarkers";
import { withToast } from "../testing/storybook-helpers";
import { ReportFileImportDialog } from "./ReportFileImportDialog";

/**
 * Imports a report file (made by Export as file) as the project's or organisation's own layouts and packs: choose the file
 * and how to settle a name already used, preview what would happen, then import. Nothing is replaced.
 */
const meta: Meta<typeof ReportFileImportDialog> = {
  title: "Components/Reports/ReportFileImportDialog",
  component: ReportFileImportDialog,
  decorators: [withToast()],
  args: { api: buildFileApi(), onClose: fn(), onImported: fn() },
};
export default meta;

type Story = StoryObj<typeof ReportFileImportDialog>;

const dialog = async () => within(await screen.findByRole("dialog", { name: "Import reports from a file" }));
const zip = () => new File(["zip"], "reports.zip", { type: "application/zip" });
const choose = async (d: ReturnType<typeof within>) => userEvent.upload(d.getByLabelText("Report file"), zip());

export const PreviewThenImport: Story = {
  args: { api: buildFileApi({ taken: ["Monthly status"], warnings: { "Board pack": ["Entries use layouts that are not in the file or here: Weekly."] }, pictures: 2 }) },
  play: async ({ args }) => {
    const d = await dialog();
    await expect(requiredCaptions(document.body)).toEqual(["Report file"]);
    await expect(d.getByRole("button", { name: "Preview" })).toBeDisabled();
    await choose(d);
    await userEvent.click(d.getByRole("button", { name: "Preview" }));
    await expect(await d.findByText("Monthly status → Monthly status (copy)")).toBeInTheDocument();
    await expect(d.getByText(/layouts that are not in the file or here: Weekly/)).toBeInTheDocument();
    await expect(d.getByText("2 picture(s) will be added to this project's library.")).toBeInTheDocument();
    await expect(args.api.importFile).toHaveBeenLastCalledWith(expect.any(File), { onConflict: "rename", dryRun: true });
    await userEvent.click(d.getByRole("button", { name: "Import 3 items" }));
    await expect(await d.findByRole("status")).toHaveTextContent("3 items imported.");
    await expect(args.api.importFile).toHaveBeenLastCalledWith(expect.any(File), { onConflict: "rename", dryRun: false });
    await expect(args.onImported).toHaveBeenCalled();
  },
};

export const SkippingATakenNameLeavesItOut: Story = {
  args: { api: buildFileApi({ taken: ["Monthly status"] }) },
  play: async ({ args }) => {
    const d = await dialog();
    await choose(d);
    await userEvent.selectOptions(d.getByRole("combobox", { name: /If a report with that name already exists/ }), "skip");
    await userEvent.click(d.getByRole("button", { name: "Preview" }));
    await expect(await d.findByText("Skip: name already used")).toBeInTheDocument();
    await expect(d.getByRole("button", { name: "Import 2 items" })).toBeInTheDocument();
    await expect(args.api.importFile).toHaveBeenLastCalledWith(expect.any(File), { onConflict: "skip", dryRun: true });
  },
};

export const ALayoutWithNoValidVersionIsListedAsLeftOut: Story = {
  args: { api: buildFileApi({ broken: ["Handover document"] }) },
  play: async () => {
    const d = await dialog();
    await choose(d);
    await userEvent.click(d.getByRole("button", { name: "Preview" }));
    await expect(await d.findByText("Cannot be imported")).toBeInTheDocument();
    await expect(d.getByText(/No version is valid here/)).toBeInTheDocument();
    await expect(d.getByRole("button", { name: "Import 2 items" })).toBeInTheDocument();
  },
};

export const ChangingTheNameRuleDiscardsThePreview: Story = {
  play: async () => {
    const d = await dialog();
    await choose(d);
    await userEvent.click(d.getByRole("button", { name: "Preview" }));
    await d.findByText("Handover document");
    await userEvent.selectOptions(d.getByRole("combobox", { name: /If a report with that name already exists/ }), "skip");
    await expect(d.queryByText("Handover document")).not.toBeInTheDocument();
    await expect(d.getByRole("button", { name: "Preview" })).toBeEnabled();
  },
};

export const AFileWithNothingImportableSaysSo: Story = {
  args: { api: buildFileApi({ layouts: [], packs: [] }) },
  play: async () => {
    const d = await dialog();
    await choose(d);
    await userEvent.click(d.getByRole("button", { name: "Preview" }));
    await expect(await d.findByText("Nothing in this file can be imported.")).toBeInTheDocument();
    await expect(d.getByRole("button", { name: "Import 0 items" })).toBeDisabled();
  },
};

export const ARefusedFileShowsTheError: Story = {
  args: { api: buildFileApi({ fail: "This is not a report file." }) },
  play: async () => {
    const d = await dialog();
    await choose(d);
    await userEvent.click(d.getByRole("button", { name: "Preview" }));
    await expect(await d.findByText("This is not a report file.")).toBeInTheDocument();
  },
};

export const CancelClosesWithoutImporting: Story = {
  play: async ({ args }) => {
    const d = await dialog();
    await userEvent.click(d.getByRole("button", { name: "Close" }));
    await waitFor(() => expect(args.onClose).toHaveBeenCalled());
    await expect(args.api.importFile).not.toHaveBeenCalled();
  },
};
