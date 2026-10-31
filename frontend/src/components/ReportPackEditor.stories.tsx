import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, screen, spyOn, userEvent, waitFor, within } from "storybook/test";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { ApiError, api } from "../api/client";
import { saveVersion } from "../testing/saveVersionHelpers";
import { buildFieldCatalogue, buildLayoutSummary } from "../testing/reportLayoutFixtures";
import { buildDuplicateApi } from "../testing/reportDuplicateFixtures";
import { buildDefinition, buildForm, buildPackApi, buildPackSummary } from "../testing/reportPackFixtures";
import { withToast } from "../testing/storybook-helpers";
import { ReportPackEditor } from "./ReportPackEditor";

/** The editor of one pack: its reports, variables, saved sets and history. */
const meta: Meta<typeof ReportPackEditor> = {
  title: "Components/Reports/ReportPackEditor",
  component: ReportPackEditor,
  args: { packId: "pack-1", backTo: "/back" },
  decorators: [
    withToast(),
    (Story) => (
      <MemoryRouter initialEntries={["/pack"]}>
        <Routes>
          <Route path="/pack" element={<Story />} />
          <Route path="/back" element={<p>Back at the list</p>} />
        </Routes>
      </MemoryRouter>
    ),
  ],
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.endsWith("/report-layouts")) return [buildLayoutSummary({ name: "Requirements overview" }), buildLayoutSummary({ id: "l2", name: "Requirement rows", family: "table" })];
      if (path.endsWith("/report-layouts/fields")) return buildFieldCatalogue();
      if (path.endsWith("/report-catalogue")) return [];
      if (path.endsWith("/form")) return buildForm();
      throw new Error(`unmocked path: ${path}`);
    });
  },
};
export default meta;

type Story = StoryObj<typeof ReportPackEditor>;

const sharedPack = buildPackSummary({ origin: "organization", editable: false, project_id: null });

export const ShowsThePackAndItsReports: Story = {
  args: { api: buildPackApi([buildPackSummary()], { stateful: false }) },
  play: async ({ canvasElement }) => {
    const view = within(canvasElement);
    await expect(await view.findByRole("heading", { name: "Handover pack" })).toBeInTheDocument();
    await expect(await view.findByRole("region", { name: "Report 1" })).toBeInTheDocument();
    await expect(view.getByRole("button", { name: "Save new version" })).toBeDisabled();
  },
};

