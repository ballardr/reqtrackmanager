import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, within } from "storybook/test";

import { ApiError, api } from "../api/client";
import type { ChangeEntry, OverviewLayout, OverviewMetricResult, OverviewMetricSpec, ProjectMetrics } from "../api/types";
import { buildChangeEntry, buildProject, buildProjectListItem, withRouter, withTerminology } from "../testing/storybook-helpers";
import { ProjectOverviewPage } from "./ProjectOverviewPage";

const metrics: ProjectMetrics = {
  requirement_count: 24,
  requirement_completed_percent: 62,
  change_requests_proposed: 5,
  change_requests_approved: 12,
  change_requests_rejected: 2,
  file_count: 8,
  // C-G-11: "completed" is no longer a `RequirementStatus` value (it's the
  // independent `Requirement.is_completed` overlay now) — sums to 24
  // (requirement_count) the same as before, just without that bucket.
  requirements_by_status: { draft: 4, reviewed: 3, approved: 15, archived: 2 },
  stage_progress: [
    { stage_id: "s1", name: "Scoping", phase_name: "Completed", phase_kind: "closed", requirement_count: 10, completed_percent: 100 },
    { stage_id: "s2", name: "Build", phase_name: "Scoping", phase_kind: "open", requirement_count: 14, completed_percent: 30 },
  ],
  scope_project_count: 1,
  records_by_type: [
    { type: "requirement", label: "Requirements", count: 24 },
    { type: "risk", label: "Risks", count: 9 },
    { type: "decision", label: "Decisions", count: 4 },
  ],
  record_total: 37,
};

/** The built-in layout the server sends for a project that has set none. */
const cell = (id: string, type: string, width: number, height: number, config: Record<string, unknown>) => ({
  id, type, title: null, width, height, scope: null, visible: true, config,
});
const layout: OverviewLayout = {
  scope: "this", source: "default", inherited_source: null, can_customise: false,
  widgets: [
    cell("percent-complete", "metric_tile", 3, 2, { metric: "requirement_completed_percent" }), cell("file-count", "metric_tile", 3, 2, { metric: "file_count" }),
    cell("cr-proposed", "metric_tile", 2, 2, { metric: "change_requests_proposed" }), cell("cr-approved", "metric_tile", 2, 2, { metric: "change_requests_approved" }),
    cell("cr-rejected", "metric_tile", 2, 2, { metric: "change_requests_rejected" }),
    cell("record-totals", "record_totals", 3, 6, {}),
    cell("requirements-by-status", "status_chart", 3, 6, { metric: "requirements_by_status", chart: "pie" }),
    cell("change-requests", "status_chart", 3, 6, { metric: "change_requests_by_outcome", chart: "pie" }),
    cell("stage-progress", "stage_progress", 3, 6, {}), cell("activity", "activity", 12, 6, { limit: 8 }),
  ],
};

/** What the metrics endpoint answers for one reference, read off a `ProjectMetrics` fixture. */
function resultFor(spec: OverviewMetricSpec, m: ProjectMetrics): OverviewMetricResult {
  const projects = spec.scope === "this" ? 1 : m.scope_project_count;
  const ok = (value: number | null, unit: "count" | "percent", breakdown: OverviewMetricResult["breakdown"] = null): OverviewMetricResult => ({
    state: "ok", unit, label: spec.metric, value, breakdown, projects,
  });
  switch (spec.metric) {
    case "requirement_completed_percent": return ok(m.requirement_completed_percent, "percent");
    case "requirement_count": return ok(m.requirement_count, "count");
    case "file_count": return ok(m.file_count, "count");
    case "change_requests_proposed": return ok(m.change_requests_proposed, "count");
    case "change_requests_approved": return ok(m.change_requests_approved, "count");
    case "change_requests_rejected": return ok(m.change_requests_rejected, "count");
    case "requirements_by_status":
      return ok(null, "count", Object.entries(m.requirements_by_status).map(([key, value]) => ({ key, label: key, value, detail: null })));
    case "change_requests_by_outcome":
      return ok(null, "count", [
        { key: "active", label: "Proposed", value: m.change_requests_proposed, detail: null },
        { key: "approved", label: "Approved", value: m.change_requests_approved, detail: null },
        { key: "rejected", label: "Rejected", value: m.change_requests_rejected, detail: null },
      ]);
    case "stage_progress":
      return ok(null, "percent", m.stage_progress.map((s) => ({ key: s.stage_id, label: s.name, value: s.completed_percent, detail: s.phase_name })));
    case "records_by_type":
      return ok(m.record_total, "count", m.records_by_type.map((r) => ({ key: r.type, label: r.label, value: r.count, detail: null })));
    default: return { state: "unavailable", unit: null, label: null, value: null, breakdown: null, projects: 1 };
  }
}

