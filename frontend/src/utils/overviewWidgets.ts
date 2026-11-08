/**
 * Module: utils/overviewWidgets
 *
 * Pure helpers behind the project overview's widgets: which metric a widget reads and in which project scope,
 * where a figure links to, how a gauge reads its level, how a widget is laid out on the grid, and how a layout
 * is edited (move, resize, add, id).
 *
 * Design decisions:
 * - A tile or chart links to a list only when the list can show what the figure counts; a record count with a
 *   component or provider filter has no matching list URL, so it is not a link rather than a misleading one.
 * - The grid is a flow, not absolute positions: a widget has a width in columns of a 12-column grid and a height
 *   in rows, and the page collapses the columns for a narrower screen (`gridSpans`), so one layout serves every
 *   screen size.
 * - Layout edits return new arrays; the editor owns the draft.
 */
import type { OverviewCatalogue, OverviewMetricSpec, OverviewScope, OverviewWidget } from "../api/types";
import { getArtefactListPath } from "../modules/artefactPaths";

/** Columns of the overview grid, and the most rows a widget may span. */
export const OVERVIEW_COLUMNS = 12;
export const OVERVIEW_MAX_ROWS = 12;

/** The scopes a widget of these core types never widens (they always read this project); a module's own types do. */
const UNSCOPED_TYPES = ["stage_progress", "activity", "text"];

/** Whether a widget of `type` can be given a project scope. */
export function isScopedType(type: string): boolean {
  return !UNSCOPED_TYPES.includes(type);
}

/** The scope a widget reads in: its own override, else the overview's. A widget that never widens reads this project. */
export function effectiveScope(widget: OverviewWidget, overviewScope: OverviewScope): OverviewScope {
  return isScopedType(widget.type) ? (widget.scope ?? overviewScope) : "this";
}

/** The metric a widget needs from the metrics endpoint, or `null` when it reads none itself. */
export function widgetMetricSpec(widget: OverviewWidget, overviewScope: OverviewScope): OverviewMetricSpec | null {
  const scope = effectiveScope(widget, overviewScope);
  switch (widget.type) {
    case "metric_tile":
    case "gauge":
    case "status_chart": {
      const metric = widget.config.metric;
      if (typeof metric !== "string") return null;
      return { id: widget.id, metric, params: (widget.config.params as Record<string, unknown> | undefined) ?? {}, scope };
    }
    case "stage_progress":
      return { id: widget.id, metric: "stage_progress", params: {}, scope };
    case "record_totals":
      return { id: widget.id, metric: "records_by_type", params: {}, scope };
    default:
      return null;
  }
}

/** The metric references of the widgets that are shown (a hidden widget requests nothing). */
export function visibleMetricSpecs(widgets: OverviewWidget[], overviewScope: OverviewScope): OverviewMetricSpec[] {
  return widgets.filter((w) => w.visible).flatMap((w) => widgetMetricSpec(w, overviewScope) ?? []);
}

/** The level a gauge shows. */
export type GaugeTone = "ok" | "warning" | "critical";

/**
 * Reads a gauge's level: with `direction` "above" the value is in trouble once it reaches a level, with
 * "below" once it falls to one. A level exactly equal to the value counts as reached. `critical` wins over `warning`.
 */
export function gaugeTone(
  value: number, levels: { warning?: number | null; critical?: number | null; direction?: "above" | "below" },
): GaugeTone {
  const reached = (level: number | null | undefined) =>
    level === null || level === undefined ? false : levels.direction === "below" ? value <= level : value >= level;
  if (reached(levels.critical)) return "critical";
  if (reached(levels.warning)) return "warning";
  return "ok";
}

/** How far along the dial a value is, from 0 to 1 (clamped); 0 when the range is empty. */
export function gaugeFraction(value: number, minimum: number, maximum: number): number {
  if (!(maximum > minimum)) return 0;
  return Math.min(1, Math.max(0, (value - minimum) / (maximum - minimum)));
}

/** A figure as shown: a percentage with its sign, a count as a whole number (grouped), else trimmed to one decimal. */
export function formatMetricValue(value: number, unit: "count" | "percent" | null): string {
  if (unit === "percent") return `${Math.round(value * 10) / 10}%`;
  return Number.isInteger(value) ? value.toLocaleString() : (Math.round(value * 10) / 10).toLocaleString();
}

function filtersOf(params: Record<string, unknown>): Record<string, string[]> {
  return (params.filters as Record<string, string[]> | undefined) ?? {};
}

/**
 * Where a metric tile links: the list its figure summarises, or `null` when no list shows exactly that figure.
 *
 * @param metric The metric key.
 * @param params The widget's metric params.
 * @param projectId The project.
 */
export function tileDestination(metric: string, params: Record<string, unknown>, projectId: string): string | null {
  const base = `/projects/${projectId}`;
  switch (metric) {
    case "requirement_count": return `${base}/requirements`;
    case "requirement_completed_percent": return `${base}/requirements?completed=1`;
    case "file_count": return `${base}/files`;
    case "change_requests_proposed": return `${base}/change-requests?status=active`;
    case "change_requests_approved": return `${base}/change-requests?status=approved`;
    case "change_requests_rejected": return `${base}/change-requests?status=rejected`;
    case "record_count": {
      const path = getArtefactListPath(String(params.record_type), projectId);
      if (!path) return null;
      const filters = filtersOf(params);
      const names = Object.keys(filters);
      if (names.length === 0) return path;
      // Only the shared tag filter has a URL the list reads; any other filter would make the list disagree with the figure.
      if (names.every((n) => n === "tag" || n === "tag_mode")) {
        const query = new URLSearchParams();
        for (const tag of filters.tag ?? []) query.append("tag", tag);
        if (filters.tag_mode?.[0]) query.set("tag_mode", filters.tag_mode[0]);
        return `${path}?${query.toString()}`;
      }
      return null;
    }
    default: return null;
  }
}

