import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Cell, Pie, PieChart, ResponsiveContainer } from "recharts";

import { sliceAtPoint } from "../utils/sliceAtPoint";
import { Popover } from "./Popover";

/** The default segment colours, in order; a chart with more segments than colours repeats them (pass `colors` to avoid that). */
const PALETTE = [
  "var(--color-primary)",
  "var(--color-accent)",
  "var(--color-warning)",
  "var(--color-danger)",
  "var(--color-text-muted)",
];

/** How many legend rows show before the rest move behind "+N more". */
const DEFAULT_LEGEND_LIMIT = 5;

/** One legend row: an item, its value, the slice whose colour it wears and an optional click action. */
export interface LegendRow {
  label: string;
  value: number;
  segment: number;
  onClick?: () => void;
}

/** A legend row: a colour dot and name (a button when clickable) beside its value. */
function LegendItem({ row, color }: { row: LegendRow; color: string }) {
  const label = (
    <span className="row" style={{ gap: "var(--space-2)" }}>
      <span style={{ width: 10, height: 10, borderRadius: "50%", background: color, display: "inline-block", flexShrink: 0 }} />
      {row.label}
    </span>
  );
  return (
    <div className="row" style={{ justifyContent: "space-between", gap: "var(--space-3)", fontSize: "0.85rem" }}>
      {row.onClick ? (
        <button
          type="button"
          onClick={row.onClick}
          style={{ background: "none", border: "none", padding: 0, cursor: "pointer", color: "inherit", font: "inherit" }}
        >
          {label}
        </button>
      ) : (
        label
      )}
      <span className="text-muted">{row.value}</span>
    </div>
  );
}

const TOOLTIP_OFFSET_PX = 14;
/**
 * The hover box of a slice, fixed beside the pointer (portalled, so no ancestor clips it; no transition, so it
 * follows the pointer instead of sliding). It flips to the left of / above the pointer near the viewport's
 * right and bottom edges. `members` are the legend rows drawn in the slice and are listed when there are several.
 */
function SliceTooltip({
  x, y, label, value, total, members,
}: { x: number; y: number; label: string; value: number; total: number; members: LegendRow[] }) {
  const ref = useRef<HTMLDivElement>(null);
  // Placed on the DOM node after measuring (as Popover does), not through state, so it never lags a render behind the pointer.
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const { offsetWidth: width, offsetHeight: height } = el;
    const left = x + TOOLTIP_OFFSET_PX + width > window.innerWidth ? x - TOOLTIP_OFFSET_PX - width : x + TOOLTIP_OFFSET_PX;
    const top = y + TOOLTIP_OFFSET_PX + height > window.innerHeight ? y - TOOLTIP_OFFSET_PX - height : y + TOOLTIP_OFFSET_PX;
    el.style.left = `${Math.max(0, left)}px`;
    el.style.top = `${Math.max(0, top)}px`;
  }, [x, y]);
  return (
    <div
      ref={ref}
      role="tooltip"
      className="card"
      style={{
        position: "fixed", left: x + TOOLTIP_OFFSET_PX, top: y + TOOLTIP_OFFSET_PX, zIndex: 1000, pointerEvents: "none",
        padding: "var(--space-2) var(--space-3)", fontSize: "0.85rem", transition: "none", whiteSpace: "nowrap",
      }}
    >
      <strong>{label}</strong>: {value} ({Math.round((value / total) * 100)}%)
      {members.length > 1 && members.map((m) => (
        <div key={m.label} className="text-muted">{m.label}: {m.value}</div>
      ))}
    </div>
  );
}

/**
 * Themed donut/pie chart for dashboard summaries (e.g. requirements by
 * status, change requests by outcome), built on Recharts rather than a
 * bespoke CSS conic-gradient — chosen (UX review) so future custom-dashboard
 * widgets have a real charting library's composable API to build on instead
 * of a one-off. Colours come from the same theme custom properties the
 * previous hand-rolled `DonutChart` used, so it still matches light/dark.
 *
 * By default the legend has one row per segment. A chart that folds several
 * items into one segment (the overview's "Other" slice of record types) passes
 * `legend` instead: one row per item, each pointing at the segment it is part of
 * (`segment`), so the exact numbers stay readable and colour is never the only cue.
 *
 * Hovering a slice shows what it is, its value and its share of the total in a small box that sits beside the
 * pointer and follows it without animating; a slice that stands for several legend rows (the folded "Other")
 * lists them. The legend rows carry the same facts for keyboard and touch.
 *
 * Props:
 * - `segments`: `[label, value]` per slice.
 * - `title`: the caption above the ring.
 * - `onSegmentClick`: fired for a slice or a default legend row.
 * - `colors`: per-slice colours replacing the default palette.
 * - `legend`: custom legend rows; `onClick` makes a row a button.
 * - `legendLimit`: rows shown under the ring before the rest open from a "+N more" popover (default 5), so a
 *   chart with many items keeps the card's height.
 */
