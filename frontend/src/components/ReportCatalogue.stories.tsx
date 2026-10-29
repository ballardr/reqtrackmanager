import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, screen, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import { buildReportCatalogueEntry, buildReportResult } from "../testing/reportFixtures";
import { buildUser, withRouter, withStatefulAuth, withToast } from "../testing/storybook-helpers";
import { ReportCatalogue } from "./ReportCatalogue";

const first = buildReportCatalogueEntry();
const second = buildReportCatalogueEntry({
  key: "f2", slug: "second-report", title: "Second report", description: "Another synthetic report.",
  path: "/api/v1/projects/project-1/modules/fixture_report_module/reports/second-report", params: [],
  supports_include_children: false,
});

function mockApis() {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.includes("/report-placements")) return [];
    if (path.startsWith("/api/v1/report-runs")) return [];
    return buildReportResult({ title: path.includes("second-report") ? "Second report" : "Fixture report" });
  });
}

const meta: Meta<typeof ReportCatalogue> = {
  title: "Components/Reports/ReportCatalogue",
  component: ReportCatalogue,
  args: { entries: [first, second], scope: { kind: "project", id: "project-1" } },
  decorators: [withRouter("/projects/project-1/reports", "/projects/:projectId/reports"), withToast(), withStatefulAuth(buildUser({ ui_preferences: {} }))],
  beforeEach: mockApis,
};
export default meta;

type Story = StoryObj<typeof ReportCatalogue>;

/** The first entry is selected and run; its description sits under the picker button. */
export const SelectsFirstEntryByDefault: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("button", { name: "Report: Fixture report" })).toBeInTheDocument();
    await expect(canvas.getByText(first.description)).toBeInTheDocument();
    await waitFor(() => expect(canvas.getByRole("region", { name: "Items" })).toBeInTheDocument());
  },
};

/** Choosing another report in the picker dialog shows it and runs it. */
export const SwitchingReportRunsIt: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Report: Fixture report" }));
    const dialog = within(await screen.findByRole("dialog", { name: "Choose a report" }));
    await userEvent.click(dialog.getByRole("button", { name: "Expand Fixture Module" }));
    await userEvent.click(dialog.getByRole("button", { name: /^Second report/ }));
    await expect(canvas.getByRole("button", { name: "Report: Second report" })).toBeInTheDocument();
    await expect(canvas.getByText(second.description)).toBeInTheDocument();
    await waitFor(() => expect(api.get).toHaveBeenCalledWith(expect.stringContaining("/reports/second-report?format=json")));
  },
};

/** An extra (non-catalogue) entry is offered, files under Platform and renders host content. */
export const ExtraEntryIsOfferedFirst: Story = {
  args: {
    extraEntries: [{ key: "requirements", title: "Requirements report", description: "Host report.", render: () => <p>Host content</p> }],
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("button", { name: "Report: Requirements report" })).toBeInTheDocument();
    await expect(canvas.getByText("Host content")).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Report: Requirements report" }));
    const dialog = await screen.findByRole("dialog", { name: "Choose a report" });
    await expect(within(dialog).getByRole("button", { name: "Expand Platform" })).toBeInTheDocument();
  },
};

/** With one entry there is nothing to pick between, so no picker is drawn. */
export const SingleEntryHasNoPicker: Story = {
  args: { entries: [first] },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByRole("button", { name: /^Report:/ })).not.toBeInTheDocument();
    await waitFor(() => expect(canvas.getByRole("region", { name: "Items" })).toBeInTheDocument());
  },
};

/** Each module's reports are filed in a folder of their own, as the server's entries say. */
export const FilesEachModuleInItsOwnFolder: Story = {
  args: { entries: [first, buildReportCatalogueEntry({ ...second, module_key: "other_module", module_name: "Other Module", folder: "Other Module" })] },
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Report: Fixture report" }));
    const dialog = await screen.findByRole("dialog", { name: "Choose a report" });
    await expect(within(dialog).getByRole("button", { name: "Expand Fixture Module" })).toBeInTheDocument();
    await expect(within(dialog).getByRole("button", { name: "Expand Other Module" })).toBeInTheDocument();
  },
};

/** A placement the organisation set for an entry the catalogue does not hold (the requirements report) moves or hides it. */
export const AppliesPlacementsToExtraEntries: Story = {
  args: {
    extraEntries: [
      { key: "requirements", title: "Requirements report", description: "Host report.", render: () => <p>Host content</p> },
    ],
  },
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.includes("/report-placements/resolved")) {
        return [{ report_key: "report:platform.requirements", folder: "Core/Documents", hidden: false }];
      }
      if (path.startsWith("/api/v1/report-runs")) return [];
      return buildReportResult({ title: "Fixture report" });
    });
  },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByText(/Core\/Documents/)).toBeInTheDocument();
  },
};

/**
 * The platform's Record list is a catalogue entry like any module report: its `record_type` choice is generated
 * with the declared labels, the run carries the chosen type, and no module-specific UI is involved.
 */
export const TheRecordListChoosesATypeAndRunsWithIt: Story = {
  args: {
    entries: [
      buildReportCatalogueEntry({
        module_key: "platform", module_name: "Platform", key: "record-list", slug: "record-list", title: "Record list",
        description: "A table of any kind of record in this project.",
        path: "/api/v1/projects/project-1/reports/record-list", supports_include_children: false,
        params: [
          {
            name: "record_type", type: "string", default: "requirement", choices: ["requirement", "requirement_action"],
            minimum: null, maximum: null, description: "Which records to list.", label: "Record type",
            choice_labels: { requirement: "Requirements", requirement_action: "Actions" },
          },
          { name: "tag", type: "string", default: null, choices: null, minimum: null, maximum: null, description: "Only records carrying this tag.", label: "Tag" },
        ],
      }),
    ],
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(api.get).toHaveBeenCalledWith("/api/v1/projects/project-1/reports/record-list?format=json&record_type=requirement"));
    const select = canvas.getByLabelText("Record type");
    await expect(within(select).getAllByRole("option").map((o) => o.textContent)).toEqual(["Default", "Requirements", "Actions"]);
    await userEvent.selectOptions(select, "requirement_action");
    await waitFor(() =>
      expect(api.get).toHaveBeenCalledWith("/api/v1/projects/project-1/reports/record-list?format=json&record_type=requirement_action"),
    );
    await expect(canvas.queryByText("Include child projects")).not.toBeInTheDocument();
  },
};

export const NoReportsMessage: Story = {
  args: { entries: [] },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("No reports are available.")).toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...SelectsFirstEntryByDefault, globals: { theme: "light" } };
export const DarkTheme: Story = { ...SelectsFirstEntryByDefault, globals: { theme: "dark" } };