/** A `post` mock for the batched metrics endpoint: `metricsFor` picks the fixture from a reference's scope. */
function overviewMetricsMock(metricsFor: (scope: string) => ProjectMetrics = () => metrics) {
  return async (_path: string, body?: unknown) => {
    const specs = (body as { metrics: OverviewMetricSpec[] }).metrics;
    return { results: Object.fromEntries(specs.map((spec) => [spec.id, resultFor(spec, metricsFor(spec.scope))])) };
  };
}

const activity: ChangeEntry[] = [buildChangeEntry({ action: "updated", actor_display_name: "Alex Morgan" })];

const meta: Meta<typeof ProjectOverviewPage> = {
  title: "Pages/ProjectOverviewPage",
  component: ProjectOverviewPage,
  decorators: [withRouter("/projects/project-1", "/projects/:projectId"), withTerminology()],
};
export default meta;

type Story = StoryObj<typeof ProjectOverviewPage>;

export const Dashboard: Story = {
  beforeEach: () => {
    spyOn(api, "post").mockImplementation(overviewMetricsMock());
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.endsWith("/overview-layout")) return layout;
      if (path.endsWith("/changes")) return activity;
      // No parent/children for this fixture — a plain top-level project,
      // so neither the breadcrumb nor the "Child of/Parent of" labels
      // render (see `WithHierarchy` below for the populated case).
      if (path.endsWith("/ancestors")) return [];
      if (path.endsWith("/children")) return [];
      // No module enabled for this fixture's org — no module-contributed
      // tiles (see `ComplianceProjectOverviewTiles.stories.tsx` for the
      // Compliance module's own populated case, extracted from this page's
      // stories during the module boundary cleanup, 2026-09-08).
      if (path.endsWith("/enabled-modules")) return [];
      return buildProject({ id: "project-1", name: "Atlas Platform", summary: "Core platform requirements." });
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Atlas Platform")).toBeInTheDocument();
    // The total-records chart: its centre is the sum across modules and each type has a legend row.
    const totalCard = canvas.getByText("Total records").closest(".card") as HTMLElement;
    await expect(within(totalCard).getByText("37")).toBeInTheDocument();
    for (const label of ["Requirements", "Risks", "Decisions"]) {
      await expect(within(totalCard).getByRole("button", { name: new RegExp(label) })).toBeInTheDocument();
    }
    await expect(canvas.getByText("Alex Morgan updated")).toBeInTheDocument();
  },
};

/** A template carries a Template badge whose tooltip says only managers and administrators can change it. */
export const TemplateBadge: Story = {
  beforeEach: () => {
    spyOn(api, "post").mockImplementation(overviewMetricsMock());
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.endsWith("/overview-layout")) return layout;
      if (path.endsWith("/changes")) return activity;
      if (path.endsWith("/ancestors") || path.endsWith("/children") || path.endsWith("/enabled-modules")) return [];
      return buildProject({ id: "project-1", name: "Atlas Platform", summary: "Core platform requirements.", is_template: true });
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText("Template")).toBeInTheDocument();
    await userEvent.hover(canvas.getByText("Template"));
    await expect(await within(document.body).findByText(/Only project managers and project administrators can change it/)).toBeInTheDocument();
  },
};

/** A project with no records shows words, not an empty ring. */
export const NoRecords: Story = {
  beforeEach: () => {
    spyOn(api, "post").mockImplementation(overviewMetricsMock(() => ({ ...metrics, records_by_type: [], record_total: 0 })));
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.endsWith("/overview-layout")) return layout;
      if (path.endsWith("/changes")) return activity;
      if (path.endsWith("/ancestors") || path.endsWith("/children") || path.endsWith("/enabled-modules")) return [];
      return buildProject({ id: "project-1", name: "Atlas Platform", summary: "Core platform requirements." });
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText("No records yet.")).toBeInTheDocument();
  },
};

