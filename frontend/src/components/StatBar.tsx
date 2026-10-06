/**
 * Module: components/StatBar
 *
 * A compact, single bordered row of labelled numbers: a CSS grid of
 * equal-width columns (`repeat(auto-fit, minmax(10rem, 1fr))`) with dividers
 * drawn by the grid, never per item, so wrapping at any width yields tidy
 * columns and no stray dividers. For a page's top-level stats header
 * (`OrgOverviewPage.tsx`) or a report's handful of headline figures.
 * Budget: at most 8 entries, labels of about 28 characters or fewer; anything
 * bigger or wordier is a `StatGroups` (`components/StatGroups.tsx`).
 *
 * A figure flagged `gap` is a problem to fix when non-zero: it is marked with
 * a "Needs attention" pill (never colour alone). A figure with `to` is a link
 * (the whole cell, via a stretched link on its label) to the page it counts.
 * Design decisions: no media
 * queries (the grid sizes to its container, so it also works in a narrow
 * pane); labels wrap rather than truncate, because a clipped label loses
 * information. See docs/ux-style-guide.md ("Stat blocks") and
 * `testing/statBlockGeometry.ts`, the shared assertion every stat block's
 * stories and e2e checks run.
 */
import type { ReactNode } from "react";

import { needsAttention } from "../utils/needsAttention";
import { isInteractive, type StatFigureAction } from "../utils/statFigureAction";
import { StatFigureLabel } from "./StatFigureLabel";

export interface StatBarItem {
  key: string;
  label: string;
  value: string | number;
  /** A non-zero value is a problem to fix; flagged on screen. */
  gap?: boolean;
  /** In-app path the figure opens (typically a list filtered to what it counted); the whole cell is the link. */
  to?: string;
  /** Opens something in place instead (e.g. an organisation figure's per-project list); used when there is no `to`. */
  onActivate?: () => void;
  /** Tooltip text saying where the figure leads (shown on hover and keyboard focus). */
  hint?: string;
}

/**
 * @param items Flat entries (this page's own known stats).
 * @param children Pre-built `StatBarEntry`s to splice into the same row
 *   (e.g. a module's contributed `orgOverviewTiles`).
 */
export function StatBar({ items, children }: { items?: StatBarItem[]; children?: ReactNode }) {
  return (
    <dl className="stat-bar" data-stat-block="flat">
      {items?.map((item, index) => (
        <StatBarEntry key={`${index}-${item.key}`} label={item.label} value={item.value} gap={item.gap} to={item.to} onActivate={item.onActivate} hint={item.hint} />
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
export function StatBarEntry({
  label, value, gap, to, onActivate, hint,
}: { label: string; value: string | number; gap?: boolean } & StatFigureAction) {
  const attention = needsAttention({ value, gap });
  return (
    <div className={`stat-bar-item${isInteractive({ to, onActivate }) ? " stat-linked" : ""}`} data-stat-entry>
      <dt className="stat-bar-label">
        <StatFigureLabel label={label} value={value} to={to} onActivate={onActivate} hint={hint} />
      </dt>
      <dd className="stat-bar-value">{value}</dd>
      {attention && <span className="badge badge--warning stat-bar-flag">Needs attention</span>}
    </div>
  );
}
