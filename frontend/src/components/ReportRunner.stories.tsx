import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { ApiError, api } from "../api/client";
import { installedModules } from "../modules/registry";
import { buildReportCatalogueEntry, buildReportResult, buildReportVariable } from "../testing/reportFixtures";
import { withRouter, withToast } from "../testing/storybook-helpers";
import { ReportRunner } from "./ReportRunner";

const entry = buildReportCatalogueEntry();
const scope = { kind: "project" as const, id: "project-1" };
const orgEntry = buildReportCatalogueEntry({
  scope: "organization", supports_include_children: false, supports_project_filter: true, params: [],
  projects: [{ id: "project-1", name: "Atlas" }, { id: "project-2", name: "Borealis" }],
  path: "/api/v1/orgs/org-1/modules/fixture_report_module/reports/fixture-report",
});

function mockRunApis(opts: { result?: ReturnType<typeof buildReportResult> } = {}) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.startsWith(entry.path) || path.startsWith(orgEntry.path)) return opts.result ?? buildReportResult();
    throw new Error(`Unmocked GET: ${path}`);
  });
  spyOn(api, "getForBlob").mockResolvedValue(new Blob(["x"]));
}

/**
 * A module-neutral fixture registered with a custom view for the report key
 * `f2` — proves `ReportRunner` resolves views through the registry, not by
 * importing one. Nothing renders it unless a story runs an `f2` entry, so its
 * permanent presence causes no cross-story interference.
 */
installedModules.push({
  key: "fixture_report_module",
  reportViews: {
    f2: {
      component: ({ values, onValueChange }) => (
        <div>
          <p>Custom fixture view (rollup {String(values.rollup)})</p>
          <button className="btn" onClick={() => onValueChange("rollup", "worst_case")}>Use worst case</button>
        </div>
      ),
      ownedParams: ["rollup"],
    },
  },
});

const meta: Meta<typeof ReportRunner> = {
  title: "Components/Reports/ReportRunner",
  component: ReportRunner,
  args: { entry, scope },
  decorators: [withToast()],
};
export default meta;

type Story = StoryObj<typeof ReportRunner>;

/** A custom report with a required list variable: it does not run, or offer a download, until a value is chosen. */
export const ACustomReportWaitsForItsRequiredVariables: Story = {
  args: { entry: buildReportCatalogueEntry({ params: [], variables: [buildReportVariable()] }) },
  beforeEach: () => mockRunApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("status")).toHaveTextContent("Choose a value for Categories to run this report.");
    await expect(canvas.queryByRole("button", { name: "Export" })).toBeNull();
    await expect(api.get).not.toHaveBeenCalledWith(expect.stringContaining("/reports/fixture-report"));

    await userEvent.click(canvas.getByRole("button", { name: /Categories/ }));
    await userEvent.click(await within(document.body).findByRole("checkbox", { name: "Billing" }));
    await waitFor(() => expect(canvas.getByRole("region", { name: "Items" })).toBeInTheDocument());
    // The chosen values are sent as one JSON query parameter.
    const run = (api.get as unknown as { mock: { calls: string[][] } }).mock.calls.map((c) => c[0]).find((p) => p.includes("/reports/fixture-report"));
    const sent = new URLSearchParams(run?.split("?")[1]);
    await expect(JSON.parse(sent.get("variables") ?? "{}")).toEqual({ categories: ["Billing"] });
    await expect(canvas.queryByRole("status")).toBeNull();
  },
};

/** A variable with a default runs straight away with it, and a download sends the same values. */
export const ACustomReportRunsWithItsDefaultsAndDownloadsTheSameValues: Story = {
  args: {
    entry: buildReportCatalogueEntry({
      params: [], variables: [buildReportVariable({ default: ["Security"] })], formats: ["json", "pdf", "xlsx"],
    }),
  },
  beforeEach: () => mockRunApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("region", { name: "Items" })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Export" }));
    await userEvent.click(within(document.body).getByRole("button", { name: "Download PDF report" }));
    await waitFor(() => expect(api.getForBlob).toHaveBeenCalled());
    const url = (api.getForBlob as unknown as { mock: { calls: string[][] } }).mock.calls[0][0];
    await expect(JSON.parse(new URLSearchParams(url.split("?")[1]).get("variables") ?? "{}")).toEqual({ categories: ["Security"] });
  },
};

/** Runs on mount with the declared defaults and renders the generic viewer. */
export const RunsWithDefaultsAndShowsResult: Story = {
  beforeEach: () => mockRunApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("region", { name: "Items" })).toBeInTheDocument());
    await expect(api.get).toHaveBeenCalledWith(expect.stringContaining("format=json"));
    await expect(api.get).toHaveBeenCalledWith(expect.stringContaining("rollup=weighted_average"));
    await expect(api.get).toHaveBeenCalledWith(expect.stringContaining("stale_months=6"));
    await expect(canvas.getByText(/Atlas Platform · generated/)).toBeInTheDocument();
  },
};