// Hierarchical projects (docs/decisions.md): a project with both a visible
// parent and visible children — pins the root-first ancestor breadcrumb
// (grandparent -> parent, this project's own name un-linked) and the
// reused `ProjectHierarchyLabels` "Child of"/"Parent of" lines rendering
// together on Project Overview for the first time.
export const WithHierarchy: Story = {
  beforeEach: () => {
    spyOn(api, "post").mockImplementation(overviewMetricsMock());
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.endsWith("/overview-layout")) return layout;
      if (path.endsWith("/changes")) return activity;
      if (path.endsWith("/ancestors")) {
        return [
          { id: "grandparent-1", name: "Solstice Programme" },
          { id: "parent-1", name: "Atlas Platform" },
        ];
      }
      if (path.endsWith("/children")) {
        return [
          buildProjectListItem({ id: "child-1", name: "Atlas Mobile", parent_project_id: "project-1" }),
          buildProjectListItem({ id: "child-2", name: "Atlas Web", parent_project_id: "project-1" }),
        ];
      }
      if (path.endsWith("/enabled-modules")) return [];
      return buildProject({
        id: "project-1", name: "Atlas Core", summary: "Core platform requirements.",
        parent_project_id: "parent-1", parent_project_name: "Atlas Platform",
      });
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    // "Atlas Core" legitimately renders twice — the `<h1>` and the
    // breadcrumb's own (un-linked) trailing segment.
    await expect(canvas.getAllByText("Atlas Core")).toHaveLength(2);
    // Breadcrumb: both ancestors linked, current project's own name last
    // and un-linked.
    await expect(canvas.getByRole("link", { name: "Solstice Programme" })).toBeInTheDocument();
    // "Atlas Platform" legitimately renders twice — once as the
    // breadcrumb's immediate-parent link, once as `ProjectHierarchyLabels`'
    // "Child of:" link just below the heading — both pointing at the same
    // parent project, so asserting the count confirms both spots render
    // rather than picking one arbitrarily via `getByRole`.
    await expect(canvas.getAllByRole("link", { name: "Atlas Platform" })).toHaveLength(2);
    // "Child of"/"Parent of" labels, reused from `ProjectHierarchyLabels`.
    await expect(canvas.getByText("Child of:")).toBeInTheDocument();
    await expect(canvas.getByText("Parent of:")).toBeInTheDocument();
    await expect(canvas.getByRole("link", { name: "Atlas Mobile" })).toBeInTheDocument();
    await expect(canvas.getByRole("link", { name: "Atlas Web" })).toBeInTheDocument();
  },
};

export const LoadError: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockRejectedValue(new ApiError(403, "You do not have access to this project."));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("You do not have access to this project.")).toBeInTheDocument();
  },
};

/** With more than one project to switch between, a chevron next
 * to the project name opens a popover listing the others as plain links
 * to their own Project Overview page. */
export const EntitySwitcherOffersSiblingProjects: Story = {
  beforeEach: () => {
    spyOn(api, "post").mockImplementation(overviewMetricsMock());
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.endsWith("/overview-layout")) return layout;
      if (path.endsWith("/changes")) return activity;
      if (path.endsWith("/ancestors")) return [];
      if (path.endsWith("/children")) return [];
      if (path.endsWith("/enabled-modules")) return [];
      if (path === "/api/v1/projects?archived=false") {
        return [
          buildProjectListItem({ id: "project-1", name: "Atlas Platform" }),
          buildProjectListItem({ id: "project-2", name: "Solstice Programme" }),
        ];
      }
      return buildProject({ id: "project-1", name: "Atlas Platform", summary: "Core platform requirements." });
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Atlas Platform")).toBeInTheDocument();

    const trigger = await canvas.findByRole("button", { name: "Switch project" });
    await userEvent.click(trigger);
    const dialog = within(document.body).getByRole("dialog", { name: "Switch project" });
    await expect(within(dialog).getByRole("link", { name: "Solstice Programme" })).toHaveAttribute(
      "href",
      "/projects/project-2"
    );
  },
};

/** A manager sees "Customise overview", which opens the side panel with the layout in force. */
export const ManagerCanCustomise: Story = {
  beforeEach: () => {
    spyOn(api, "post").mockImplementation(overviewMetricsMock());
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.endsWith("/overview-layout")) return { ...layout, can_customise: true };
      if (path.endsWith("/overview-catalogue")) {
        return {
          widget_types: [{ key: "metric_tile", label: "Metric tile", description: "", module_key: null }],
          metrics: [{ key: "requirement_completed_percent", label: "Requirements complete", unit: "percent", scalar: true, breakdown: false, params: [], module_key: null }],
          record_types: [], max_widgets: 24,
        };
      }
      if (path.endsWith("/changes")) return activity;
      if (path.endsWith("/ancestors") || path.endsWith("/children") || path.endsWith("/enabled-modules")) return [];
      return buildProject({ id: "project-1", name: "Atlas Platform", summary: "Core platform requirements." });
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const customise = await canvas.findByRole("button", { name: "Customise overview" });
    // The actions sit on the project name's own row, not at the far side of the page.
    const heading = canvas.getByRole("heading", { level: 1, name: "Atlas Platform" });
    await expect(Math.abs(customise.getBoundingClientRect().top - heading.getBoundingClientRect().top)).toBeLessThan(heading.getBoundingClientRect().height);
    // ...and at the right-hand end of that row, not beside the title.
    const newButton = canvas.getByRole("link", { name: /New requirement/i });
    await expect(newButton.getBoundingClientRect().right).toBeGreaterThan(canvasElement.getBoundingClientRect().right - 40);
    await expect(customise.getBoundingClientRect().left).toBeGreaterThan(heading.getBoundingClientRect().right + 40);
    await userEvent.click(customise);
    // The page becomes the editor: a bar with Save, Add widget and the count, and tools on each widget.
    await expect(await canvas.findByRole("button", { name: "Save" })).toBeInTheDocument();
    await expect(canvas.getByRole("combobox", { name: "Add widget" })).toBeInTheDocument();
    await expect(canvas.getByText("10 of 24 widgets")).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Move % Completed" })).toBeInTheDocument();
    // The other actions step aside while editing, and the built-in layout shows no "Restore default" (nothing is edited).
    await expect(canvas.queryByRole("button", { name: "Reports" })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Restore default" })).not.toBeInTheDocument();
    // Leaving with no change needs no confirmation.
    await userEvent.click(canvas.getByRole("button", { name: "Cancel" }));
    await expect(await canvas.findByRole("button", { name: "Customise overview" })).toBeInTheDocument();
  },
};

