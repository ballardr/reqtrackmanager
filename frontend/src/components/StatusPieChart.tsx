import { Cell, Pie, PieChart, ResponsiveContainer } from "recharts";

const PALETTE = [
  "var(--color-primary)",
  "var(--color-accent)",
  "var(--color-warning)",
  "var(--color-danger)",
  "var(--color-text-muted)",
];

/**
 * Themed donut/pie chart for dashboard summaries (e.g. requirements by
 * status, change requests by outcome), built on Recharts rather than a
 * bespoke CSS conic-gradient — chosen (UX review) so future custom-dashboard
 * widgets have a real charting library's composable API to build on instead
 * of a one-off. Colours come from the same theme custom properties the
 * previous hand-rolled `DonutChart` used, so it still matches light/dark.
 */
export function StatusPieChart({
  segments, title, onSegmentClick,
}: {
  segments: Array<[string, number]>;
  title: string;
  onSegmentClick?: (label: string, index: number) => void;
}) {
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
                  <Cell key={entry.label} fill={PALETTE[idx % PALETTE.length]} />
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
        {segments.map(([label, value], idx) => {
          const row = (
            <span className="row" style={{ gap: "0.4rem" }}>
              <span
                style={{
                  width: 10, height: 10, borderRadius: "50%",
                  background: PALETTE[idx % PALETTE.length], display: "inline-block",
                }}
              />
              {label}
            </span>
          );
          return (
            <div key={label} className="row" style={{ justifyContent: "space-between", fontSize: "0.85rem" }}>
              {onSegmentClick ? (
                <button
                  type="button"
                  onClick={() => onSegmentClick(label, idx)}
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
