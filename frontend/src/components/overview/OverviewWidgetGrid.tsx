/**
 * Module: components/overview/OverviewWidgetGrid
 *
 * Draws the project overview's widgets in a 12-column grid, one cell per visible widget, in layout order, each as
 * wide as its width and at least as tall as its height. With `edit` the same grid is the editor: every widget
 * (hidden ones too, dimmed) gets a handle to drag it to a new place, a corner to resize it, and buttons for its
 * settings, hiding and removing, so the page is edited as it will look.
 *
 * Responsibilities:
 * - Turn each widget and its figure (`OverviewMetricResult`) into the right view: a metric tile, a gauge, a pie
 *   or bar chart, stage progress, record totals, the activity feed, the tiles enabled modules contribute, or a
 *   widget a module contributes itself.
 * - Show a notice, not a zero, for a figure the caller may not read, that timed out or failed.
 * - Link a tile or chart row to the list it summarises, only where a list shows exactly that figure.
 * - Mark a figure read beyond this project ("With children, 3 projects"), so a count is never mistaken for one project's.
 *
 * Design decisions:
 * - The grid is a flow with spans, not absolute positions, so it collapses to six columns on a medium screen and two on a
 *   phone with no second layout (`gridSpans`); dragging reorders the flow and the corner changes the spans.
 * - The grid never imports a module: module tiles and widgets come from the registry
 *   (`overviewWidgets`), so a module needs no edit here; a module's widget is as movable and resizable as any other.
 * - Default titles come from the string table for core metrics (so they follow the project's terminology) and
 *   from the server's metric label for any other (a module's, or a record type's plural name).
 * - Figures arrive in one batched request made by the page (`useOverviewMetrics`); the activity feed is the one
 *   widget that reads its own data, because it is a list of changes, not a figure.
 */
import { GripVertical, Eye, EyeOff, MoveDiagonal2, SlidersHorizontal, Trash2 } from "lucide-react";
import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent as ReactPointerEvent } from "react";
import { Link, useNavigate } from "react-router-dom";

import { ApiError, api } from "../../api/client";
import type { ChangeEntry, OverviewScope, OverviewWidget } from "../../api/types";
import { activityEntityLabel, activityEntryLink, activityEntryNotes, describeActivityEntry } from "../../api/types";
import type { ProjectScope } from "../../api/projectScope";
import { useOrgLabelCapitalized } from "../../context/BrandingContext";
import { useStrings } from "../../context/TerminologyContext";
import type { OverviewMetricsState } from "../../hooks/useOverviewMetrics";
import { getInstalledModule } from "../../modules/registry";
import { buildRecordTotalsChart, RECORD_SLICE_COLORS } from "../../utils/recordTotals";
import { renderMarkdown } from "../../utils/safeMarkdown";
import {
  chartDestination, clamp, effectiveScope, formatMetricValue, gridSpans, isScopedType, moveWidgetTo, orgTileDestination, OVERVIEW_COLUMNS,
  OVERVIEW_MAX_ROWS, resizedBy, tileDestination,
} from "../../utils/overviewWidgets";
import { ActivityNote } from "../ActivityNote";
import { rowLabel, titleOf } from "./overviewTitles";
import { Badge } from "../Badge";
import { BarChart } from "../BarChart";
import { Gauge } from "../Gauge";
import { MetricTile } from "../MetricTile";
import { Spinner } from "../Spinner";
import { StatusPieChart } from "../StatusPieChart";
import { Tooltip } from "../Tooltip";

/** A card saying why a figure is not shown. */
function Notice({ title, message }: { title: string; message: string }) {
  return (
    <div className="card stack">
      <div className="text-muted">{title}</div>
      <p className="text-muted">{message}</p>
    </div>
  );
}

