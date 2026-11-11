import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect } from "storybook/test";

import type { OverviewCatalogue, OverviewWidget } from "../api/types";
import {
  chartDestination, cleanedForSave, defaultWidget, effectiveScope, formatMetricValue, gaugeFraction, gaugeTone, gridSpans, moveWidget, moveWidgetTo,
  newWidgetId, resizedBy, tileDestination, visibleMetricSpecs,
} from "./overviewWidgets";

/** Pure-function checks for the overview widgets' helpers, run as stories like the other helpers. */
const meta: Meta = { title: "Utils/OverviewWidgets" };
export default meta;

type Story = StoryObj;

const widget = (id: string, type: string, config: Record<string, unknown>, visible = true): OverviewWidget => ({
  id, type, title: null, width: 3, height: 2, scope: null, visible, config,
});

export const GaugeLevelsAtTheBoundaries: Story = {
  render: () => <div>Gauge levels</div>,
  play: async () => {
    const above = { warning: 10, critical: 15 };
    await expect(gaugeTone(9.99, above)).toBe("ok");
    await expect(gaugeTone(10, above)).toBe("warning");
    await expect(gaugeTone(14.9, above)).toBe("warning");
    await expect(gaugeTone(15, above)).toBe("critical");
    const below = { warning: 40, critical: 20, direction: "below" as const };
    await expect(gaugeTone(41, below)).toBe("ok");
    await expect(gaugeTone(40, below)).toBe("warning");
    await expect(gaugeTone(20, below)).toBe("critical");
    // No level set means no alarm.
    await expect(gaugeTone(1000, {})).toBe("ok");
    await expect(gaugeTone(5, { warning: null, critical: undefined })).toBe("ok");
  },
};

export const GaugeFractionIsClamped: Story = {
  render: () => <div>Gauge fraction</div>,
  play: async () => {
    await expect(gaugeFraction(5, 0, 10)).toBe(0.5);
    await expect(gaugeFraction(-5, 0, 10)).toBe(0);
    await expect(gaugeFraction(50, 0, 10)).toBe(1);
    await expect(gaugeFraction(5, 10, 10)).toBe(0);
  },
};

export const FiguresAreFormatted: Story = {
  render: () => <div>Formatting</div>,
  play: async () => {
    await expect(formatMetricValue(62, "percent")).toBe("62%");
    await expect(formatMetricValue(62.46, "percent")).toBe("62.5%");
    await expect(formatMetricValue(7, "count")).toBe("7");
    await expect(formatMetricValue(0, null)).toBe("0");
  },
};

export const OnlyVisibleWidgetsRequestFigures: Story = {
  render: () => <div>Specs</div>,
  play: async () => {
    const widgets = [
      widget("a", "metric_tile", { metric: "file_count" }),
      widget("b", "metric_tile", { metric: "requirement_count" }, false),
      widget("c", "stage_progress", {}),
      widget("d", "record_totals", {}),
      widget("e", "activity", { limit: 5 }),
      widget("f", "compliance:standards_status", {}),
      widget("g", "gauge", { metric: "record_count", params: { record_type: "risk" } }),
    ];
    await expect(visibleMetricSpecs(widgets, "this")).toEqual([
      { id: "a", metric: "file_count", params: {}, scope: "this" },
      { id: "c", metric: "stage_progress", params: {}, scope: "this" },
      { id: "d", metric: "records_by_type", params: {}, scope: "this" },
      { id: "g", metric: "record_count", params: { record_type: "risk" }, scope: "this" },
    ]);
  },
};

export const LinksOnlyWhereAListShowsTheFigure: Story = {
  render: () => <div>Destinations</div>,
  play: async () => {
    await expect(tileDestination("requirement_completed_percent", {}, "p1")).toBe("/projects/p1/requirements?completed=1");
    await expect(tileDestination("change_requests_proposed", {}, "p1")).toBe("/projects/p1/change-requests?status=active");
    await expect(tileDestination("unknown_metric", {}, "p1")).toBeNull();
    // A requirement count with a component filter has no list that shows exactly that figure.
    await expect(tileDestination("record_count", { record_type: "requirement", filters: { component: ["SW"] } }, "p1")).toBeNull();
    await expect(tileDestination("record_count", { record_type: "requirement", filters: { tag: ["urgent"] } }, "p1"))
      .toBe("/projects/p1/requirements?tag=urgent");
    await expect(chartDestination("requirements_by_status", "in review", "p1")).toBe("/projects/p1/requirements?status=in%20review");
    await expect(chartDestination("stage_progress", "s1", "p1")).toBe("/projects/p1/requirements?stage=s1");
    await expect(chartDestination("nothing", "x", "p1")).toBeNull();
  },
};

export const LayoutEdits: Story = {
  render: () => <div>Layout edits</div>,
  play: async () => {
    await expect(moveWidget(["a", "b", "c"], 1, -1)).toEqual(["b", "a", "c"]);
    await expect(moveWidget(["a", "b", "c"], 0, -1)).toEqual(["a", "b", "c"]);
    await expect(moveWidget(["a", "b", "c"], 2, 1)).toEqual(["a", "b", "c"]);
    await expect(moveWidgetTo(["a", "b", "c", "d"], 0, 2)).toEqual(["b", "c", "a", "d"]);
    await expect(moveWidgetTo(["a", "b", "c", "d"], 3, 0)).toEqual(["d", "a", "b", "c"]);
    await expect(moveWidgetTo(["a", "b"], 0, 9)).toEqual(["b", "a"]);
    const existing = ["w-aaaa"];
    const id = newWidgetId(existing);
    await expect(id).toMatch(/^w-[a-z0-9]+$/);
    await expect(existing.includes(id)).toBe(false);
  },
};

