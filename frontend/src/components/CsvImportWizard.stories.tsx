import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import {
  buildImportResult,
  buildRecordColumns,
  failing,
  fakeRecordTables,
  inSequence,
} from "../testing/recordTablesFixtures";
import { CsvImportWizard } from "./CsvImportWizard";

const csvFile = (text: string) => new File([text], "requirements.csv", { type: "text/csv" });

const meta: Meta<typeof CsvImportWizard> = {
  title: "Components/CsvImportWizard",
  component: CsvImportWizard,
  args: {
    projectId: "project-1",
    recordType: "requirement",
    columns: buildRecordColumns(),
    file: csvFile("name,component,category\nReset password,AUTH,LOG\n"),
    onClose: fn(),
    onApplied: fn(),
    tables: fakeRecordTables(),
  },
};
export default meta;

type Story = StoryObj<typeof CsvImportWizard>;

const dialog = () => within(document.body).getByRole("dialog", { name: "Import Requirements" });

/** A file whose headers are the server's own keys maps by itself, so the required columns are met and Preview is open. */
export const AutoMapsMatchingHeaders: Story = {
  play: async () => {
    await waitFor(() => expect(dialog()).toBeInTheDocument());
    const modal = within(dialog());
    await waitFor(() => expect(modal.getByLabelText("Map Name")).toHaveValue("name"));
    await expect(modal.getByLabelText("Map Component")).toHaveValue("component");
    await expect(modal.queryByText(/still need a column/)).not.toBeInTheDocument();
    await expect(modal.getByRole("button", { name: "Preview" })).toBeEnabled();
  },
};

/** Headers that match nothing leave the required columns unmapped: Preview stays blocked and says which. */
export const UnmatchedHeadersBlockThePreview: Story = {
  args: { file: csvFile("title,area\nReset password,AUTH\n") },
  play: async () => {
    await waitFor(() => expect(dialog()).toBeInTheDocument());
    const modal = within(dialog());
    await waitFor(() => expect(modal.getByText(/Name, Component, Category still need/)).toBeInTheDocument());
    await expect(modal.getByRole("button", { name: "Preview" })).toBeDisabled();
  },
};

/** A Code column names the records to update, so required columns are no longer needed for a file of updates only. */
export const ACodeColumnLiftsTheRequiredColumns: Story = {
  args: { file: csvFile("code,level\nSW-001,Optional\n") },
  play: async () => {
    await waitFor(() => expect(dialog()).toBeInTheDocument());
    const modal = within(dialog());
    await waitFor(() => expect(modal.getByLabelText("Map Code")).toHaveValue("code"));
    await expect(modal.queryByText(/still need a column/)).not.toBeInTheDocument();
    await expect(modal.getByRole("button", { name: "Preview" })).toBeEnabled();
  },
};

/** A column with a closed list can be given one value for every row; the file sent has it on each row. */
export const FixedValueIsWrittenOnEveryRow: Story = {
  args: { file: csvFile("name\nFirst\nSecond\n") },
  play: async ({ args }) => {
    await waitFor(() => expect(dialog()).toBeInTheDocument());
    const modal = within(dialog());
    await waitFor(() => expect(modal.getByLabelText("Map Name")).toHaveValue("name"));
    await expect(modal.getByRole("button", { name: "Preview" })).toBeDisabled();
    await userEvent.click(modal.getByLabelText("Use the same component for every row"));
    await userEvent.selectOptions(modal.getByLabelText("Fixed component"), "AUTH");
    await userEvent.click(modal.getByLabelText("Use the same category for every row"));
    await userEvent.selectOptions(modal.getByLabelText("Fixed category"), "LOG");
    await userEvent.click(modal.getByLabelText("Use the same level for every row"));
    await userEvent.selectOptions(modal.getByLabelText("Fixed level"), "Optional");
    await userEvent.click(modal.getByRole("button", { name: "Preview" }));
    await waitFor(() => expect(args.tables!.importFile).toHaveBeenCalledOnce());
    const [, , sent, dryRun] = (args.tables!.importFile as ReturnType<typeof fn>).mock.calls[0] as [string, string, File, boolean];
    await expect(dryRun).toBe(true);
    const lines = (await sent.text()).trim().split(/\r?\n/);
    await expect(lines[0]).toBe("name,component,category,level");
    await expect(lines.slice(1)).toEqual(["First,AUTH,LOG,Optional", "Second,AUTH,LOG,Optional"]);
  },
};

