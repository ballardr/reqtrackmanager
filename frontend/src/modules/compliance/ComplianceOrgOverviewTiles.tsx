/**
 * Module: modules/compliance/ComplianceOrgOverviewTiles
 *
 * This module's contribution to `pages/OrgOverviewPage.tsx`'s always-
 * visible stats header (compliance-module-plan.md Phase 25b) — three
 * headline gauges (overall compliance percentage, active standards count,
 * non-compliant projects count) computed from the same
 * `listOrgProjectComplianceStatus` rows `OrgComplianceDashboard.tsx`'s own
 * Dashboard tab uses, via the shared `orgComplianceSummary.ts` helper, so
 * the two surfaces never report different numbers for the same underlying
 * data.
 *
 * Registered as an `orgOverviewTiles` entry in `./module.ts`;
 * `OrgOverviewPage.tsx` renders whatever this returns without knowing
 * anything about compliance. Renders nothing at all while loading or once
 * loaded with zero project-compliance assignments — an org with no
 * compliance activity at all gets no tiles, the same "don't show an empty/
 * zero-value tile nobody asked to see" rule
 * `ComplianceProjectOverviewTiles.tsx` already follows.
 *
 * Fetches via the shared `useOrgComplianceStatus` hook, not its own
 * `useEffect`/`listOrgProjectComplianceStatus` call — `OrgOverviewPage.tsx`
 * renders the Dashboard `orgOverviewSections` group by default
 * (`sections[0]`) right alongside this header, so `OrgComplianceDashboard
 * .tsx` mounts at the same time and needs the exact same rows; the shared
 * hook's module-level cache means the two components' first renders share
 * one request instead of firing it twice.
 *
 * Labelled distinctly from `OrgComplianceDashboard.tsx`'s own same-numbers
 * `StatCard`s ("Overall org compliance"/"Compliance standards in
 * use"/"Projects out of compliance" here vs. "Overall compliance"/"Active
 * compliance standards"/"Non-compliant projects" there) even though both
 * read from the same `computeOrgComplianceHeadline` output — both render at
 * once (see above), so identical label text in both places would make
 * `getByText`/accessible-name lookups ambiguous on every page load, not
 * just an edge case.
 */
import { StatCard } from "../../components/StatCard";
import { computeOrgComplianceHeadline } from "./orgComplianceSummary";
import { useOrgComplianceStatus } from "./useOrgComplianceStatus";

export function ComplianceOrgOverviewTiles({ orgId }: { orgId: string }) {
  const statusRows = useOrgComplianceStatus(orgId);

  if (!statusRows || statusRows.length === 0) return null;

  const { activeStandardCount, overallCompliancePercentage, nonCompliantProjects } = computeOrgComplianceHeadline(statusRows);

  return (
    <>
      <StatCard label="Overall org compliance" value={`${Math.round(overallCompliancePercentage)}%`} />
      <StatCard label="Compliance standards in use" value={activeStandardCount} />
      <StatCard label="Projects out of compliance" value={nonCompliantProjects.length} />
    </>
  );
}
