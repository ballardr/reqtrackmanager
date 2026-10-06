import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { ApiError, api } from "../api/client";
import type { ReportTemplate } from "../api/types";
import { installedModules } from "../modules/registry";
import { buildReportCatalogueEntry, buildReportResult } from "../testing/reportFixtures";
import { withRouter, withToast } from "../testing/storybook-helpers";
import { ReportRunner } from "./ReportRunner";

const entry = buildReportCatalogueEntry();
const scope = { kind: "project" as const, id: "project-1" };
const orgEntry = buildReportCatalogueEntry({
  scope: "organization", supports_include_children: false, supports_project_filter: true, params: [],
  projects: [{ id: "project-1", name: "Atlas" }, { id: "project-2", name: "Borealis" }],
  path: "/api/v1/orgs/org-1/modules/fixture_report_module/reports/fixture-report",
});

const template: ReportTemplate = {
  id: "tpl-1", organization_id: "org-1", name: "Branded template", accent_color_hex: "#475569",
  include_cover_page: true, include_logo: true, footer_text: null, intro: "", chapters: [], appendices: [],
  chapters_per_component: false,
};

function mockRunApis(opts: { templates?: ReportTemplate[]; result?: ReturnType<typeof buildReportResult> } = {}) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.includes("/report-templates")) return opts.templates ?? [];
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
  args: { entry, scope, organizationId: "org-1" },
  decorators: [withToast()],
};
export default meta;

type Story = StoryObj<typeof ReportRunner>;

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

export const ProjectReportHasNoProjectPicker: Story = {
  beforeEach: () => mockRunApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("region", { name: "Items" })).toBeInTheDocument());
    await expect(canvas.queryByLabelText("Project")).not.toBeInTheDocument();
  },
};

/** A PDF download carries the on-screen values plus the chosen branding template, and confirms with a toast. */
export const PdfDownloadSendsValuesAndTemplate: Story = {
  beforeEach: () => mockRunApis({ templates: [template] }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("region", { name: "Items" })).toBeInTheDocument());
    await waitFor(() => expect(canvas.getByLabelText("Branding template (PDF)")).toBeInTheDocument());
    await userEvent.selectOptions(canvas.getByLabelText("Branding template (PDF)"), "tpl-1");
    await userEvent.click(canvas.getByRole("button", { name: "Export" }));
    await userEvent.click(within(document.body).getByRole("button", { name: "Download PDF report" }));
    await waitFor(() =>
      expect(api.getForBlob).toHaveBeenCalledWith(expect.stringMatching(/format=pdf.*report_template_id=tpl-1|report_template_id=tpl-1.*format=pdf/)),
    );
    await waitFor(() => expect(within(document.body).getByText("Downloaded Fixture report (PDF).")).toBeInTheDocument());
  },
};

/** CSV never carries the branding template (it is a flat export). */
export const CsvDownloadOmitsTemplate: Story = {
  beforeEach: () => mockRunApis({ templates: [template] }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("region", { name: "Items" })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Export" }));
    await userEvent.click(within(document.body).getByRole("button", { name: "Download CSV report" }));
    await waitFor(() => expect(api.getForBlob).toHaveBeenCalledWith(expect.stringContaining("format=csv")));
    await expect(api.getForBlob).not.toHaveBeenCalledWith(expect.stringContaining("report_template_id"));
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

/** A failed run shows an inline error, not a blank page. */
export const RunFailureShowsError: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.includes("/report-templates")) return [];
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
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.includes("/report-templates")) return [];
      return buildReportResult({ key: "f2" });
    });
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
      if (path.includes("/report-templates")) return [];
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
