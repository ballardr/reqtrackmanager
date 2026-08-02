const PALETTE = [
  "var(--color-primary)",
  "var(--color-accent)",
  "var(--color-warning)",
  "var(--color-danger)",
  "var(--color-text-muted)",
];

/**
 * Lightweight donut/pie chart built from a CSS conic-gradient — avoids
 * pulling in a charting dependency for a handful of dashboard summaries
 * (mockup: Requirements Totals, Change Requests donut).
 */
export function DonutChart({ segments, title }: { segments: Array<[string, number]>; title: string }) {
  const total = segments.reduce((sum, [, v]) => sum + v, 0);

  let cursor = 0;
  const stops = segments.map(([, value], idx) => {
    const start = (cursor / (total || 1)) * 360;
    cursor += value;
    const end = (cursor / (total || 1)) * 360;
    return `${PALETTE[idx % PALETTE.length]} ${start}deg ${end}deg`;
  });

  const gradient = total > 0 ? `conic-gradient(${stops.join(", ")})` : "var(--color-surface-alt)";

  return (
    <div className="card stack" style={{ alignItems: "center" }}>
      <div className="text-muted">{title}</div>
      <div
        style={{
          width: 120,
          height: 120,
          borderRadius: "50%",
          background: gradient,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <div
          style={{
            width: 70,
            height: 70,
            borderRadius: "50%",
            background: "var(--color-surface)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontWeight: 700,
          }}
        >
          {total}
        </div>
      </div>
      <div className="stack" style={{ gap: "0.2rem", width: "100%" }}>
        {segments.map(([label, value], idx) => (
          <div key={label} className="row" style={{ justifyContent: "space-between", fontSize: "0.85rem" }}>
            <span className="row" style={{ gap: "0.4rem" }}>
              <span
                style={{
                  width: 10,
                  height: 10,
                  borderRadius: "50%",
                  background: PALETTE[idx % PALETTE.length],
                  display: "inline-block",
                }}
              />
              {label}
            </span>
            <span className="text-muted">{value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
