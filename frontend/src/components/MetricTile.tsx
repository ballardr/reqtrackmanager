import { Link } from "react-router-dom";

/**
 * One clickable metric tile in a `.grid.grid-metrics` grid: a big number or percentage plus a label, linking to the
 * list the number summarises. Shared by `ProjectOverviewPage.tsx` and by module-contributed tiles
 * (`TierAModuleDefinition.overviewWidgets`) so both render identically. `to` is omitted for a figure with no list
 * to open.
 */
export function MetricTile({ label, value, to }: { label: string; value: string | number; to?: string | null }) {
  const body = (
    <>
      <div style={{ fontSize: "1.8rem", fontWeight: 700 }}>{value}</div>
      <div className="text-muted">{label}</div>
    </>
  );
  const style = { alignItems: "center", textAlign: "center", textDecoration: "none", color: "inherit" } as const;
  // A figure no list shows exactly (a record count with a component filter) is not a link, rather than a misleading one.
  return to ? (
    <Link to={to} className="card stack" data-stat-entry style={style}>
      {body}
    </Link>
  ) : (
    <div className="card stack" data-stat-entry style={style}>
      {body}
    </div>
  );
}
