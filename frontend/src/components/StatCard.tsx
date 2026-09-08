import type { ReactNode } from "react";

/**
 * One non-clickable stat card — a big number plus a label, with optional
 * `children` for a drill-down list/detail underneath (e.g. the actual
 * projects a count refers to). Extracted (compliance-module-plan.md Phase
 * 19) from `modules/compliance/OrgComplianceDashboard.tsx`'s own
 * previously-local `StatCard`, which needed a core-owned home once
 * `pages/OrgOverviewPage.tsx`'s stats header needed the identical shape —
 * a core page must never import a component from `modules/compliance/`
 * (see `docs/compliance-module-plan.md`'s "Modular Feature System
 * Boundary" section). `OrgComplianceDashboard.tsx` now imports this shared
 * version too, rather than keeping a second, duplicate implementation.
 *
 * Deliberately distinct from `MetricTile` (`components/MetricTile.tsx`):
 * that one is always a link to a filtered list view; this one is a plain
 * card, for a stat with no single obvious link target (or one that already
 * expands inline via `children`) rather than one destination page.
 */
export function StatCard({ label, value, children }: { label: string; value: string | number; children?: ReactNode }) {
  return (
    <div className="card stack" style={{ minWidth: 220 }}>
      <span className="text-muted" style={{ fontSize: "0.8rem", fontWeight: 600 }}>{label}</span>
      <span style={{ fontSize: "1.8rem", fontWeight: 700 }}>{value}</span>
      {children}
    </div>
  );
}