/** Changing a parameter re-runs the report with the new value. */
export const ParameterChangeReruns: Story = {
  beforeEach: () => mockRunApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("region", { name: "Items" })).toBeInTheDocument());
    await userEvent.selectOptions(canvas.getByLabelText("Rollup"), "worst_case");
    await waitFor(() => expect(api.get).toHaveBeenCalledWith(expect.stringContaining("rollup=worst_case")));
  },
};

/** The framework `include_children` switch is sent to the run. */
export const IncludeChildrenIsSent: Story = {
  beforeEach: () => mockRunApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("region", { name: "Items" })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("switch", { name: "Include child projects" }));
    await waitFor(() => expect(api.get).toHaveBeenCalledWith(expect.stringContaining("include_children=true")));
  },
};

/** An organisation-wide report offers a Project picker; choosing one re-runs it narrowed, and a project report never does. */
export const OrganisationReportCanBeNarrowedToOneProject: Story = {
  args: { entry: orgEntry, scope: { kind: "organization", id: "org-1" } },
  beforeEach: () => mockRunApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("region", { name: "Items" })).toBeInTheDocument());
    await expect(within(canvas.getByLabelText("Project")).getByRole("option", { name: "Borealis" })).toBeInTheDocument();
    await userEvent.selectOptions(canvas.getByLabelText("Project"), "project-2");
    await waitFor(() => expect(api.get).toHaveBeenCalledWith(expect.stringContaining("project_id=project-2")));
    await userEvent.click(canvas.getByRole("button", { name: "Export" }));
    await userEvent.click(within(document.body).getByRole("button", { name: "Download CSV report" }));
    await waitFor(() => expect(api.getForBlob).toHaveBeenCalledWith(expect.stringContaining("project_id=project-2")));
  },
};

/** A custom table report offers its own formats (Excel, CSV) and asks the server for exactly the one chosen. */
export const CustomTableReportOffersExcelAndCsv: Story = {
  args: {
    entry: buildReportCatalogueEntry({
      module_key: "custom_reports", slug: "custom-sheet-1", supports_include_children: true, params: [],
      formats: ["json", "csv", "xlsx", "ods"], path: "/api/v1/projects/project-1/custom-reports/layout-2/run",
    }),
  },
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.startsWith("/api/v1/projects/project-1/custom-reports/layout-2/run")) return buildReportResult();
      throw new Error(`Unmocked GET: ${path}`);
    });
    spyOn(api, "getForBlob").mockResolvedValue(new Blob(["x"], { type: "application/zip" }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("region", { name: "Items" })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Export" }));
    await expect(within(document.body).queryByRole("button", { name: "Download PDF report" })).not.toBeInTheDocument();
    await userEvent.click(within(document.body).getByRole("button", { name: "Download Excel report" }));
    await waitFor(() => expect(api.getForBlob).toHaveBeenCalledWith(expect.stringContaining("format=xlsx")));
    await waitFor(() => expect(within(document.body).getByText("Downloaded Fixture report (Excel).")).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Export" }));
    await userEvent.click(within(document.body).getByRole("button", { name: "Download ODS report" }));
    await waitFor(() => expect(api.getForBlob).toHaveBeenCalledWith(expect.stringContaining("format=ods")));
  },
};

/** A custom report run once per project: choosing projects re-runs it with `project_ids`, and downloads carry the same selection. */
export const OrganisationCustomReportChoosesProjects: Story = {
  args: {
    entry: buildReportCatalogueEntry({
      scope: "organization", module_key: "custom_reports", slug: "custom-everywhere-1", supports_include_children: false,
      supports_project_filter: false, supports_project_multi_filter: true, params: [],
      formats: ["json", "pdf", "docx"],
      projects: [{ id: "project-1", name: "Atlas" }, { id: "project-2", name: "Borealis" }],
      path: "/api/v1/orgs/org-1/custom-reports/layout-1/run",
    }),
    scope: { kind: "organization", id: "org-1" },
  },
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.startsWith("/api/v1/orgs/org-1/custom-reports/layout-1/run")) return buildReportResult();
      throw new Error(`Unmocked GET: ${path}`);
    });
    spyOn(api, "getForBlob").mockResolvedValue(new Blob(["x"]));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("region", { name: "Items" })).toBeInTheDocument());
    await expect(canvas.queryByLabelText("Project")).not.toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Projects" }));
    await userEvent.click(within(document.body).getByRole("checkbox", { name: "Borealis" }));
    await waitFor(() => expect(api.get).toHaveBeenCalledWith(expect.stringContaining("project_ids=project-2")));
    await userEvent.keyboard("{Escape}");
    await userEvent.click(canvas.getByRole("button", { name: "Export" }));
    await userEvent.click(within(document.body).getByRole("button", { name: "Download PDF report" }));
    await waitFor(() => expect(api.getForBlob).toHaveBeenCalledWith(expect.stringContaining("project_ids=project-2")));
  },
};

