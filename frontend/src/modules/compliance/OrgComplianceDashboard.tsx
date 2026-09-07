/**
 * Module: modules/compliance/OrgComplianceDashboard
 *
 * §23's "Compliance Dashboard" — the org-wide summary widgets, each backed
 * by real per-project/per-requirement data (never a bare, unexplained
 * number) so every widget satisfies §23's own explicit "should provide
 * drill-down capability rather than only showing aggregate numbers": each
 * count is followed by the actual list of affected projects/items it
 * counts, linking to that project's Compliance page the same way
 * `OrgComplianceStandardsPanel`/`OrgComplianceOutstandingPanel` do.
 *
 * Built entirely from the Phase 14 org-wide endpoints already fetched for
 * this panel's sibling tabs — no widget-specific backend endpoint beyond
 * `recent-activity` (which has no other consumer) was needed; "Standards
 * with the most outstanding issues" is computed client-side by tallying
 * the non-compliant/pending-approval/outstanding-action rows per standard,
 * the same client-side-aggregation-over-a-flat-listing precedent
 * `OrgComplianceStandardsPanel`/Phase 12's `buildRequirementTree` both use.
 */
import type { ReactNode } from "react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { COMPLIANCE_REVIEW_SCHEDULE_STATE_LABEL } from "../../api/types";
import { Spinner } from "../../components/Spinner";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import * as complianceApi from "./api";
import type {
  ComplianceRecentActivity,
  OrgExpiringEvidence,
  OrgNonCompliantRequirement,
  OrgPendingApproval,
  OrgReviewDue,
  OutstandingRequiredAction,
  ProjectComplianceStatus,
} from "./types";

interface DashboardData {
  statusRows: ProjectComplianceStatus[];
  nonCompliant: OrgNonCompliantRequirement[];
  pending: OrgPendingApproval[];
  outstandingActions: OutstandingRequiredAction[];
  expiringEvidence: OrgExpiringEvidence[];
  reviewsDue: OrgReviewDue[];
  reviewsIncludingUpcoming: OrgReviewDue[];
  recentActivity: ComplianceRecentActivity[];
}

function distinctProjects(entries: { project_id: string; project_name: string }[]): { id: string; name: string }[] {
  const map = new Map<string, string>();
  for (const e of entries) map.set(e.project_id, e.project_name);
  return [...map.entries()].map(([id, name]) => ({ id, name }));
}

function ProjectList({ projects }: { projects: { id: string; name: string }[] }) {
  if (projects.length === 0) return <p className="text-muted" style={{ margin: 0 }}>None.</p>;
  return (
    <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
      {projects.map((p) => (
        <li key={p.id}>
          <Link to={`/projects/${p.id}/modules/compliance`}>{p.name}</Link>
        </li>
      ))}
    </ul>
  );
}

function StatCard({ label, value, children }: { label: string; value: number; children?: ReactNode }) {
  return (
    <div className="card stack" style={{ minWidth: 220 }}>
      <span className="text-muted" style={{ fontSize: "0.8rem", fontWeight: 600 }}>{label}</span>
      <span style={{ fontSize: "1.8rem", fontWeight: 700 }}>{value}</span>
      {children}
    </div>
  );
}