/** Where one row of a chart links, or `null` when no list shows it. */
export function chartDestination(metric: string, rowKey: string, projectId: string): string | null {
  const base = `/projects/${projectId}`;
  switch (metric) {
    case "requirements_by_status": return `${base}/requirements?status=${encodeURIComponent(rowKey)}`;
    case "change_requests_by_outcome": return `${base}/change-requests?status=${encodeURIComponent(rowKey)}`;
    case "stage_progress": return `${base}/requirements?stage=${encodeURIComponent(rowKey)}`;
    case "records_by_type": return getArtefactListPath(rowKey, projectId);
    default: return null;
  }
}

/**
 * The grid spans a widget takes at each screen size, as the CSS variables the grid reads. At 12 columns the span is
 * the width; at 6 columns (a medium screen) half of it; at 2 columns (a phone) a small tile takes one and every other
 * widget the full width, so the figures sit two to a row and the charts and text read at full width.
 */
export function gridSpans(widget: Pick<OverviewWidget, "type" | "width" | "height">): Record<string, number> {
  return {
    "--w": widget.width,
    "--h": widget.height,
    "--w-md": Math.max(1, Math.round(widget.width / 2)),
    "--w-sm": widget.type === "metric_tile" && widget.width < 6 ? 1 : 2,
  };
}

/** `value` held between `low` and `high`. */
export function clamp(value: number, low: number, high: number): number {
  return Math.min(high, Math.max(low, value));
}

/**
 * The size a drag resizes a widget to.
 *
 * @param start The widget's width and height when the drag began.
 * @param deltaPx The pointer's movement since then.
 * @param pitch The size of one column and one row including the gap, in pixels.
 */
export function resizedBy(
  start: { width: number; height: number }, deltaPx: { x: number; y: number }, pitch: { column: number; row: number },
): { width: number; height: number } {
  return {
    width: clamp(start.width + Math.round(deltaPx.x / pitch.column), 1, OVERVIEW_COLUMNS),
    height: clamp(start.height + Math.round(deltaPx.y / pitch.row), 1, OVERVIEW_MAX_ROWS),
  };
}

/** A new widget id: short, unique within a layout and valid for the server (letters, digits, hyphen). */
export function newWidgetId(existing: readonly string[]): string {
  const candidate = `w-${Math.random().toString(36).slice(2, 10)}`;
  return existing.includes(candidate) ? newWidgetId(existing) : candidate;
}

/** `list` with the item at `index` moved one step (clamped); a new array. */
export function moveWidget<T>(list: readonly T[], index: number, delta: -1 | 1): T[] {
  return moveWidgetTo(list, index, index + delta);
}

/** `list` with the item at `from` moved to position `to` (both clamped); a new array. */
export function moveWidgetTo<T>(list: readonly T[], from: number, to: number): T[] {
  const target = clamp(to, 0, list.length - 1);
  if (from < 0 || from >= list.length || from === target) return [...list];
  const next = [...list];
  const [item] = next.splice(from, 1);
  next.splice(target, 0, item);
  return next;
}

/** A new widget of `type` with the settings and size that make it valid and useful at once. */
export function defaultWidget(type: string, catalogue: OverviewCatalogue, existing: readonly string[]): OverviewWidget {
  const id = newWidgetId(existing);
  const base = { id, type, title: null, scope: null, visible: true };
  const scalar = catalogue.metrics.find((m) => m.scalar && m.key !== "record_count") ?? catalogue.metrics.find((m) => m.scalar);
  const breakdown = catalogue.metrics.find((m) => m.breakdown);
  switch (type) {
    case "metric_tile": return { ...base, width: 3, height: 2, config: { metric: scalar?.key ?? "requirement_count" } };
    case "gauge": return { ...base, width: 3, height: 4, config: { metric: scalar?.key ?? "requirement_count", minimum: 0, maximum: 100 } };
    case "status_chart": return { ...base, width: 4, height: 6, config: { metric: breakdown?.key ?? "requirements_by_status", chart: "pie" } };
    case "activity": return { ...base, width: 12, height: 6, config: { limit: 8 } };
    case "text": return { ...base, width: 6, height: 3, config: { markdown: "" } };
    case "stage_progress":
    case "record_totals": return { ...base, width: 3, height: 6, config: {} };
    default: {
      // A module's widget starts at the size its module declared.
      const declared = catalogue.widget_types.find((w) => w.key === type);
      return { ...base, width: declared?.width ?? 4, height: declared?.height ?? 4, config: {} };
    }
  }
}

/** The widgets ready to send: filter rows left blank are removed, and a record count with none left drops its filters. */
export function cleanedForSave(widgets: OverviewWidget[]): OverviewWidget[] {
  return widgets.map((widget) => {
    const params = widget.config.params as { filters?: Record<string, string[]> } | undefined;
    if (!params?.filters) return widget;
    const filters = Object.fromEntries(
      Object.entries(params.filters).map(([name, values]) => [name, values.filter((v) => v.trim() !== "")]).filter(([, values]) => (values as string[]).length > 0),
    );
    const nextParams = { ...params } as Record<string, unknown>;
    if (Object.keys(filters).length > 0) nextParams.filters = filters;
    else delete nextParams.filters;
    return { ...widget, config: { ...widget.config, params: nextParams } };
  });
}
