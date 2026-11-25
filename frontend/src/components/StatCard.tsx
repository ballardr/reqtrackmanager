import type { ReactNode } from "react";

/**
 * One non-clickable stat card: a big number plus a label, with optional `children` for a drill-down list or detail
 * underneath (e.g. the projects a count refers to). It lives in core because `pages/OrgOverviewPage.tsx`'s stats header
 * and `modules/compliance/OrgComplianceWidgets.tsx` both use it, and a core page must never import from
 * `modules/compliance/` ("Modular Feature System Boundary").
 *
 * Distinct from `MetricTile` (`components/MetricTile.tsx`), which is always a link to a filtered list view; this is a
 * plain card for a stat with no single link target (or one that expands inline via `children`).
 *
 * Renders value-above-label, centred, the same order and alignment as `MetricTile`, because the two are used
 * interchangeably in the same `.grid.grid-metrics` row and a mismatched pair reads as visually broken.
 */
export function StatCard({ label, value, children }: { label: string; value: string | number; children?: ReactNode }) {
  return (
    <div className="card stack" style={{ alignItems: "center", textAlign: "center" }} data-stat-entry>
      <span style={{ fontSize: "1.8rem", fontWeight: 700 }}>{value}</span>
      <span className="text-muted">{label}</span>
      {children}
    </div>
  );
}