const catalogue: OverviewCatalogue = {
  widget_types: [],
  metrics: [
    { key: "requirement_count", label: "Requirements", unit: "count", scalar: true, breakdown: false, params: [], module_key: null },
    { key: "record_count", label: "Record count", unit: "count", scalar: true, breakdown: false, params: ["filters", "record_type"], module_key: null },
    { key: "requirements_by_status", label: "Requirements by status", unit: "count", scalar: false, breakdown: true, params: [], module_key: null },
  ],
  record_types: [],
  max_widgets: 24,
};

export const NewWidgetsStartValid: Story = {
  render: () => <div>Defaults</div>,
  play: async () => {
    await expect(defaultWidget("metric_tile", catalogue, []).config).toEqual({ metric: "requirement_count" });
    await expect(defaultWidget("text", catalogue, []).config).toEqual({ markdown: "" });
    const chart = defaultWidget("status_chart", catalogue, []);
    await expect([chart.width, chart.height, chart.scope]).toEqual([4, 6, null]);
    // A module's widget starts at the size its module declared.
    const withModule = { ...catalogue, widget_types: [{ key: "compliance:standards_status", label: "Compliance standards", description: "", module_key: "compliance", width: 12, height: 2 }] };
    const moduleWidget = defaultWidget("compliance:standards_status", withModule, []);
    await expect([moduleWidget.width, moduleWidget.height]).toEqual([12, 2]);
    await expect(defaultWidget("gauge", catalogue, []).config).toEqual({ metric: "requirement_count", minimum: 0, maximum: 100 });
    await expect(defaultWidget("status_chart", catalogue, []).config).toEqual({ metric: "requirements_by_status", chart: "pie" });
    await expect(defaultWidget("activity", catalogue, []).config).toEqual({ limit: 8 });
  },
};

export const BlankFilterRowsAreDroppedBeforeSaving: Story = {
  render: () => <div>Clean</div>,
  play: async () => {
    const dirty = widget("a", "metric_tile", { metric: "record_count", params: { record_type: "risk", filters: { status: [""], tag: ["x", " "] } } });
    const [clean] = cleanedForSave([dirty]);
    await expect(clean.config).toEqual({ metric: "record_count", params: { record_type: "risk", filters: { tag: ["x"] } } });
    const [none] = cleanedForSave([widget("b", "metric_tile", { metric: "record_count", params: { record_type: "risk", filters: { status: [""] } } })]);
    await expect(none.config).toEqual({ metric: "record_count", params: { record_type: "risk" } });
  },
};

export const ScopeFollowsTheOverviewUnlessOverridden: Story = {
  render: () => <div>Scope</div>,
  play: async () => {
    await expect(effectiveScope(widget("a", "metric_tile", {}), "both")).toBe("both");
    await expect(effectiveScope({ ...widget("a", "metric_tile", {}), scope: "children" }, "both")).toBe("children");
    // A widget that never widens reads this project whatever the overview says.
    await expect(effectiveScope(widget("a", "activity", {}), "both")).toBe("this");
    await expect(effectiveScope(widget("a", "text", {}), "both")).toBe("this");
    await expect(effectiveScope(widget("a", "risks:heat_map", {}), "children")).toBe("children");
  },
};

export const WidthsCollapseForNarrowerScreens: Story = {
  render: () => <div>Spans</div>,
  play: async () => {
    await expect(gridSpans({ type: "metric_tile", width: 3, height: 2 })).toEqual({ "--w": 3, "--h": 2, "--w-md": 2, "--w-sm": 1 });
    await expect(gridSpans({ type: "status_chart", width: 3, height: 6 })["--w-sm"]).toBe(2);
    await expect(gridSpans({ type: "metric_tile", width: 6, height: 2 })["--w-sm"]).toBe(2);
    await expect(gridSpans({ type: "text", width: 1, height: 1 })["--w-md"]).toBe(1);
    await expect(gridSpans({ type: "activity", width: 12, height: 6 })["--w-md"]).toBe(6);
  },
};

export const ResizingSnapsToTheGridAndStaysInRange: Story = {
  render: () => <div>Resize</div>,
  play: async () => {
    const pitch = { column: 100, row: 50 };
    await expect(resizedBy({ width: 3, height: 2 }, { x: 0, y: 0 }, pitch)).toEqual({ width: 3, height: 2 });
    // Under half a column is no change; past it snaps to the next.
    await expect(resizedBy({ width: 3, height: 2 }, { x: 49, y: 24 }, pitch)).toEqual({ width: 3, height: 2 });
    await expect(resizedBy({ width: 3, height: 2 }, { x: 51, y: 26 }, pitch)).toEqual({ width: 4, height: 3 });
    await expect(resizedBy({ width: 3, height: 2 }, { x: -1000, y: -1000 }, pitch)).toEqual({ width: 1, height: 1 });
    await expect(resizedBy({ width: 3, height: 2 }, { x: 5000, y: 5000 }, pitch)).toEqual({ width: 12, height: 12 });
  },
};