const previewWithUpdatesAndErrors = buildImportResult({
  created: 1, updated: 1, unchanged: 0, failed: 1,
  rows: [
    { row: 2, action: "create", code: "", changes: [], message: "" },
    {
      row: 3, action: "update", code: "SW-002", message: "",
      changes: [{ column: "level", label: "Level", before: "Requirement", after: "Optional" }],
    },
    { row: 4, action: "error", code: "SW-099", changes: [], message: "No record SW-099 in this project." },
  ],
  ignored_columns: { notes: "Not a column of this table." },
});

/** The preview lists what would change, with before and after, plus row errors, and writes nothing until Apply. */
export const PreviewListsUpdatesAndErrors: Story = {
  args: { tables: fakeRecordTables({ importFile: fn(async () => previewWithUpdatesAndErrors) }) },
  play: async ({ args }) => {
    await waitFor(() => expect(dialog()).toBeInTheDocument());
    const modal = within(dialog());
    await waitFor(() => expect(modal.getByRole("button", { name: "Preview" })).toBeEnabled());
    await userEvent.click(modal.getByRole("button", { name: "Preview" }));
    await waitFor(() => expect(modal.getByText("1 to create, 1 to update, 0 unchanged, 1 with errors.")).toBeInTheDocument());
    await expect(modal.getByText("SW-002")).toBeInTheDocument();
    await expect(modal.getByText("Optional")).toBeInTheDocument();
    await expect(modal.getByText("Row 4: No record SW-099 in this project.")).toBeInTheDocument();
    await expect(modal.getByText(/notes: Not a column of this table\./)).toBeInTheDocument();
    await expect(args.tables!.importFile).toHaveBeenCalledTimes(1);
    await expect(modal.getByRole("button", { name: "Apply 2 change(s)" })).toBeEnabled();
    await userEvent.click(modal.getByRole("button", { name: "Back" }));
    await expect(modal.getByRole("button", { name: "Preview" })).toBeInTheDocument();
  },
};

/** A preview with nothing to write leaves Apply disabled and says so. */
export const NothingToApplyDisablesApply: Story = {
  args: { tables: fakeRecordTables({ importFile: fn(async () => buildImportResult({ unchanged: 1 })) }) },
  play: async () => {
    await waitFor(() => expect(dialog()).toBeInTheDocument());
    const modal = within(dialog());
    await waitFor(() => expect(modal.getByRole("button", { name: "Preview" })).toBeEnabled());
    await userEvent.click(modal.getByRole("button", { name: "Preview" }));
    await waitFor(() => expect(modal.getByText("There is nothing to apply.")).toBeInTheDocument());
    await expect(modal.getByRole("button", { name: "Apply 0 change(s)" })).toBeDisabled();
  },
};

/** Apply sends the same file for real, reports in a toast, tells the list to reload and closes. */
export const ApplyWritesReportsAndCloses: Story = {
  args: {
    tables: fakeRecordTables({
      importFile: inSequence(
      buildImportResult({ created: 1, rows: [{ row: 2, action: "create", code: "", changes: [], message: "" }] }),
      buildImportResult({ applied: true, created: 1 }),
    ),
    }),
  },
  play: async ({ args }) => {
    await waitFor(() => expect(dialog()).toBeInTheDocument());
    const modal = within(dialog());
    await waitFor(() => expect(modal.getByRole("button", { name: "Preview" })).toBeEnabled());
    await userEvent.click(modal.getByRole("button", { name: "Preview" }));
    await userEvent.click(await modal.findByRole("button", { name: "Apply 1 change(s)" }));
    await waitFor(() => expect(args.onApplied).toHaveBeenCalledOnce());
    await expect(args.onClose).toHaveBeenCalledOnce();
    const calls = (args.tables!.importFile as ReturnType<typeof fn>).mock.calls;
    await expect(calls.map((c) => c[3])).toEqual([true, false]);
    await expect(await within(document.body).findByText("1 created, 0 updated, 0 failed.")).toBeInTheDocument();
  },
};

