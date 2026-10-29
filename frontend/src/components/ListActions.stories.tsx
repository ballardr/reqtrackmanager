import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, screen, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import { buildReportCatalogueEntry } from "../testing/reportFixtures";
import { buildUser, withRouter, withStatefulAuth } from "../testing/storybook-helpers";

import { buildImportResult, buildRecordColumns, failing, fakeRecordTables, inSequence } from "../testing/recordTablesFixtures";
import { chooseListAction, openListMenu, chooseExport } from "../testing/listActionsMenu";
import { ListActions, ListActionsMenu } from "./ListActions";

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

/** The List actions menu downloads the list with the page's own filters, not the full set. */
export const ExportSendsThePagesFilters: Story = {
  play: async ({ canvasElement, args }) => {
    await chooseExport(within(canvasElement), "CSV");
    await waitFor(() =>
      expect(args.tables!.exportFile).toHaveBeenCalledWith({ projectId: "project-1" }, "requirement", "csv", "status=draft&tag=safety&tag_mode=any"),
    );
    await expect(await within(document.body).findByText("Requirements exported as CSV.")).toBeInTheDocument();
  },
};

/** The export and import actions are one kebab menu, not separate Export and Import buttons. */
export const TheActionsShareOneBurgerMenu: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("button", { name: "List actions" })).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Export" })).not.toBeInTheDocument();
    await expect(canvas.queryByText("Import")).not.toBeInTheDocument();
    const menu = await openListMenu(canvas);
    for (const name of ["Download report", "Download shown items", "Download import template", "Import from CSV"]) {
      await expect(menu.getByRole("menuitem", { name })).toBeInTheDocument();
    }
    // The formats are one level down, not flat in the menu.
    await expect(menu.queryByRole("menuitem", { name: /^CSV/ })).not.toBeInTheDocument();
  },
};

/** Download shown items lists CSV (with its re-import hint), PDF, Word, ODT and ODS, each with its full name as a tooltip. */
export const DownloadShownItemsListsEveryFormat: Story = {
  play: async ({ canvasElement }) => {
    const menu = await openListMenu(within(canvasElement));
    const parent = menu.getByRole("menuitem", { name: "Download shown items" });
    await expect(parent).toHaveAttribute("aria-haspopup", "menu");
    await expect(parent).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(parent);
    await expect(parent).toHaveAttribute("aria-expanded", "true");
    const submenu = within(await within(document.body).findByRole("menu", { name: "Download shown items" }));
    const names = submenu.getAllByRole("menuitem").map((item) => item.textContent?.trim());
    await expect(names).toEqual(["CSVre-imports", "PDF", "Word", "ODT", "ODS"]);
    await expect(submenu.getByRole("menuitem", { name: "ODT" })).toHaveAttribute("title", "OpenDocument text");
    await expect(submenu.getByRole("menuitem", { name: "ODS" })).toHaveAttribute("title", "OpenDocument spreadsheet");
  },
};

/** The pointer resting on the parent opens the submenu (after a short delay) without a click. */
export const HoveringTheParentOpensTheSubmenu: Story = {
  play: async ({ canvasElement }) => {
    const menu = await openListMenu(within(canvasElement));
    await userEvent.hover(menu.getByRole("menuitem", { name: "Download shown items" }));
    await expect(await within(document.body).findByRole("menu", { name: "Download shown items" })).toBeInTheDocument();
  },
};

/** The keyboard opens the submenu with Right, moves with Down, and Escape closes only the submenu (the menu stays). */
export const TheKeyboardOpensAndLeavesTheSubmenu: Story = {
  play: async ({ canvasElement }) => {
    const menu = await openListMenu(within(canvasElement));
    menu.getByRole("menuitem", { name: "Download report" }).focus();
    await userEvent.keyboard("{ArrowDown}");
    await expect(menu.getByRole("menuitem", { name: "Download shown items" })).toHaveFocus();
    await userEvent.keyboard("{ArrowRight}");
    const submenu = within(await within(document.body).findByRole("menu", { name: "Download shown items" }));
    await waitFor(() => expect(submenu.getByRole("menuitem", { name: /^CSV/ })).toHaveFocus());
    await userEvent.keyboard("{ArrowDown}");
    await expect(submenu.getByRole("menuitem", { name: "PDF" })).toHaveFocus();
    await userEvent.keyboard("{Escape}");
    await expect(within(document.body).queryByRole("menu", { name: "Download shown items" })).not.toBeInTheDocument();
    await expect(menu.getByRole("menuitem", { name: "Download shown items" })).toHaveFocus();
    await expect(within(document.body).getByRole("dialog", { name: "List actions" })).toBeInTheDocument();
    await userEvent.keyboard("{ArrowRight}{ArrowLeft}");
    await expect(menu.getByRole("menuitem", { name: "Download shown items" })).toHaveFocus();
  },
};

