import { Link } from "react-router-dom";

/**
 * One clickable metric tile in a `.grid.grid-metrics` grid (`ProjectOverviewPage.tsx`
 * — U-P-05) — a big number/percentage plus a label, linking through to
 * whatever list view the number summarises. Extracted (module boundary
 * cleanup, 2026-09-08) from `ProjectOverviewPage.tsx`'s own inline `.map`
 * over its built-in tiles so a module contributing its own tiles
 * (`TierAModuleDefinition.projectOverviewTiles`, e.g. Compliance's
 * per-standard status tiles) renders pixel-identical ones without
 * duplicating the markup/style in a second place.
 */
export function MetricTile({ label, value, to }: { label: string; value: string | number; to: string }) {
  return (
    <Link
      to={to}
      className="card stack"
      style={{ alignItems: "center", textAlign: "center", textDecoration: "none", color: "inherit" }}
    >
      <div style={{ fontSize: "1.8rem", fontWeight: 700 }}>{value}</div>
      <div className="text-muted">{label}</div>
    </Link>
  );
}