/** Failed rows stay open with a way to get them back as a file to fix. */
export const FailedRowsOfferAnErrorFile: Story = {
  args: {
    tables: fakeRecordTables({
      importFile: inSequence(
      buildImportResult({ created: 1, failed: 1 }),
      buildImportResult({
          applied: true, created: 1, failed: 1, error_csv: "code,name,error\n,Bad,Unknown component.\n",
          rows: [{ row: 3, action: "error", code: "", changes: [], message: "Unknown component 'ZZZ'." }],
        }),
    ),
    }),
  },
  play: async ({ args }) => {
    await waitFor(() => expect(dialog()).toBeInTheDocument());
    const modal = within(dialog());
    await waitFor(() => expect(modal.getByRole("button", { name: "Preview" })).toBeEnabled());
    await userEvent.click(modal.getByRole("button", { name: "Preview" }));
    await userEvent.click(await modal.findByRole("button", { name: "Apply 1 change(s)" }));
    await expect(await modal.findByText("Row 3: Unknown component 'ZZZ'.")).toBeInTheDocument();
    await expect(modal.getByRole("button", { name: "Download error file" })).toBeEnabled();
    await expect(args.onClose).not.toHaveBeenCalled();
    // The dialog's own ✕ is also named "Close"; the text button is the one in the header actions.
    const textClose = modal.getAllByRole("button", { name: "Close" }).find((b) => b.textContent === "Close")!;
    await userEvent.click(textClose);
    await expect(args.onClose).toHaveBeenCalledOnce();
  },
};

/** A server error on the preview stays on the mapping step and is shown, so nothing is lost. */
export const APreviewErrorIsShown: Story = {
  args: { tables: fakeRecordTables({ importFile: failing("The file is not a CSV.") }) },
  play: async () => {
    await waitFor(() => expect(dialog()).toBeInTheDocument());
    const modal = within(dialog());
    await waitFor(() => expect(modal.getByRole("button", { name: "Preview" })).toBeEnabled());
    await userEvent.click(modal.getByRole("button", { name: "Preview" }));
    await expect(await modal.findByText("The file is not a CSV.")).toBeInTheDocument();
    await expect(modal.getByRole("button", { name: "Preview" })).toBeEnabled();
  },
};

/** A file over the row cap is refused before anything is sent. */
export const TooManyRowsBlocksThePreview: Story = {
  args: { columns: buildRecordColumns({ max_rows: 1 }), file: csvFile("name,component,category\nA,AUTH,LOG\nB,AUTH,LOG\n") },
  play: async () => {
    await waitFor(() => expect(dialog()).toBeInTheDocument());
    const modal = within(dialog());
    await waitFor(() => expect(modal.getByText(/more than 1 rows/)).toBeInTheDocument());
    await expect(modal.getByRole("button", { name: "Preview" })).toBeDisabled();
  },
};

/** Columns the personal-data policy leaves out are not offered, and the person is told. */
export const PolicyOmittedColumnsAreNotOffered: Story = {
  args: {
    columns: buildRecordColumns({
      omitted_sensitivity: ["contact"], omitted_reasons: { contact: "policy" },
      columns: buildRecordColumns().columns.map((c) => (c.key === "owner" ? { ...c, included: false, sensitivity: "contact" } : c)),
    }),
  },
  play: async () => {
    await waitFor(() => expect(dialog()).toBeInTheDocument());
    const modal = within(dialog());
    await waitFor(() => expect(modal.getByLabelText("Map Name")).toBeInTheDocument());
    await expect(modal.queryByLabelText("Map Owner")).not.toBeInTheDocument();
    await expect(modal.getByText(/left out by your organisation's policy/)).toBeInTheDocument();
  },
};

export const LightTheme: Story = { globals: { theme: "light" } };
export const DarkTheme: Story = { globals: { theme: "dark" } };