/** On a narrow screen (touch) the submenu opens inline beneath its parent, and a tap on a format downloads. */
export const OnANarrowScreenTheSubmenuOpensInline: Story = {
  beforeEach: () => {
    // The submenu places itself from the window width, so narrow the window it reads.
    const original = window.innerWidth;
    Object.defineProperty(window, "innerWidth", { value: 500, configurable: true });
    return () => {
      Object.defineProperty(window, "innerWidth", { value: original, configurable: true });
    };
  },
  play: async ({ canvasElement, args }) => {
    const menu = await openListMenu(within(canvasElement));
    await userEvent.click(menu.getByRole("menuitem", { name: "Download shown items" }));
    const list = await within(document.body).findByRole("menu", { name: "Download shown items" });
    await expect(getComputedStyle(list).position).toBe("static");
    await userEvent.click(within(list).getByRole("menuitem", { name: "ODS" }));
    await waitFor(() => expect(args.tables!.exportFile).toHaveBeenCalled());
  },
};

/** An organisation's own list exports through the organisation owner, with the same filters. */
export const AnOrganisationListExportsItsOwnRecords: Story = {
  args: { projectId: undefined, organizationId: "org-1", recordType: "strategy", filters: "status=draft" },
  play: async ({ canvasElement, args }) => {
    await chooseExport(within(canvasElement), "CSV");
    await waitFor(() =>
      expect(args.tables!.exportFile).toHaveBeenCalledWith({ organizationId: "org-1" }, "strategy", "csv", "status=draft"),
    );
    await waitFor(() => expect(args.tables!.columns).toHaveBeenCalledWith({ organizationId: "org-1" }, "strategy"));
  },
};

/** PDF, Word, ODT and ODS come from the record-list report and carry the same filters as the CSV. */
export const EveryReportFormatCarriesTheSameFilters: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await chooseExport(canvas, "PDF");
    await waitFor(() =>
      expect(args.tables!.exportFile).toHaveBeenCalledWith({ projectId: "project-1" }, "requirement", "pdf", "status=draft&tag=safety&tag_mode=any"),
    );
    await expect(await within(document.body).findByText("Requirements exported as PDF.")).toBeInTheDocument();
    await chooseExport(canvas, "Word");
    await waitFor(() =>
      expect(args.tables!.exportFile).toHaveBeenCalledWith({ projectId: "project-1" }, "requirement", "docx", "status=draft&tag=safety&tag_mode=any"),
    );
    await expect(await within(document.body).findByText("Requirements exported as Word.")).toBeInTheDocument();
    for (const [format, kind] of [["ODT", "odt"], ["ODS", "ods"]] as const) {
      await chooseExport(canvas, format);
      await waitFor(() =>
        expect(args.tables!.exportFile).toHaveBeenCalledWith({ projectId: "project-1" }, "requirement", kind, "status=draft&tag=safety&tag_mode=any"),
      );
      await expect(await within(document.body).findByText(`Requirements exported as ${format}.`)).toBeInTheDocument();
    }
  },
};

/** A failed download is reported, not swallowed. */
export const AFailedExportIsReported: Story = {
  args: { tables: fakeRecordTables({ exportFile: failing("Server unavailable.") }) },
  play: async ({ canvasElement }) => {
    await chooseExport(within(canvasElement), "CSV");
    await expect(await within(document.body).findByText("Server unavailable.")).toBeInTheDocument();
  },
};

/** The import template is the importable columns, `code` first, in the same menu as the export formats. */
export const TheMenuOffersTheImportTemplate: Story = {
  play: async ({ canvasElement }) => {
    const menu = await openListMenu(within(canvasElement));
    await expect(menu.getByRole("menuitem", { name: "Download import template" })).toBeInTheDocument();
  },
};

/** Choosing Import from CSV opens the file picker; the chosen file opens the wizard, and a finished import tells the page to reload. */
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
    await within(canvasElement).findByRole("button", { name: "List actions" });
    const input = canvasElement.querySelector('input[type="file"][accept=".csv,text/csv"]') as HTMLInputElement;
    const picked = fn();
    input.addEventListener("click", picked);
    await chooseListAction(within(canvasElement), "Import from CSV");
    await expect(picked).toHaveBeenCalledOnce();
    await userEvent.upload(input, new File(["name,component,category\nA,AUTH,LOG\n"], "in.csv", { type: "text/csv" }));
    const modal = within(await within(document.body).findByRole("dialog", { name: "Import Requirements" }));
    await waitFor(() => expect(modal.getByRole("button", { name: "Preview" })).toBeEnabled());
    await userEvent.click(modal.getByRole("button", { name: "Preview" }));
    await userEvent.click(await modal.findByRole("button", { name: "Apply 1 change(s)" }));
    await waitFor(() => expect(args.onImported).toHaveBeenCalledOnce());
  },
};