/** Without the right to change the layout the control is absent (the default stories above). */
export const ReadOnlyViewerHasNoCustomiseControl: Story = {
  ...Dashboard,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByText("Total records");
    await expect(canvas.queryByRole("button", { name: "Customise overview" })).not.toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...Dashboard, globals: { theme: "light" } };
export const DarkTheme: Story = { ...Dashboard, globals: { theme: "dark" } };

/** A module's tiles are an ordinary widget: placed between the charts, sized and shown like any other. */
export const ComplianceWidgetSitsWhereItIsPlaced: Story = {
  beforeEach: () => {
    spyOn(api, "post").mockImplementation(overviewMetricsMock());
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.endsWith("/overview-layout")) {
        return { ...layout, widgets: [layout.widgets[0], cell("compliance-standards_status", "compliance:standards_status", 6, 2, {}), ...layout.widgets.slice(1)] };
      }
      if (path.endsWith("/modules/compliance/status")) {
        return [{
          project_compliance_id: "pc-1", project_id: "project-1", project_name: "Atlas Platform", standard_id: "s1", standard_reference: "ISO-27001",
          standard_name: "Corporate Security Standard", standard_version_id: "v1", version_label: "v2.0", target_compliance_date: null,
          assigned_at: "2026-01-01T00:00:00Z", total_requirements: 20, applicable_count: 18, not_applicable_count: 2,
          counts_by_status: { compliant: 15 }, compliance_percentage: 83, has_non_compliant: false, not_yet_assessed: false,
          overall_compliance_state: "in_progress", overall_approval_state: "not_assessed", from_project_id: null,
        }];
      }
      if (path.endsWith("/changes")) return activity;
      if (path.endsWith("/ancestors") || path.endsWith("/children") || path.endsWith("/enabled-modules")) return [];
      return buildProject({ id: "project-1", name: "Atlas Platform", summary: "Core platform requirements." });
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const cellEl = (await canvas.findByText("Corporate Security Standard")).closest("[data-widget-id]") as HTMLElement;
    await expect(cellEl).toHaveAttribute("data-widget-id", "compliance-standards_status");
    await expect(within(cellEl).getByText("83%")).toBeInTheDocument();
    await expect(cellEl.style.getPropertyValue("--w")).toBe("6");
    // It is the second widget, so it sits right after the first tile, not in a group of its own at the end.
    await expect(canvasElement.querySelectorAll("[data-widget-id]")[1]).toBe(cellEl);
  },
};

/** An overview whose scope is "with parents" reads its figures across the parent: the tile counts both projects and says so. */
export const WidenedToTheParent: Story = {
  beforeEach: () => {
    spyOn(api, "post").mockImplementation(overviewMetricsMock((scope) => scope === "parents"
      ? {
        ...metrics, requirement_count: 60, scope_project_count: 2, record_total: 60,
        records_by_type: [{ type: "requirement", label: "Requirements", count: 60 }],
      }
      : metrics));
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.endsWith("/overview-layout")) {
        return {
          ...layout, scope: "parents",
          widgets: [{ ...cell("total", "metric_tile", 3, 2, { metric: "requirement_count" }), title: "All requirements" }, ...layout.widgets.slice(1)],
        };
      }
      if (path.endsWith("/changes")) return activity;
      if (path.endsWith("/ancestors") || path.endsWith("/children") || path.endsWith("/enabled-modules")) return [];
      return buildProject({ id: "project-1", name: "Atlas Platform", summary: "Core platform requirements." });
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const tile = (await canvas.findByText("All requirements")).closest("[data-widget-id]") as HTMLElement;
    await expect(within(tile).getByText("60")).toBeInTheDocument();
    await expect(within(tile).getByText("With parents · 2 projects")).toBeInTheDocument();
    // There is no scope select on the page any more: the scope is a setting of the overview.
    await expect(canvas.queryByRole("combobox", { name: "Show records from" })).not.toBeInTheDocument();
  },
};