export const ProjectReportHasNoProjectPicker: Story = {
  beforeEach: () => mockRunApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("region", { name: "Items" })).toBeInTheDocument());
    await expect(canvas.queryByLabelText("Project")).not.toBeInTheDocument();
  },
};

/** A document download has no branding choice, even when the organisation has templates: the server applies the
 * layout's own template, else the organisation's default, so the request names none; it confirms with a toast. */
export const DocumentDownloadHasNoBrandingChoice: Story = {
  beforeEach: () => mockRunApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("region", { name: "Items" })).toBeInTheDocument());
    await expect(canvas.queryByLabelText("Branding template")).not.toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Export" }));
    await userEvent.click(within(document.body).getByRole("button", { name: "Download PDF report" }));
    await waitFor(() => expect(api.getForBlob).toHaveBeenCalledWith(expect.stringContaining("format=pdf")));
    await expect(api.getForBlob).not.toHaveBeenCalledWith(expect.stringContaining("report_template_id"));
    await waitFor(() => expect(within(document.body).getByText("Downloaded Fixture report (PDF).")).toBeInTheDocument());
  },
};

/** A CSV download is a flat export: no template in the request. */
export const CsvDownloadOmitsTemplate: Story = {
  beforeEach: () => mockRunApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("region", { name: "Items" })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Export" }));
    await userEvent.click(within(document.body).getByRole("button", { name: "Download CSV report" }));
    await waitFor(() => expect(api.getForBlob).toHaveBeenCalledWith(expect.stringContaining("format=csv")));
    await expect(api.getForBlob).not.toHaveBeenCalledWith(expect.stringContaining("report_template_id"));
  },
};

/** Every format a module report declares is in the menu, and none of them sends a branding template. */
export const EveryDeclaredFormatIsInTheMenu: Story = {
  args: { entry: buildReportCatalogueEntry({ formats: ["json", "pdf", "docx", "html", "odt", "csv", "xlsx", "ods"] }) },
  beforeEach: () => mockRunApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("region", { name: "Items" })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Export" }));
    const menu = within(document.body);
    for (const label of [
      "Download PDF report", "Download Word report", "Download HTML report", "Download ODT report",
      "Download CSV report", "Download Excel report", "Download ODS report",
    ]) {
      await expect(menu.getByRole("button", { name: label })).toBeInTheDocument();
    }
    await userEvent.click(menu.getByRole("button", { name: "Download ODT report" }));
    await waitFor(() => expect(api.getForBlob).toHaveBeenCalledWith(expect.stringContaining("format=odt")));
    await expect(api.getForBlob).toHaveBeenLastCalledWith(expect.not.stringContaining("report_template_id"));
    await waitFor(() => expect(within(document.body).getByText("Downloaded Fixture report (ODT).")).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Export" }));
    await userEvent.click(within(document.body).getByRole("button", { name: "Download ODS report" }));
    await waitFor(() => expect(api.getForBlob).toHaveBeenLastCalledWith(expect.stringContaining("format=ods")));
    await expect(api.getForBlob).toHaveBeenLastCalledWith(expect.not.stringContaining("report_template_id"));
  },
};

export const DownloadFailureShowsToast: Story = {
  beforeEach: () => {
    mockRunApis();
    spyOn(api, "getForBlob").mockRejectedValue(new ApiError(500, "Internal Server Error"));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("region", { name: "Items" })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Export" }));
    await userEvent.click(within(document.body).getByRole("button", { name: "Download CSV report" }));
    await waitFor(() => expect(within(document.body).getByText("Internal Server Error")).toBeInTheDocument());
  },
};

/** A file run that is too big for a request is queued in the background and the person is told so. */
export const TooBigDownloadIsQueuedInTheBackground: Story = {
  args: { entry: buildReportCatalogueEntry({ path: "/api/v1/projects/project-1/custom-reports/layout-1/run" }) },
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async () => buildReportResult());
    spyOn(api, "getForBlob").mockRejectedValue(
      new ApiError(409, "Too big.", { code: "async_required", message: "Too big." }),
    );
    spyOn(api, "post").mockResolvedValue({ id: "run-1", status: "queued" });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("region", { name: "Items" })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Export" }));
    await userEvent.click(within(document.body).getByRole("button", { name: "Download PDF report" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(expect.stringMatching(/\/runs$/), expect.objectContaining({ format: "pdf" })));
    await waitFor(() => expect(within(document.body).getByText(/being prepared in the background/)).toBeInTheDocument());
  },
};