/** Download report opens the picker of the reports that use the list's record type. */
export const DownloadReportOffersTheReportsForTheType: Story = {
  decorators: [withRouter("/projects/project-1/requirements", "/projects/:projectId/requirements"), withStatefulAuth(buildUser({ ui_preferences: {} }))],
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => (path.endsWith("/report-catalogue")
      ? [
        buildReportCatalogueEntry({ slug: "requirement-coverage", title: "Requirement coverage", record_types: ["requirement"] }),
        buildReportCatalogueEntry({ slug: "engagement-yield", title: "Engagement yield", record_types: ["engagement"] }),
      ]
      : []));
  },
  play: async ({ canvasElement }) => {
    await chooseListAction(within(canvasElement), "Download report");
    const dialog = within(await screen.findByRole("dialog", { name: "Download report" }));
    // Folders start collapsed the first time a picker is opened.
    await userEvent.click(await dialog.findByRole("button", { name: "Expand Fixture Module" }));
    await expect(await dialog.findByRole("button", { name: /^Requirement coverage/ })).toBeInTheDocument();
    await expect(dialog.queryByText(/Engagement yield/)).not.toBeInTheDocument();
  },
};

/** A person who may not create or update records is not offered Import (or the template) at all. */
export const NoImportWithoutPermission: Story = {
  args: { tables: fakeRecordTables({}, buildRecordColumns({ can_import: false })) },
  play: async ({ canvasElement }) => {
    const menu = await openListMenu(within(canvasElement));
    await expect(menu.getByRole("menuitem", { name: "Download shown items" })).toBeInTheDocument();
    await expect(menu.queryByRole("menuitem", { name: "Import from CSV" })).not.toBeInTheDocument();
    await expect(menu.queryByRole("menuitem", { name: "Download import template" })).not.toBeInTheDocument();
  },
};

/** A type that gives a reason it cannot be imported is exported only. */
export const AnExportOnlyTypeHidesImport: Story = {
  args: {
    tables: fakeRecordTables({}, buildRecordColumns({ importable: false, can_import: false, not_importable_reason: "Produced by a workflow." })),
  },
  play: async ({ canvasElement }) => {
    const menu = await openListMenu(within(canvasElement));
    await expect(menu.getByRole("menuitem", { name: "Download shown items" })).toBeInTheDocument();
    await expect(menu.queryByRole("menuitem", { name: "Import from CSV" })).not.toBeInTheDocument();
  },
};

/** Columns the personal-data policy left out are named in one line under the menu's items. */
export const OmittedColumnsAreNoted: Story = {
  args: {
    tables: fakeRecordTables({}, buildRecordColumns({ omitted_sensitivity: ["contact"], omitted_reasons: { contact: "policy" } })),
  },
  play: async ({ canvasElement }) => {
    await openListMenu(within(canvasElement));
    await expect(
      within(document.body).getByText("Some columns holding personal data are left out by your organisation's policy."),
    ).toBeInTheDocument();
  },
};

/** A list of several kinds shows one kebab with a heading per kind, and each item acts on its own kind. */
export const SeveralKindsShareOneMenu: Story = {
  render: (args) => (
    <ListActionsMenu>
      <ListActions {...args} recordType="persona" kindLabel="personas" />
      <ListActions {...args} recordType="stakeholder" kindLabel="stakeholders" />
    </ListActionsMenu>
  ),
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findAllByRole("button", { name: "List actions" })).toHaveLength(1);
    const menu = await openListMenu(canvas);
    await expect(menu.getByText("Personas")).toBeInTheDocument();
    await expect(menu.getByText("Stakeholders")).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    await chooseExport(canvas, "CSV", "Stakeholders");
    await waitFor(() =>
      expect(args.tables!.exportFile).toHaveBeenCalledWith({ projectId: "project-1" }, "stakeholder", "csv", "status=draft&tag=safety&tag_mode=any"),
    );
  },
};

/** A type with no table (or no right to see it) shows no menu rather than a broken one. */
export const NothingWhenTheTypeHasNoTable: Story = {
  args: { tables: fakeRecordTables({ columns: failing("Record type not found.") }) },
  play: async ({ canvasElement, args }) => {
    await waitFor(() => expect(args.tables!.columns).toHaveBeenCalled());
    await expect(within(canvasElement).queryByRole("button", { name: "List actions" })).not.toBeInTheDocument();
  },
};

export const LightTheme: Story = { globals: { theme: "light" } };
export const DarkTheme: Story = { globals: { theme: "dark" } };
