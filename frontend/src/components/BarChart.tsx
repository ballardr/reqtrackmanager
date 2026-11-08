/**
 * Module: components/BarChart
 *
 * A horizontal bar chart for a breakdown: one row per item with its label, a bar scaled to the largest value
 * and the value. Rows can link to the list they summarise. The bar alternative to `StatusPieChart` for the
 * project overview's chart widget.
 *
 * Design decisions:
 * - Plain CSS bars (no charting dependency), like the stage-progress bars; each bar carries its value as text,
 *   so the figure never depends on the bar's length.
 */
import { Link } from "react-router-dom";

export interface BarRow {
  key: string;
  label: string;
  value: number;
  /** Text shown in place of the bare value (a percentage); the value still scales the bar. */
  valueText?: string;
  /** Where the row links; omit for a row with no list to open. */
  to?: string | null;
}

/**
 * @param rows The items, in the order shown.
 * @param title The chart's caption.
 * @param ariaLabel Builds a row's accessible name from its label and value text.
 */
export function BarChart({ rows, title, ariaLabel }: { rows: BarRow[]; title: string; ariaLabel: (label: string, value: string) => string }) {
  const largest = Math.max(1, ...rows.map((r) => r.value));
  return (
    <div className="card stack">
      <div className="text-muted">{title}</div>
      {rows.map((row) => {
        const text = row.valueText ?? String(row.value);
        const body = (
          <div className="stack" style={{ gap: "0.2rem" }}>
            <div className="row" style={{ justifyContent: "space-between", fontSize: "0.85rem" }}>
              <span>{row.label}</span>
              <span className="text-muted">{text}</span>
            </div>
            <div
              role="img" aria-label={ariaLabel(row.label, text)}
              style={{ background: "var(--color-surface-alt)", borderRadius: "var(--radius-sm)", height: 8, overflow: "hidden" }}
            >
              <div style={{ width: `${(row.value / largest) * 100}%`, background: "var(--color-primary)", height: "100%" }} />
            </div>
          </div>
        );
        return row.to ? (
          <Link key={row.key} to={row.to} style={{ textDecoration: "none", color: "inherit" }}>{body}</Link>
        ) : (
          <div key={row.key}>{body}</div>
        );
      })}
    </div>
  );
}
