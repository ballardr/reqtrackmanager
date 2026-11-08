import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, userEvent, within } from "storybook/test";

import { api } from "../../api/client";
import type { OverviewMetricResult, OverviewWidget } from "../../api/types";
import type { OverviewMetricsState } from "../../hooks/useOverviewMetrics";
import { buildChangeEntry, withRouter, withTerminology } from "../../testing/storybook-helpers";
import { OverviewWidgetGrid } from "./OverviewWidgetGrid";

const ok = (
  label: string, value: number | null, unit: "count" | "percent" = "count", breakdown: OverviewMetricResult["breakdown"] = null, projects = 1,
): OverviewMetricResult => ({ state: "ok", unit, label, value, breakdown, projects });
const widget = (id: string, type: string, config: Record<string, unknown>, extra: Partial<OverviewWidget> = {}): OverviewWidget => ({
  id, type, title: null, width: 3, height: 2, scope: null, visible: true, config, ...extra,
});

const widgets: OverviewWidget[] = [
  widget("files", "metric_tile", { metric: "file_count" }),
  widget("risks", "metric_tile", { metric: "record_count", params: { record_type: "risk", filters: { component: ["SW"] } } }, { title: "Risks in Software" }),
  widget("gauge", "gauge", { metric: "change_requests_proposed", minimum: 0, maximum: 20, warning: 5, critical: 10 }, { title: "Open change requests" }),
  widget("status", "status_chart", { metric: "requirements_by_status", chart: "pie" }),
  widget("bars", "status_chart", { metric: "change_requests_by_outcome", chart: "bar" }, { width: 6, height: 4 }),
  widget("stages", "stage_progress", {}),
  widget("totals", "record_totals", {}),
  widget("hidden", "metric_tile", { metric: "requirement_count" }, { visible: false }),
  widget("ghost", "ghost:thing", {}),
  widget("secret", "metric_tile", { metric: "record_count", params: { record_type: "decision" } }, { title: "Decisions" }),
  widget("slow", "metric_tile", { metric: "requirement_count" }, { title: "Slow figure" }),
  widget("activity", "activity", { limit: 1 }, { width: 12, height: 6 }),
  widget("note", "text", { markdown: "## Release freeze\n\nNo merges after **Friday**. See [the plan](https://example.com/plan)." }, { width: 6, height: 3, title: "Notes" }),
];

const results: Record<string, OverviewMetricResult> = {
  files: ok("Files", 8),
  risks: ok("Risks", 3),
  gauge: ok("Change requests proposed", 7),
  status: ok("Requirements by status", null, "count", [
    { key: "draft", label: "draft", value: 4, detail: null }, { key: "approved", label: "approved", value: 15, detail: null },
  ]),
  bars: ok("Change requests by outcome", null, "count", [
    { key: "active", label: "Proposed", value: 5, detail: null }, { key: "approved", label: "Approved", value: 12, detail: null },
  ]),
  stages: ok("Stage progress", null, "percent", [{ key: "s1", label: "Scoping", value: 100, detail: "Completed" }]),
  totals: ok("Records by type", 37, "count", [
    { key: "requirement", label: "Requirements", value: 24, detail: null }, { key: "risk", label: "Risks", value: 13, detail: null },
  ]),
  secret: { state: "unavailable", unit: "count", label: "Decisions", value: null, breakdown: null, projects: 1 },
  slow: { state: "timeout", unit: "count", label: "Requirements", value: null, breakdown: null, projects: 1 },
};
const metrics: OverviewMetricsState = { results, error: null };

const meta: Meta<typeof OverviewWidgetGrid> = {
  title: "Components/Overview/OverviewWidgetGrid",
  component: OverviewWidgetGrid,
  decorators: [withRouter("/projects/project-1", "/projects/:projectId"), withTerminology()],
  args: { widgets, metrics, projectId: "project-1", scope: "this" },
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.endsWith("/changes")) return [buildChangeEntry({ action: "updated", actor_display_name: "Alex Morgan" }), buildChangeEntry({ actor_display_name: "Sam Lee" })];
      return [];
    });
  },
};
export default meta;

type Story = StoryObj<typeof OverviewWidgetGrid>;