export function OrgComplianceDashboard({ orgId }: { orgId: string }) {
  const { showToast } = useToast();
  const [data, setData] = useState<DashboardData | null>(null);

  useEffect(() => {
    Promise.all([
      complianceApi.listOrgProjectComplianceStatus(orgId),
      complianceApi.listOrgNonCompliantRequirements(orgId),
      complianceApi.listOrgPendingApprovals(orgId),
      complianceApi.listOrgOutstandingRequiredActions(orgId),
      complianceApi.listOrgExpiringEvidence(orgId),
      complianceApi.listOrgReviewsDue(orgId, false),
      complianceApi.listOrgReviewsDue(orgId, true),
      complianceApi.listOrgRecentActivity(orgId, 10),
    ])
      .then(([statusRows, nonCompliant, pending, outstandingActions, expiringEvidence, reviewsDue, reviewsIncludingUpcoming, recentActivity]) => {
        setData({ statusRows, nonCompliant, pending, outstandingActions, expiringEvidence, reviewsDue, reviewsIncludingUpcoming, recentActivity });
      })
      .catch((err) => showToast(toErrorMessage(err, "Could not load the compliance dashboard."), "error"));
  }, [orgId, showToast]);

  if (data === null) return <Spinner />;

  const { statusRows, nonCompliant, pending, outstandingActions, expiringEvidence, reviewsDue, reviewsIncludingUpcoming, recentActivity } = data;

  const activeStandardIds = new Set(statusRows.map((r) => r.standard_id));
  const projectsSubjectToCompliance = distinctProjects(statusRows);
  const totalApplicable = statusRows.reduce((sum, r) => sum + r.applicable_count, 0);
  const weightedCompliantWeight = statusRows.reduce((sum, r) => sum + r.applicable_count * (r.compliance_percentage / 100), 0);
  const overallCompliancePercentage = totalApplicable > 0 ? (weightedCompliantWeight / totalApplicable) * 100 : 0;
  const nonCompliantProjects = distinctProjects(
    statusRows.filter((r) => r.overall_compliance_state === "non_compliant").map((r) => ({ project_id: r.project_id, project_name: r.project_name }))
  );
  const outstandingActionProjects = distinctProjects(outstandingActions);
  const expiredEvidenceProjects = distinctProjects(expiringEvidence.filter((e) => e.validity_state === "expired"));
  const expiringSoonEvidenceProjects = distinctProjects(expiringEvidence.filter((e) => e.validity_state === "expiring_soon"));
  const overdueReviewProjects = distinctProjects(reviewsDue);
  const upcomingReviews = reviewsIncludingUpcoming
    .filter((r) => r.review.schedule_state === "upcoming")
    .sort((a, b) => a.review.next_due_date.localeCompare(b.review.next_due_date))
    .slice(0, 8);

  const issuesByStandard = new Map<string, number>();
  for (const row of [...nonCompliant, ...pending, ...outstandingActions]) {
    issuesByStandard.set(row.standard_reference, (issuesByStandard.get(row.standard_reference) ?? 0) + 1);
  }
  const standardsWithMostIssues = [...issuesByStandard.entries()].sort((a, b) => b[1] - a[1]).slice(0, 5);

  return (
    <div className="stack">
      <div className="row" style={{ gap: "1rem", flexWrap: "wrap" }}>
        <StatCard label="Active compliance standards" value={activeStandardIds.size} />
        <StatCard label="Projects subject to compliance" value={projectsSubjectToCompliance.length}>
          <ProjectList projects={projectsSubjectToCompliance} />
        </StatCard>
        <StatCard label="Overall compliance" value={Math.round(overallCompliancePercentage)}>
          <span className="text-muted">%, weighted by applicable requirements</span>
        </StatCard>
        <StatCard label="Non-compliant projects" value={nonCompliantProjects.length}>
          <ProjectList projects={nonCompliantProjects} />
        </StatCard>
      </div>

      <div className="row" style={{ gap: "1rem", flexWrap: "wrap" }}>
        <StatCard label="Projects with outstanding actions" value={outstandingActionProjects.length}>
          <ProjectList projects={outstandingActionProjects} />
        </StatCard>
        <StatCard label="Projects with expired evidence" value={expiredEvidenceProjects.length}>
          <ProjectList projects={expiredEvidenceProjects} />
        </StatCard>
        <StatCard label="Projects with evidence approaching expiry" value={expiringSoonEvidenceProjects.length}>
          <ProjectList projects={expiringSoonEvidenceProjects} />
        </StatCard>
        <StatCard label="Projects with overdue compliance reviews" value={overdueReviewProjects.length}>
          <ProjectList projects={overdueReviewProjects} />
        </StatCard>
        <StatCard label="Assessments awaiting approval" value={pending.length} />
      </div>

      <div className="row" style={{ gap: "1rem", flexWrap: "wrap", alignItems: "flex-start" }}>
        <div className="card stack" style={{ flex: "1 1 260px" }}>
          <h3 style={{ margin: 0 }}>Standards with the most outstanding issues</h3>
          {standardsWithMostIssues.length === 0 ? (
            <p className="text-muted" style={{ margin: 0 }}>None.</p>
          ) : (
            <ol style={{ margin: 0, paddingLeft: "1.2rem" }}>
              {standardsWithMostIssues.map(([reference, count]) => (
                <li key={reference}>
                  {reference} — {count} issue{count === 1 ? "" : "s"}
                </li>
              ))}
            </ol>
          )}
        </div>

        <div className="card stack" style={{ flex: "1 1 260px" }}>
          <h3 style={{ margin: 0 }}>Recently changed compliance assessments</h3>
          {recentActivity.length === 0 ? (
            <p className="text-muted" style={{ margin: 0 }}>None.</p>
          ) : (
            <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
              {recentActivity.map((event) => (
                <li key={event.id} style={{ borderBottom: "1px solid var(--color-border)", padding: "0.3rem 0" }}>
                  <Link to={`/projects/${event.project_id}/modules/compliance`}>{event.project_name}</Link>
                  {" — "}
                  {event.requirement_reference ? `${event.requirement_reference} — ` : ""}
                  {event.requirement_name} — {event.action.replace(/_/g, " ")}
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="card stack" style={{ flex: "1 1 260px" }}>
          <h3 style={{ margin: 0 }}>Upcoming compliance deadlines/reviews</h3>
          {upcomingReviews.length === 0 ? (
            <p className="text-muted" style={{ margin: 0 }}>None.</p>
          ) : (
            <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
              {upcomingReviews.map((row) => (
                <li key={`${row.project_id}-${row.review.id}`} style={{ borderBottom: "1px solid var(--color-border)", padding: "0.3rem 0" }}>
                  <Link to={`/projects/${row.project_id}/modules/compliance`}>{row.project_name}</Link>
                  {" — "}
                  {row.review.frequency_label} — due {row.review.next_due_date}
                  {row.review.schedule_state && (
                    <span className="badge" style={{ marginLeft: "0.5rem" }}>{COMPLIANCE_REVIEW_SCHEDULE_STATE_LABEL[row.review.schedule_state]}</span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
