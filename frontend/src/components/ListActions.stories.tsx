import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { buildImportResult, buildRecordColumns, failing, fakeRecordTables, inSequence } from "../testing/recordTablesFixtures";
import { ListActions } from "./ListActions";

const meta: Meta<typeof ListActions> = {
  title: "Components/ListActions",
  component: ListActions,
  args: {
    projectId: "project-1",
    recordType: "requirement",
    filters: "status=draft&tag=safety&tag_mode=any",
    onImported: fn(),
    tables: fakeRecordTables(),
  },
};
export default meta;

type Story = StoryObj<typeof ListActions>;

/** The Export menu downloads the list with the page's own filters, not the full set. */
export const ExportSendsThePagesFilters: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Export" }));
    const menu = within(within(document.body).getByRole("dialog", { name: "Export" }));
    await userEvent.click(menu.getByRole("button", { name: "Download CSV report" }));
    await waitFor(() =>
      expect(args.tables!.exportCsv).toHaveBeenCalledWith("project-1", "requirement", "status=draft&tag=safety&tag_mode=any"),
    );
    await expect(await within(document.body).findByText("Requirements exported as CSV.")).toBeInTheDocument();
  },
};

/** A failed download is reported, not swallowed. */
export const AFailedExportIsReported: Story = {
  args: { tables: fakeRecordTables({ exportCsv: failing("Server unavailable.") }) },
  play: async ({ canvasElement }) => {
    await userEvent.click(await within(canvasElement).findByRole("button", { name: "Export" }));
    await userEvent.click(within(document.body).getByRole("button", { name: "Download CSV report" }));
    await expect(await within(document.body).findByText("Server unavailable.")).toBeInTheDocument();
  },
};

/** The import template is the importable columns, `code` first, under the export formats. */
export const TheMenuOffersTheImportTemplate: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.click(await within(canvasElement).findByRole("button", { name: "Export" }));
    const menu = within(within(document.body).getByRole("dialog", { name: "Export" }));
    await expect(menu.getByRole("button", { name: "Download import template" })).toBeInTheDocument();
  },
};

/** Picking a file opens the wizard, and a finished import tells the page to reload. */
export const ImportOpensTheWizardAndReloadsTheList: Story = {
  args: {
    tables: fakeRecordTables({
      importFile: inSequence(
      buildImportResult({ created: 1, rows: [{ row: 2, action: "create", code: "", changes: [], message: "" }] }),
      buildImportResult({ applied: true, created: 1 }),
    ),
    }),
  },
  play: async ({ canvasElement, args }) => {
    await within(canvasElement).findByRole("button", { name: "Export" });
    const input = canvasElement.querySelector('input[type="file"][accept=".csv,text/csv"]') as HTMLInputElement;
    await userEvent.upload(input, new File(["name,component,category\nA,AUTH,LOG\n"], "in.csv", { type: "text/csv" }));
    const modal = within(await within(document.body).findByRole("dialog", { name: "Import Requirements" }));
    await waitFor(() => expect(modal.getByRole("button", { name: "Preview" })).toBeEnabled());
    await userEvent.click(modal.getByRole("button", { name: "Preview" }));
    await userEvent.click(await modal.findByRole("button", { name: "Apply 1 change(s)" }));
    await waitFor(() => expect(args.onImported).toHaveBeenCalledOnce());
  },
};

/** A person who may not create or update records is not offered Import (or the template) at all. */
export const NoImportWithoutPermission: Story = {
  args: { tables: fakeRecordTables({}, buildRecordColumns({ can_import: false })) },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Export" }));
    await expect(canvas.queryByText("Import")).not.toBeInTheDocument();
    await expect(within(document.body).queryByRole("button", { name: "Download import template" })).not.toBeInTheDocument();
  },
};

/** A type that gives a reason it cannot be imported is exported only. */
export const AnExportOnlyTypeHidesImport: Story = {
  args: {
    tables: fakeRecordTables({}, buildRecordColumns({ importable: false, can_import: false, not_importable_reason: "Produced by a workflow." })),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("button", { name: "Export" });
    await expect(canvas.queryByText("Import")).not.toBeInTheDocument();
  },
};

/** Columns the personal-data policy left out are named in one line in the Export menu. */
export const OmittedColumnsAreNoted: Story = {
  args: {
    tables: fakeRecordTables({}, buildRecordColumns({ omitted_sensitivity: ["contact"], omitted_reasons: { contact: "policy" } })),
  },
  play: async ({ canvasElement }) => {
    await userEvent.click(await within(canvasElement).findByRole("button", { name: "Export" }));
    await expect(
      within(document.body).getByText("Some columns holding personal data are left out by your organisation's policy."),
    ).toBeInTheDocument();
  },
};

/** A type with no table (or no right to see it) shows no controls rather than broken ones. */
export const NothingWhenTheTypeHasNoTable: Story = {
  args: { tables: fakeRecordTables({ columns: failing("Record type not found.") }) },
  play: async ({ canvasElement, args }) => {
    await waitFor(() => expect(args.tables!.columns).toHaveBeenCalled());
    await expect(within(canvasElement).queryByRole("button", { name: "Export" })).not.toBeInTheDocument();
  },
};

export const LightTheme: Story = { globals: { theme: "light" } };
export const DarkTheme: Story = { globals: { theme: "dark" } };