/** The widget's latest changes, read on its own (a feed, not a figure). */
function ActivityWidget({ projectId, title, limit }: { projectId: string; title: string; limit: number }) {
  const strings = useStrings();
  const orgLabelCap = useOrgLabelCapitalized();
  const [entries, setEntries] = useState<ChangeEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    api
      .get<ChangeEntry[]>(`/api/v1/projects/${projectId}/changes`)
      .then((all) => {
        if (!cancelled) setEntries(all.slice(0, limit));
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : strings.overviewWidgets.figureError);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, limit, strings.overviewWidgets.figureError]);
  if (error) return <Notice title={title} message={error} />;
  return (
    <div className="card stack">
      <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{title}</h2>
      {entries && entries.length === 0 && <p className="text-muted">{strings.history.empty}</p>}
      {entries?.map((c, idx) => {
        const link = activityEntryLink(c, projectId);
        return (
          <div
            key={idx}
            className="row"
            style={{ justifyContent: "space-between", borderBottom: "1px solid var(--color-border)", paddingBottom: "var(--space-3)" }}
          >
            <span className="stack" style={{ gap: "var(--space-1)", minWidth: 0 }}>
              <span>
                <Badge>{activityEntityLabel(c.entity_type, orgLabelCap)}</Badge> {describeActivityEntry(c)}
                {link && (
                  <>
                    {" "}
                    <Link to={link.to}>{link.label}</Link>
                  </>
                )}
              </span>
              {activityEntryNotes(c).map((note) => <ActivityNote key={note} text={note} />)}
            </span>
            <span className="text-muted">{new Date(c.timestamp).toLocaleString()}</span>
          </div>
        );
      })}
    </div>
  );
}

/**
 * A widget a module contributes, drawn by the module's own renderer. While editing, its name is shown above it, so a
 * widget that has nothing to show for this project (a module with no tile yet) is still a block that can be moved,
 * hidden or removed.
 */
function ModuleWidget({
  widget, projectId, organizationId, projectScope, title, editingName,
}: {
  widget: OverviewWidget; projectId?: string; organizationId?: string; projectScope: ProjectScope; title: string; editingName?: string;
}) {
  const strings = useStrings();
  const [moduleKey, widgetKey] = widget.type.split(":");
  const installed = getInstalledModule(moduleKey);
  const organizationRenderer = organizationId !== undefined ? installed?.orgOverviewWidgets?.find((w) => w.key === widgetKey) : undefined;
  const projectRenderer = organizationId === undefined && projectId !== undefined ? installed?.overviewWidgets?.find((w) => w.key === widgetKey) : undefined;
  if (organizationId === undefined ? !projectRenderer : !organizationRenderer) {
    return <Notice title={title || editingName || widget.type} message={strings.overviewWidgets.widgetUnknown} />;
  }
  const drawn = organizationId !== undefined
    ? organizationRenderer?.render({ orgId: organizationId, title, config: widget.config })
    : projectRenderer?.render({ projectId: projectId ?? "", projectScope, title, config: widget.config });
  if (editingName === undefined) return <>{drawn}</>;
  return (
    <div className="stack" style={{ gap: "var(--space-1)" }}>
      <span className="text-muted">{editingName}</span>
      {drawn}
    </div>
  );
}

/** What the editor lets the grid do to the layout; omit it for the read-only overview. */
export interface OverviewGridEdit {
  /** Called with the whole layout after a drag, a resize, a hide or a remove. */
  onChange: (widgets: OverviewWidget[]) => void;
  /** Opens the widget's settings. */
  onOpenSettings: (id: string) => void;
}

/** The text widget: its title (when it has one) and its markdown, rendered without raw HTML or images. */
function TextWidget({ title, markdown }: { title: string; markdown: string }) {
  return (
    <div className="card overview-text">
      {title && <h2 style={{ margin: 0, fontSize: "1.1rem" }}>{title}</h2>}
      {renderMarkdown(markdown)}
    </div>
  );
}

