import type { ReactNode } from "react";

export interface StatBarItem {
  key: string;
  label: string;
  value: string | number;
}

/**
 * A compact, table-like row of labelled numbers (compliance-module-plan.md
 * Phase 27b) — one bordered `<dl>` with a value/label pair per entry,
 * separated by dividers, rather than each stat repeating `.card`'s full
 * border/shadow/padding chrome (`StatCard`, `.grid.grid-metrics`). Built for
 * `OrgOverviewPage.tsx`'s top-level, always-visible stats header
 * specifically — a small set of numbers meant to be scanned at a glance,
 * not the grouped/paged stat blocks elsewhere in the app that keep the
 * existing `.grid.grid-metrics` convention (see docs/ux-style-guide.md).
 *
 * `items` covers this page's own known stats; `children` lets a caller
 * splice in additional pre-built entries (e.g. a module's own contributed
 * `orgOverviewTiles`, which return an arbitrary `ReactNode` the host page
 * doesn't otherwise inspect) into the same row — render them with
 * `StatBarEntry` so they pick up identical spacing/dividers.
 */
export function StatBar({ items, children }: { items?: StatBarItem[]; children?: ReactNode }) {
  return (
    <dl className="stat-bar">
      {items?.map((item) => (
        <StatBarEntry key={item.key} label={item.label} value={item.value} />
      ))}
      {children}
    </dl>
  );
}

/** One label/value pair within a `StatBar` — exported so a module
 * contributing its own headline tile (e.g.
 * `modules/compliance/ComplianceOrgOverviewTiles.tsx`) can render entries
 * that match the row's own styling exactly, rather than a module inventing
 * a second implementation of the same pair. */
export function StatBarEntry({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="stat-bar-item">
      <dt className="stat-bar-label">{label}</dt>
      <dd className="stat-bar-value">{value}</dd>
    </div>
  );
}
