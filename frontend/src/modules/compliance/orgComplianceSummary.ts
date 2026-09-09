/**
 * Module: modules/compliance/orgComplianceSummary
 *
 * Shared "org-wide headline compliance numbers" computation — extracted
 * (compliance-module-plan.md Phase 25b) so `OrgComplianceDashboard.tsx`'s
 * own Dashboard-tab stats and `ComplianceOrgOverviewTiles.tsx`'s new
 * `OrgOverviewPage.tsx` header tiles compute the exact same numbers from
 * the exact same `listOrgProjectComplianceStatus` rows, rather than two
 * copies of the same weighted-average/grouping logic drifting apart.
 */
import type { ProjectComplianceStatus } from "./types";

export interface OrgComplianceHeadline {
  activeStandardCount: number;
  /** 0-100, weighted by each row's own `applicable_count` — a standard
   * assigned to more projects (or with more applicable requirements) counts
   * proportionally more than one assigned to a single small project. */
  overallCompliancePercentage: number;
  nonCompliantProjects: { id: string; name: string }[];
}

export function distinctProjects(entries: { project_id: string; project_name: string }[]): { id: string; name: string }[] {
  const map = new Map<string, string>();
  for (const e of entries) map.set(e.project_id, e.project_name);
  return [...map.entries()].map(([id, name]) => ({ id, name }));
}

export function computeOrgComplianceHeadline(statusRows: ProjectComplianceStatus[]): OrgComplianceHeadline {
  const activeStandardCount = new Set(statusRows.map((r) => r.standard_id)).size;
  const totalApplicable = statusRows.reduce((sum, r) => sum + r.applicable_count, 0);
  const weightedCompliantWeight = statusRows.reduce((sum, r) => sum + r.applicable_count * (r.compliance_percentage / 100), 0);
  const overallCompliancePercentage = totalApplicable > 0 ? (weightedCompliantWeight / totalApplicable) * 100 : 0;
  const nonCompliantProjects = distinctProjects(
    statusRows.filter((r) => r.overall_compliance_state === "non_compliant").map((r) => ({ project_id: r.project_id, project_name: r.project_name }))
  );
  return { activeStandardCount, overallCompliancePercentage, nonCompliantProjects };
}