export function StatusPieChart({
  segments, title, onSegmentClick, colors = PALETTE, legend, legendLimit = DEFAULT_LEGEND_LIMIT,
}: {
  segments: Array<[string, number]>;
  title: string;
  onSegmentClick?: (label: string, index: number) => void;
  colors?: string[];
  legend?: LegendRow[];
  legendLimit?: number;
}) {
  const [moreOpen, setMoreOpen] = useState(false);
  // The hovered slice and the pointer (viewport coordinates), for the tooltip beside the pointer.
  const [hover, setHover] = useState<{ index: number; x: number; y: number } | null>(null);
  const moreRef = useRef<HTMLButtonElement>(null);
  const hovering = hover !== null;
  useEffect(() => {
    if (!hovering) return undefined;
    const clear = () => setHover(null);
    window.addEventListener("scroll", clear, true);
    window.addEventListener("blur", clear);
    return () => {
      window.removeEventListener("scroll", clear, true);
      window.removeEventListener("blur", clear);
    };
  }, [hovering]);
  const colorOf = (index: number) => colors[index % colors.length];
  const rows: LegendRow[] = legend ?? segments.map(([label, value], idx) => ({
    label, value, segment: idx, onClick: onSegmentClick ? () => onSegmentClick(label, idx) : undefined,
  }));
  const total = segments.reduce((sum, [, v]) => sum + v, 0);
  const data = useMemo(() => segments.map(([label, value]) => ({ label, value })), [segments]);
  // The ring is memoised so a hover (which only moves the tooltip) never re-renders it: Recharts would replace its slice
  // elements under the pointer, and a click that lands on a replaced element is lost.
  const ring = useMemo(
    () => (
      total > 0 ? (
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={data}
              dataKey="value"
              nameKey="label"
              innerRadius={35}
              outerRadius={60}
              startAngle={90}
              endAngle={-270}
              stroke="var(--color-surface)"
              strokeWidth={2}
              isAnimationActive={false}
              onClick={onSegmentClick ? (_, index) => onSegmentClick(segments[index][0], index) : undefined}
              style={onSegmentClick ? { cursor: "pointer" } : undefined}
            >
              {data.map((entry, idx) => (
                <Cell key={entry.label} fill={colors[idx % colors.length]} />
              ))}
            </Pie>
          </PieChart>
        </ResponsiveContainer>
      ) : (
        <div style={{ width: "100%", height: "100%", borderRadius: "50%", background: "var(--color-surface-alt)" }} />
      )
    ),
    [data, total, colors, onSegmentClick, segments],
  );

  return (
    <div className="card stack" style={{ alignItems: "center" }}>
      <div className="text-muted">{title}</div>
      <div
        style={{ width: 120, height: 120, position: "relative" }}
        // Which slice is under the pointer comes from geometry (`sliceAtPoint`), and the box is cleared when the pointer is
        // off the ring or the chart, so it can never outlive the pointer.
        onMouseMove={(e) => {
          const box = e.currentTarget.getBoundingClientRect();
          const index = sliceAtPoint(
            e.clientX - (box.left + box.width / 2), e.clientY - (box.top + box.height / 2), data.map((d) => d.value),
          );
          setHover(index < 0 ? null : { index, x: e.clientX, y: e.clientY });
        }}
        onMouseLeave={() => setHover(null)}
      >
        {ring}
        <div
          style={{
            position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center",
            fontWeight: 700, pointerEvents: "none",
          }}
        >
          {total}
        </div>
      </div>
      {hover && total > 0 && createPortal(
        <SliceTooltip
          x={hover.x} y={hover.y} label={data[hover.index].label} value={data[hover.index].value} total={total}
          members={rows.filter((r) => r.segment === hover.index)}
        />,
        document.body,
      )}
      <div className="stack" style={{ gap: "0.2rem", width: "100%" }}>
        {rows.slice(0, legendLimit).map((row) => (
          <LegendItem key={row.label} row={row} color={colorOf(row.segment)} />
        ))}
        {rows.length > legendLimit && (
          <>
            <button
              ref={moreRef}
              type="button"
              aria-haspopup="dialog"
              aria-expanded={moreOpen}
              onClick={() => setMoreOpen((open) => !open)}
              style={{
                alignSelf: "flex-start", background: "none", border: "none", padding: 0, cursor: "pointer",
                color: "var(--color-primary)", textDecoration: "underline", font: "inherit", fontSize: "0.85rem",
              }}
            >
              +{rows.length - legendLimit} more
            </button>
            {moreOpen && (
              <Popover anchorRef={moreRef} onClose={() => setMoreOpen(false)} title={title} fit>
                <div className="stack" style={{ gap: "0.3rem" }}>
                  {rows.map((row) => (
                    <LegendItem
                      key={row.label}
                      row={row.onClick ? { ...row, onClick: () => { setMoreOpen(false); row.onClick?.(); } } : row}
                      color={colorOf(row.segment)}
                    />
                  ))}
                </div>
              </Popover>
            )}
          </>
        )}
      </div>
    </div>
  );
}
