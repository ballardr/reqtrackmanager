import { Cell, Pie, PieChart, ResponsiveContainer } from "recharts";

/** The default segment colours, in order; a chart with more segments than colours repeats them (pass `colors` to avoid that). */
const PALETTE = [
  "var(--color-primary)",
  "var(--color-accent)",
  "var(--color-warning)",
  "var(--color-danger)",
  "var(--color-text-muted)",
];

/** One legend row: an item, its value, the slice whose colour it wears and an optional click action. */
export interface LegendRow {
  label: string;
  value: number;
  segment: number;
  onClick?: () => void;
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
 * Props:
 * - `segments`: `[label, value]` per slice.
 * - `title`: the caption above the ring.
 * - `onSegmentClick`: fired for a slice or a default legend row.
 * - `colors`: per-slice colours replacing the default palette.
 * - `legend`: custom legend rows; `onClick` makes a row a button.
 */
export function StatusPieChart({
  segments, title, onSegmentClick, colors = PALETTE, legend,
}: {
  segments: Array<[string, number]>;
  title: string;
  onSegmentClick?: (label: string, index: number) => void;
  colors?: string[];
  legend?: LegendRow[];
}) {
  const colorOf = (index: number) => colors[index % colors.length];
  const rows: LegendRow[] = legend ?? segments.map(([label, value], idx) => ({
    label, value, segment: idx, onClick: onSegmentClick ? () => onSegmentClick(label, idx) : undefined,
  }));
  const total = segments.reduce((sum, [, v]) => sum + v, 0);
  const data = segments.map(([label, value]) => ({ label, value }));
  const clickable = Boolean(onSegmentClick);

  return (
    <div className="card stack" style={{ alignItems: "center" }}>
      <div className="text-muted">{title}</div>
      <div style={{ width: 120, height: 120, position: "relative" }}>
        {total > 0 ? (
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
                style={clickable ? { cursor: "pointer" } : undefined}
              >
                {data.map((entry, idx) => (
                  <Cell key={entry.label} fill={colorOf(idx)} />
                ))}
              </Pie>
            </PieChart>
          </ResponsiveContainer>
        ) : (
          <div style={{ width: "100%", height: "100%", borderRadius: "50%", background: "var(--color-surface-alt)" }} />
        )}
        <div
          style={{
            position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center",
            fontWeight: 700, pointerEvents: "none",
          }}
        >
          {total}
        </div>
      </div>
      <div className="stack" style={{ gap: "0.2rem", width: "100%" }}>
        {rows.map(({ label, value, segment, onClick }) => {
          const row = (
            <span className="row" style={{ gap: "var(--space-2)" }}>
              <span
                style={{
                  width: 10, height: 10, borderRadius: "50%",
                  background: colorOf(segment), display: "inline-block",
                }}
              />
              {label}
            </span>
          );
          return (
            <div key={label} className="row" style={{ justifyContent: "space-between", fontSize: "0.85rem" }}>
              {onClick ? (
                <button
                  type="button"
                  onClick={onClick}
                  style={{ background: "none", border: "none", padding: 0, cursor: "pointer", color: "inherit", font: "inherit" }}
                >
                  {row}
                </button>
              ) : (
                row
              )}
              <span className="text-muted">{value}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