export const DuplicateOpensTheDialogForThePack: Story = {
  args: { api: buildPackApi([buildPackSummary()], { stateful: false }), duplicateApi: buildDuplicateApi({ sourceName: "Handover pack" }) },
  play: async ({ canvasElement }) => {
    const view = within(canvasElement);
    await view.findByRole("heading", { name: "Handover pack" });
    await userEvent.click(view.getByRole("button", { name: "Report pack actions" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Duplicate…" }));
    const dialog = within(await screen.findByRole("dialog", { name: "Duplicate pack" }));
    await waitFor(() => expect(dialog.getByRole("textbox", { name: "Name" })).toHaveValue("Handover pack (copy)"));
    await userEvent.click(dialog.getByRole("button", { name: "Cancel" }));
  },
};

export const EditingAReportEnablesSavingAsANewVersion: Story = {
  args: { api: buildPackApi([buildPackSummary()], { stateful: false }) },
  play: async ({ canvasElement, args }) => {
    const view = within(canvasElement);
    const first = within(await view.findByRole("region", { name: "Report 1" }));
    await userEvent.type(first.getByRole("textbox", { name: "File name" }), "-v2");
    await expect(await view.findByText("Unsaved changes")).toBeInTheDocument();
    await saveVersion(view.getByRole("button", { name: "Save new version" }), "Renamed the file");
    await waitFor(() => expect(args.api!.save).toHaveBeenCalledWith("pack-1", expect.objectContaining({
      base_version: 2, comment: "Renamed the file",
      definition: expect.objectContaining({ entries: expect.arrayContaining([expect.objectContaining({ filename: "overview-v2" })]) }),
    })));
    await expect(await within(document.body).findByText("Saved as version 3.")).toBeInTheDocument();
  },
};

export const AnInvalidJsonBoxHoldsSaveBack: Story = {
  args: { api: buildPackApi([buildPackSummary()], { stateful: false }) },
  play: async ({ canvasElement }) => {
    const view = within(canvasElement);
    const first = within(await view.findByRole("region", { name: "Report 1" }));
    const box = first.getByRole("textbox", { name: "Fixed values (JSON)" });
    await userEvent.clear(box);
    await userEvent.type(box, "{{\"a\"");
    await expect(await view.findByText("Fix the JSON boxes marked in red before saving.")).toBeInTheDocument();
    await expect(view.getByRole("button", { name: "Save new version" })).toBeDisabled();
  },
};

export const TheServersProblemsAreListed: Story = {
  args: {
    api: buildPackApi([buildPackSummary()], {
      stateful: false,
      save: async () => { throw new ApiError(422, "The pack is not valid.", { errors: [{ path: "entries[0].format", message: "Must be one of: pdf, docx." }] }); },
    }),
  },
  play: async ({ canvasElement }) => {
    const view = within(canvasElement);
    const first = within(await view.findByRole("region", { name: "Report 1" }));
    await userEvent.type(first.getByRole("textbox", { name: "File name" }), "x");
    await saveVersion(view.getByRole("button", { name: "Save new version" }));
    await expect(await view.findByText("entries[0].format: Must be one of: pdf, docx.")).toBeInTheDocument();
  },
};

export const AConflictAsksForAReload: Story = {
  args: {
    api: buildPackApi([buildPackSummary()], {
      stateful: false,
      save: async () => { throw new ApiError(409, "moved on", { current_version: 5 }); },
    }),
  },
  play: async ({ canvasElement }) => {
    const view = within(canvasElement);
    const first = within(await view.findByRole("region", { name: "Report 1" }));
    await userEvent.type(first.getByRole("textbox", { name: "File name" }), "x");
    await saveVersion(view.getByRole("button", { name: "Save new version" }));
    await expect(await view.findByText(/Someone saved a newer version/)).toBeInTheDocument();
  },
};

export const ASharedPackIsReadOnlyButItsSetsCanBeOverridden: Story = {
  args: { api: buildPackApi([sharedPack], { stateful: false }) },
  play: async ({ canvasElement }) => {
    const view = within(canvasElement);
    await expect(await view.findByText(/is read-only here/)).toBeInTheDocument();
    await expect(view.queryByRole("button", { name: "Save new version" })).not.toBeInTheDocument();
    await userEvent.click(view.getByRole("tab", { name: "Saved sets" }));
    await expect(await view.findByRole("region", { name: "Team Alpha" })).toBeInTheDocument();
  },
};

export const TheVariablesTabEditsDeclarations: Story = {
  args: { api: buildPackApi([buildPackSummary()], { stateful: false }) },
  play: async ({ canvasElement }) => {
    const view = within(canvasElement);
    await userEvent.click(await view.findByRole("tab", { name: "Variables" }));
    await expect(await view.findByRole("region", { name: "Variable 1" })).toBeInTheDocument();
  },
};

export const TheHistoryTabListsVersions: Story = {
  args: { api: buildPackApi([buildPackSummary()], { stateful: false }) },
  play: async ({ canvasElement }) => {
    const view = within(canvasElement);
    await userEvent.click(await view.findByRole("tab", { name: "History" }));
    const table = await view.findByRole("table", { name: "History" });
    await expect(within(table).getByText("First draft")).toBeInTheDocument();
  },
};

export const AnEmptyPackInvitesAddingReports: Story = {
  args: {
    api: buildPackApi([buildPackSummary({ entries: 0 })], { stateful: false, get: async () => ({
      ...buildPackSummary({ entries: 0 }),
      current: { version: 1, schema_version: 1, definition: buildDefinition({ entries: [], variables: undefined }), definition_hash: "h", comment: "", created_by: null, created_at: "2026-10-12T09:00:00Z" },
    }) }),
  },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByText("No reports in this pack yet.")).toBeInTheDocument();
  },
};

export const LeavingWithUnsavedChangesAsksFirst: Story = {
  args: { api: buildPackApi([buildPackSummary()], { stateful: false }) },
  play: async ({ canvasElement }) => {
    const view = within(canvasElement);
    const first = within(await view.findByRole("region", { name: "Report 1" }));
    await userEvent.type(first.getByRole("textbox", { name: "File name" }), "x");
    await userEvent.click(view.getByRole("button", { name: /Report packs/ }));
    await expect(await screen.findByRole("dialog", { name: "Leave without saving?" })).toBeInTheDocument();
  },
};