export const AllWidgetTypes: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    // Tile: the figure and a link to the list it summarises.
    await expect(canvas.getByRole("link", { name: /8\s*Files/ })).toHaveAttribute("href", "/projects/project-1/files");
    // A record count with a component filter has no list that shows exactly that figure, so it is not a link.
    const risks = canvas.getByText("Risks in Software").closest("[data-stat-entry]") as HTMLElement;
    await expect(within(risks).getByText("3")).toBeInTheDocument();
    await expect(risks.tagName).toBe("DIV");
    // Gauge: 7 is at or above the warning level (5) and below the critical level (10).
    await expect(canvas.getByRole("img", { name: "Open change requests: 7, Warning" })).toBeInTheDocument();
    // Pie chart rows use the status label map, never the raw status.
    await expect(canvas.getByText("Requirements by status")).toBeInTheDocument();
    // Bar chart with a link to the matching list.
    await expect(canvas.getByRole("link", { name: /proposed/i })).toHaveAttribute("href", "/projects/project-1/change-requests?status=active");
    // Stage progress with the phase badge and its own link.
    await expect(canvas.getByRole("link", { name: /Scoping/ })).toHaveAttribute("href", "/projects/project-1/requirements?stage=s1");
    // Record totals: the total in the centre, one legend row per type.
    const totals = canvas.getByText("Total records").closest(".card") as HTMLElement;
    await expect(within(totals).getByText("37")).toBeInTheDocument();
    await expect(within(totals).getByRole("button", { name: /Risks/ })).toBeInTheDocument();
    // The activity feed reads its own data and honours its limit.
    await expect(await canvas.findByText("Alex Morgan updated")).toBeInTheDocument();
    await expect(canvas.queryByText("Sam Lee updated")).not.toBeInTheDocument();
  },
};

export const HiddenWidgetsAreNotDrawn: Story = {
  play: async ({ canvasElement }) => {
    await expect(canvasElement.querySelector('[data-widget-id="hidden"]')).toBeNull();
    await expect(canvasElement.querySelector('[data-widget-id="files"]')).not.toBeNull();
  },
};

/** A figure the caller may not read, or one that was too slow, says so in words; it is never a zero. */
export const UnavailableAndSlowFiguresSayWhy: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const secret = canvasElement.querySelector('[data-widget-id="secret"]') as HTMLElement;
    await expect(within(secret).getByText("This figure is not available to you.")).toBeInTheDocument();
    await expect(within(secret).queryByText("0")).not.toBeInTheDocument();
    await expect(canvas.getByText("This figure took too long to load.")).toBeInTheDocument();
  },
};

/** A widget type of a module that is no longer installed is a notice, not a crash. */
export const UnknownModuleWidgetIsANotice: Story = {
  play: async ({ canvasElement }) => {
    const ghost = canvasElement.querySelector('[data-widget-id="ghost"]') as HTMLElement;
    await expect(within(ghost).getByText("This widget is no longer available.")).toBeInTheDocument();
  },
};

export const WidgetSizesBecomeGridSpans: Story = {
  play: async ({ canvasElement }) => {
    const bars = canvasElement.querySelector<HTMLElement>('[data-widget-id="bars"]');
    await expect(bars?.style.getPropertyValue("--w")).toBe("6");
    await expect(bars?.style.getPropertyValue("--h")).toBe("4");
    // A medium screen has six columns, so a width of 6 becomes 3; a small tile stays one column on a phone, a chart takes two.
    await expect(bars?.style.getPropertyValue("--w-md")).toBe("3");
    await expect(bars?.style.getPropertyValue("--w-sm")).toBe("2");
    const tile = canvasElement.querySelector<HTMLElement>('[data-widget-id="files"]');
    await expect(tile?.style.getPropertyValue("--w-sm")).toBe("1");
  },
};

export const LightTheme: Story = { ...AllWidgetTypes, globals: { theme: "light" } };
export const DarkTheme: Story = { ...AllWidgetTypes, globals: { theme: "dark" } };

/** The text widget renders its markdown as elements: a heading, bold text and a web link, and no raw HTML. */
export const TextWidgetShowsItsMarkdown: Story = {
  play: async ({ canvasElement }) => {
    const note = within(canvasElement.querySelector('[data-widget-id="note"]') as HTMLElement);
    await expect(note.getByRole("heading", { name: "Release freeze" })).toBeInTheDocument();
    await expect(note.getByRole("link", { name: "the plan" })).toHaveAttribute("href", "https://example.com/plan");
    await expect(note.getByText("Friday").tagName).toBe("STRONG");
  },
};

/** A figure read beyond this project says so, with how many projects it covers. */
export const WidenedFiguresAreMarked: Story = {
  args: {
    widgets: [widget("kids", "metric_tile", { metric: "requirement_count" }, { scope: "children" }), widget("own", "metric_tile", { metric: "file_count" })],
    metrics: { results: { kids: ok("Requirements", 9, "count", null, 3), own: ok("Files", 8) }, error: null },
  },
  play: async ({ canvasElement }) => {
    const kids = canvasElement.querySelector('[data-widget-id="kids"]') as HTMLElement;
    await expect(within(kids).getByText("With children · 3 projects")).toBeInTheDocument();
    await expect(canvasElement.querySelector('[data-widget-id="own"] .overview-scope-tag')).toBeNull();
  },
};