/**
 * @param widgets The layout in force (or, when editing, the draft).
 * @param scope The overview's project scope; a widget with its own scope reads in that one.
 * @param metrics The figures by widget id (`useOverviewMetrics`); ignored with `placeholders`.
 * @param projectId The project; omitted for an organisation (a dashboard, or its default project layout, which has no data).
 * @param organizationId The organisation, for one of its dashboards: the figures are the organisation's and a module's
 *   widget is drawn by its organisation renderer.
 * @param placeholders Draw a labelled block for each figure widget instead of its data (an organisation's default).
 * @param edit Makes the grid the editor.
 * @param typeLabels Names of the widget types by key (the editor's catalogue), for a module's widget, which the string table does not name.
 */
export function OverviewWidgetGrid({
  widgets, scope, metrics, projectId, organizationId, placeholders = false, edit, typeLabels,
}: {
  widgets: OverviewWidget[]; scope: OverviewScope; metrics: OverviewMetricsState; projectId?: string; organizationId?: string;
  placeholders?: boolean; edit?: OverviewGridEdit;
  typeLabels?: Record<string, string>;
}) {
  const strings = useStrings();
  const navigate = useNavigate();
  const notices = strings.overviewWidgets;
  const gridRef = useRef<HTMLDivElement>(null);
  const [drag, setDrag] = useState<{ id: string; overId: string | null; after: boolean } | null>(null);
  const [resizingId, setResizingId] = useState<string | null>(null);
  const [announcement, setAnnouncement] = useState("");

  const nameOf = (widget: OverviewWidget) =>
    titleOf(widget, metrics.results?.[widget.id], strings) || typeLabels?.[widget.type] || notices.typeLabel[widget.type] || widget.type;

  const view = (widget: OverviewWidget) => {
    const result = metrics.results?.[widget.id];
    const title = titleOf(widget, result, strings);
    const projectScope = effectiveScope(widget, scope);
    if (widget.type === "text") return <TextWidget title={widget.title ?? ""} markdown={String(widget.config.markdown ?? "")} />;
    if (edit && !widget.visible) return <Notice title={nameOf(widget)} message={notices.hiddenNotice} />;
    if (placeholders || (!projectId && !organizationId)) {
      return (
        <div className="card stack" data-placeholder>
          <strong>{nameOf(widget)}</strong>
          <span className="text-muted">{notices.typeLabel[widget.type] ?? widget.type}</span>
        </div>
      );
    }
    const tileTo = (metricKey: string, config: Record<string, unknown>) =>
      projectId ? tileDestination(metricKey, config, projectId) : orgTileDestination(metricKey);
    const chartTo = (metricKey: string, rowKey: string) => (projectId ? chartDestination(metricKey, rowKey, projectId) : null);
    const needsFigure = ["metric_tile", "gauge", "status_chart", "stage_progress", "record_totals"].includes(widget.type);
    if (needsFigure) {
      if (!result) return <div className="card"><Spinner /></div>;
      if (result.state === "unavailable") return <Notice title={title} message={notices.figureUnavailable} />;
      if (result.state === "timeout") return <Notice title={title} message={notices.figureTimeout} />;
      if (result.state === "error") return <Notice title={title} message={notices.figureError} />;
    }
    const metric = typeof widget.config.metric === "string" ? widget.config.metric : "";
    const params = (widget.config.params as Record<string, unknown> | undefined) ?? {};
    switch (widget.type) {
      case "metric_tile":
        return <MetricTile label={title} value={formatMetricValue(result?.value ?? 0, result?.unit ?? null)} to={edit ? null : tileTo(metric, params)} />;
      case "gauge": {
        const levels = widget.config as { minimum?: number; maximum?: number; warning?: number; critical?: number; direction?: "above" | "below" };
        return (
          <div className="card stack" style={{ alignItems: "center" }}>
            <div className="text-muted">{title}</div>
            <Gauge
              value={result?.value ?? 0} valueText={formatMetricValue(result?.value ?? 0, result?.unit ?? null)}
              minimum={levels.minimum ?? 0} maximum={levels.maximum ?? 100} warning={levels.warning} critical={levels.critical}
              direction={levels.direction} label={title} ariaLabel={notices.gaugeAria}
              levelLabels={{ ok: notices.levelOk, warning: notices.levelWarning, critical: notices.levelCritical }}
            />
          </div>
        );
      }
      case "status_chart": {
        const rows = (result?.breakdown ?? []).map((r) => ({ ...r, label: rowLabel(metric, r.key, r.label, strings) }));
        if (widget.config.chart === "bar") {
          return (
            <BarChart
              title={title} ariaLabel={notices.barAria}
              rows={rows.map((r) => ({
                key: r.key, label: r.label, value: r.value, valueText: formatMetricValue(r.value, result?.unit ?? null),
                to: edit ? null : chartTo(metric, r.key),
              }))}
            />
          );
        }
        return (
          <StatusPieChart
            title={title} segments={rows.map((r) => [r.label, r.value])}
            onSegmentClick={edit ? undefined : (_, idx) => {
              const to = chartTo(metric, rows[idx].key);
              if (to) navigate(to);
            }}
          />
        );
      }
      case "stage_progress":
        if (!projectId) return null;
        return (
          <div className="card stack">
            <div className="text-muted">{title}</div>
            {(result?.breakdown ?? []).map((s) => (
              <Link
                key={s.key} to={edit ? "#" : chartDestination("stage_progress", s.key, projectId) ?? "#"}
                className="stack" style={{ gap: "0.2rem", textDecoration: "none", color: "inherit" }}
              >
                <div className="row" style={{ justifyContent: "space-between", fontSize: "0.85rem" }}>
                  <span>
                    {s.label} {s.detail && <Badge>{s.detail}</Badge>}
                  </span>
                  <span className="text-muted">{s.value}%</span>
                </div>
                <div style={{ background: "var(--color-surface-alt)", borderRadius: "var(--radius-sm)", height: 8, overflow: "hidden" }}>
                  <div style={{ width: `${s.value}%`, background: "var(--color-primary)", height: "100%" }} />
                </div>
              </Link>
            ))}
          </div>
        );
      case "record_totals": {
        if (!projectId) return null;
        const total = result?.value ?? 0;
        if (total <= 0) {
          return (
            <div className="card stack">
              <div className="text-muted">{title}</div>
              <p className="text-muted">{strings.overview.noRecords}</p>
            </div>
          );
        }
        const chart = buildRecordTotalsChart(
          (result?.breakdown ?? []).map((r) => ({ type: r.key, label: rowLabel("records_by_type", r.key, r.label, strings), count: r.value })),
          strings.overview.otherRecords,
        );
        const open = (type: string | null) => {
          const to = type && !edit ? chartDestination("records_by_type", type, projectId) : null;
          if (to) navigate(to);
        };
        return (
          <StatusPieChart
            title={title} segments={chart.segments} colors={RECORD_SLICE_COLORS}
            legend={chart.legend.map((row) => ({ label: row.label, value: row.count, segment: row.segment, onClick: edit ? undefined : () => open(row.type) }))}
            onSegmentClick={edit ? undefined : (_, idx) => open(chart.segmentTypes[idx])}
          />
        );
      }
      case "activity":
        if (!projectId) return null;
        return <ActivityWidget projectId={projectId} title={title} limit={typeof widget.config.limit === "number" ? widget.config.limit : 8} />;
      default:
        return <ModuleWidget widget={widget} projectId={projectId} organizationId={organizationId} projectScope={projectScope} title={title} editingName={edit ? nameOf(widget) : undefined} />;
    }
  };

  // --- editing ------------------------------------------------------------------------------------

  const replace = (next: OverviewWidget) => edit?.onChange(widgets.map((w) => (w.id === next.id ? next : w)));
  const announce = (text: string) => setAnnouncement(text);

  /** One column and one row of the grid including the gap, in pixels, read from the rendered grid. */
  const pitch = () => {
    const grid = gridRef.current;
    if (!grid) return { column: 1, row: 1 };
    const style = getComputedStyle(grid);
    const gap = parseFloat(style.columnGap) || 0;
    return {
      column: (grid.clientWidth + gap) / OVERVIEW_COLUMNS,
      row: (parseFloat(style.getPropertyValue("--overview-row")) || 44) + (parseFloat(style.rowGap) || 0),
    };
  };

  /** Scrolls the page while a drag or a resize is near the top or the bottom of the window, so a far place can be reached. */
  const autoScroll = (clientY: number) => {
    const edge = 72;
    const step = clientY < edge ? -18 : clientY > window.innerHeight - edge ? 18 : 0;
    if (step === 0) return;
    let node: HTMLElement | null = gridRef.current?.parentElement ?? null;
    while (node && node !== document.body) {
      const overflow = getComputedStyle(node).overflowY;
      if ((overflow === "auto" || overflow === "scroll") && node.scrollHeight > node.clientHeight) {
        node.scrollBy(0, step);
        return;
      }
      node = node.parentElement;
    }
    window.scrollBy(0, step);
  };

  const startDrag = (event: ReactPointerEvent<HTMLButtonElement>, widget: OverviewWidget) => {
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    setDrag({ id: widget.id, overId: null, after: false });
  };
  const moveDrag = (event: ReactPointerEvent<HTMLButtonElement>) => {
    if (!drag) return;
    autoScroll(event.clientY);
    const under = document.elementsFromPoint(event.clientX, event.clientY)
      .map((el) => el.closest<HTMLElement>("[data-widget-id]"))
      .find((el) => el && el.dataset.widgetId !== drag.id && gridRef.current?.contains(el));
    if (!under) return setDrag({ ...drag, overId: null });
    const rect = under.getBoundingClientRect();
    const fullWidth = rect.width >= (gridRef.current?.clientWidth ?? 0) * 0.9;
    const after = fullWidth ? event.clientY > rect.top + rect.height / 2 : event.clientX > rect.left + rect.width / 2;
    setDrag({ ...drag, overId: under.dataset.widgetId ?? null, after });
  };
  const endDrag = () => {
    if (drag?.overId) {
      const from = widgets.findIndex((w) => w.id === drag.id);
      const over = widgets.findIndex((w) => w.id === drag.overId);
      // Dropping after the target; moving forward past it shifts the target down one place.
      const to = drag.after ? (from < over ? over : over + 1) : (from < over ? over - 1 : over);
      edit?.onChange(moveWidgetTo(widgets, from, to));
    }
    setDrag(null);
  };
  const keyMove = (event: KeyboardEvent<HTMLButtonElement>, widget: OverviewWidget, index: number) => {
    const delta = event.key === "ArrowLeft" || event.key === "ArrowUp" ? -1 : event.key === "ArrowRight" || event.key === "ArrowDown" ? 1 : 0;
    if (delta === 0) return;
    event.preventDefault();
    const to = clamp(index + delta, 0, widgets.length - 1);
    if (to === index) return;
    edit?.onChange(moveWidgetTo(widgets, index, to));
    announce(notices.movedTo(nameOf(widget), to + 1, widgets.length));
  };

  const resize = useRef<{ x: number; y: number; width: number; height: number } | null>(null);
  const startResize = (event: ReactPointerEvent<HTMLButtonElement>, widget: OverviewWidget) => {
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    resize.current = { x: event.clientX, y: event.clientY, width: widget.width, height: widget.height };
    setResizingId(widget.id);
  };
  const endResize = () => {
    resize.current = null;
    setResizingId(null);
  };
  const moveResize = (event: ReactPointerEvent<HTMLButtonElement>, widget: OverviewWidget) => {
    const start = resize.current;
    if (!start) return;
    autoScroll(event.clientY);
    const size = resizedBy(start, { x: event.clientX - start.x, y: event.clientY - start.y }, pitch());
    if (size.width !== widget.width || size.height !== widget.height) replace({ ...widget, ...size });
  };
  const keyResize = (event: KeyboardEvent<HTMLButtonElement>, widget: OverviewWidget) => {
    const dx = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
    const dy = event.key === "ArrowDown" ? 1 : event.key === "ArrowUp" ? -1 : 0;
    if (dx === 0 && dy === 0) return;
    event.preventDefault();
    const width = clamp(widget.width + dx, 1, OVERVIEW_COLUMNS);
    const height = clamp(widget.height + dy, 1, OVERVIEW_MAX_ROWS);
    replace({ ...widget, width, height });
    announce(notices.resizedTo(nameOf(widget), width, height));
  };

  const shown = edit ? widgets : widgets.filter((w) => w.visible);
  return (
    <div className="overview-grid" ref={gridRef} data-editing={edit ? "true" : undefined}>
      {shown.map((widget, index) => {
        const result = metrics.results?.[widget.id];
        const resolved = effectiveScope(widget, scope);
        const name = nameOf(widget);
        const dragging = drag?.id === widget.id;
        return (
          <div
            key={widget.id}
            className={`overview-widget${edit ? " overview-widget-editing" : ""}`}
            style={gridSpans(widget) as React.CSSProperties}
            data-widget-id={widget.id} data-widget-type={widget.type}
            data-hidden={!widget.visible || undefined} data-dragging={dragging || undefined} data-active={dragging || resizingId === widget.id || undefined}
            data-drop={drag?.overId === widget.id ? (drag.after ? "after" : "before") : undefined}
          >
            {view(widget)}
            {isScopedType(widget.type) && resolved !== "this" && !placeholders && (
              <span className="overview-scope-tag text-muted">
                {notices.scopeTag[resolved]}{result && result.projects > 1 ? ` · ${notices.projectCount(result.projects)}` : ""}
              </span>
            )}
            {edit && (
              <>
                <div className="overview-edit-tools" role="group" aria-label={notices.toolsFor(name)}>
                  <Tooltip label={notices.move(name)} wrap>
                    <button
                      type="button" className="btn overview-grip" aria-label={notices.move(name)} aria-describedby="overview-edit-help"
                      onPointerDown={(e) => startDrag(e, widget)} onPointerMove={moveDrag} onPointerUp={endDrag} onPointerCancel={() => setDrag(null)}
                      onKeyDown={(e) => keyMove(e, widget, index)}
                    >
                      <GripVertical />
                    </button>
                  </Tooltip>
                  <Tooltip label={notices.editSettings(name)} wrap>
                    <button type="button" className="btn" aria-label={notices.editSettings(name)} onClick={() => edit.onOpenSettings(widget.id)}>
                      <SlidersHorizontal />
                    </button>
                  </Tooltip>
                  <Tooltip label={widget.visible ? notices.hide(name) : notices.show(name)} wrap>
                    <button
                      type="button" className="btn" aria-label={widget.visible ? notices.hide(name) : notices.show(name)}
                      aria-pressed={!widget.visible} onClick={() => replace({ ...widget, visible: !widget.visible })}
                    >
                      {widget.visible ? <Eye /> : <EyeOff />}
                    </button>
                  </Tooltip>
                  <Tooltip label={notices.remove(name)} wrap>
                    <button
                      type="button" className="btn btn-danger" aria-label={notices.remove(name)}
                      onClick={() => edit.onChange(widgets.filter((w) => w.id !== widget.id))}
                    >
                      <Trash2 />
                    </button>
                  </Tooltip>
                </div>
                <button
                  type="button" className="overview-resize" aria-label={notices.resize(name)} aria-describedby="overview-edit-help"
                  onPointerDown={(e) => startResize(e, widget)} onPointerMove={(e) => moveResize(e, widget)}
                  onPointerUp={endResize} onPointerCancel={endResize}
                  onKeyDown={(e) => keyResize(e, widget)}
                >
                  <MoveDiagonal2 />
                </button>
              </>
            )}
          </div>
        );
      })}
      {edit && (
        <>
          <span id="overview-edit-help" hidden>{notices.editKeys}</span>
          <span className="sr-only" role="status" aria-live="polite">{announcement}</span>
        </>
      )}
    </div>
  );
}