/** A failed run shows an inline error, not a blank page. */
export const RunFailureShowsError: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async () => {
      throw new ApiError(500, "Report failed to run.");
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("alert")).toHaveTextContent("Report failed to run."));
  },
};

/** No in-scope project has the feature enabled: the viewer's explicit empty state. */
export const NothingToReportOn: Story = {
  beforeEach: () => mockRunApis({ result: buildReportResult({ eligible_projects: 0 }) }),
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(within(canvasElement).getByText(/Nothing to report on/)).toBeInTheDocument());
  },
};

/** A report with a registered view renders it instead of the generic viewer, and the view owns its parameter. */
export const RegisteredViewReplacesGenericViewer: Story = {
  args: { entry: buildReportCatalogueEntry({ key: "f2", slug: "fixture-view", path: `${entry.path}-view` }) },
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async () => buildReportResult({ key: "f2" }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Custom fixture view (rollup weighted_average)")).toBeInTheDocument());
    await expect(canvas.queryByRole("region", { name: "Items" })).not.toBeInTheDocument();
    // `rollup` is owned by the view, so the generic form does not offer it.
    await expect(canvas.queryByLabelText("Rollup")).not.toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Use worst case" }));
    await waitFor(() => expect(canvas.getByText("Custom fixture view (rollup worst_case)")).toBeInTheDocument());
  },
};

export const LightTheme: Story = { ...RunsWithDefaultsAndShowsResult, globals: { theme: "light" } };
export const DarkTheme: Story = { ...RunsWithDefaultsAndShowsResult, globals: { theme: "dark" } };

const linkedResult = () =>
  buildReportResult({
    metrics: [
      { label: "Blockers", value: 3, gap: true, link: { kind: "module", target: "pain-points", query: { blocker: "1" }, section: null } },
      { label: "Oldest (days)", value: 33, link: null },
    ],
  });

/** In a project report a linked figure is a link to the module page it counts; an unlinked figure stays plain. */
export const ProjectFiguresLinkToFilteredPages: Story = {
  decorators: [withRouter("/")],
  beforeEach: () => mockRunApis({ result: linkedResult() }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const link = await canvas.findByRole("link", { name: "Blockers: 3" });
    await expect(link).toHaveAttribute("href", "/projects/project-1/modules/fixture_report_module/pain-points?blocker=1");
    await expect(canvas.queryByRole("link", { name: /Oldest/ })).not.toBeInTheDocument();
    // Hovering says where it leads.
    await userEvent.hover(link);
    await expect(within(canvasElement.ownerDocument.body).getByRole("tooltip", { name: /Opens the pain points list, filtered to "Blockers"/ })).toBeVisible();
  },
};

/** In an organisation report a figure opens the per-project list, and following a project goes to its page. */
export const OrganisationFiguresOpenAProjectList: Story = {
  args: {
    entry: buildReportCatalogueEntry({
      ...orgEntry,
      breakdown_path: `${orgEntry.path}/by-project`,
    }),
    scope: { kind: "organization", id: "org-1" },
  },
  decorators: [withRouter("/")],
  beforeEach: () => {
    const figure = linkedResult().metrics[0];
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.includes("/by-project")) {
        return {
          generated_at: "2026-10-06T09:30:00Z", truncated: false,
          projects: [{ project_id: "p-1", project_name: "Atlas", metrics: [{ ...figure, value: 3 }] }],
        };
      }
      return linkedResult();
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const figure = await canvas.findByRole("button", { name: "Blockers: 3" });
    await userEvent.hover(figure);
    await expect(within(canvasElement.ownerDocument.body).getByRole("tooltip", { name: /Shows which projects make up "Blockers"/ })).toBeVisible();
    await userEvent.click(figure);
    const dialog = within(canvasElement.ownerDocument.body);
    await expect(await dialog.findByRole("dialog", { name: "Blockers by project" })).toBeInTheDocument();
    await expect(await dialog.findByRole("link", { name: /Atlas/ })).toHaveAttribute(
      "href", "/projects/p-1/modules/fixture_report_module/pain-points?blocker=1",
    );
  },
};

/** With the result off (the record list's download dialog) the report is not run for the screen, yet it still offers its download. */
export const WithoutResultItIsNotRunOnScreen: Story = {
  args: { showResult: false },
  beforeEach: () => mockRunApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("button", { name: "Export" })).toBeInTheDocument();
    await expect(api.get).not.toHaveBeenCalledWith(expect.stringContaining("/reports/fixture-report"));
    await expect(canvas.queryByRole("table")).not.toBeInTheDocument();
  },
};