/** A widget with no scope of its own reads in the overview's, which a widget that never widens ignores. */
export const OverviewScopeAppliesToWidgetsWithNoOverride: Story = {
  args: {
    scope: "both",
    widgets: [widget("tile", "metric_tile", { metric: "file_count" }), widget("stages", "stage_progress", {})],
    metrics: { results: { tile: ok("Files", 8, "count", null, 2), stages: ok("Stage progress", null, "percent", [{ key: "s1", label: "Scoping", value: 100, detail: "Done" }]) }, error: null },
  },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement.querySelector('[data-widget-id="tile"]') as HTMLElement).getByText(/With parents and children/)).toBeInTheDocument();
    await expect(canvasElement.querySelector('[data-widget-id="stages"] .overview-scope-tag')).toBeNull();
  },
};

/** An organisation's default has no data, so each figure widget is a labelled block. */
export const PlaceholdersForAnOrganisationDefault: Story = {
  args: { projectId: undefined, placeholders: true, metrics: { results: null, error: null } },
  play: async ({ canvasElement }) => {
    const block = canvasElement.querySelector('[data-widget-id="gauge"] [data-placeholder]') as HTMLElement;
    await expect(within(block).getByText("Open change requests")).toBeInTheDocument();
    await expect(within(block).getByText("Gauge")).toBeInTheDocument();
    // The text widget still shows its note.
    await expect(canvasElement.querySelector('[data-widget-id="note"] h4')).not.toBeNull();
  },
};

const twoWidgets = [widget("a", "metric_tile", { metric: "file_count" }), widget("b", "metric_tile", { metric: "requirement_count" }, { title: "Second", visible: false })];
const editArgs = {
  widgets: twoWidgets,
  metrics: { results: { a: ok("Files", 8), b: ok("Requirements", 3) }, error: null } as OverviewMetricsState,
};

/** In edit mode every widget, hidden ones included (dimmed), has its tools and a resize corner, and tiles are not links. */
export const EditModeShowsToolsOnEveryWidget: Story = {
  args: { ...editArgs, edit: { onChange: fn(), onOpenSettings: fn() } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvasElement.querySelectorAll("[data-widget-id]")).toHaveLength(2);
    await expect(canvasElement.querySelector('[data-widget-id="b"]')).toHaveAttribute("data-hidden");
    await expect(canvas.getByText("Hidden. It is not shown on the overview until you show it.")).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Resize Files" })).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Show Second" })).toHaveAttribute("aria-pressed", "true");
    // A tile is not a link while editing, so a click on it never leaves the page.
    await expect(canvas.queryByRole("link")).not.toBeInTheDocument();
  },
};

export const EditModeButtonsChangeTheLayout: Story = {
  args: { ...editArgs, edit: { onChange: fn(), onOpenSettings: fn() } },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Hide Files" }));
    await expect(args.edit?.onChange).toHaveBeenLastCalledWith([{ ...twoWidgets[0], visible: false }, twoWidgets[1]]);
    await userEvent.click(canvas.getByRole("button", { name: "Remove Files" }));
    await expect(args.edit?.onChange).toHaveBeenLastCalledWith([twoWidgets[1]]);
    await userEvent.click(canvas.getByRole("button", { name: "Settings for Files" }));
    await expect(args.edit?.onOpenSettings).toHaveBeenCalledWith("a");
  },
};

/** The arrow keys on the move handle reorder; on the resize corner they change the width and height (the keyboard route). */
export const EditModeKeyboardMovesAndResizes: Story = {
  args: { ...editArgs, edit: { onChange: fn(), onOpenSettings: fn() } },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const grip = canvas.getByRole("button", { name: "Move Files" });
    grip.focus();
    await userEvent.keyboard("{ArrowRight}");
    await expect(args.edit?.onChange).toHaveBeenLastCalledWith([twoWidgets[1], twoWidgets[0]]);
    await expect(await canvas.findByText("Files moved to position 2 of 2.")).toBeInTheDocument();
    const corner = canvas.getByRole("button", { name: "Resize Files" });
    corner.focus();
    await userEvent.keyboard("{ArrowRight}");
    await expect(args.edit?.onChange).toHaveBeenLastCalledWith([{ ...twoWidgets[0], width: 4 }, twoWidgets[1]]);
    await expect(await canvas.findByText("Files is now 4 columns wide and 2 rows tall.")).toBeInTheDocument();
    await userEvent.keyboard("{ArrowDown}");
    await expect(args.edit?.onChange).toHaveBeenLastCalledWith([{ ...twoWidgets[0], height: 3 }, twoWidgets[1]]);
  },
};
