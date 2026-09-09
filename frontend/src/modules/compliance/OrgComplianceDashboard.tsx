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
 * The four headline numbers (active standards / projects subject to
 * compliance / overall compliance / non-compliant projects) are computed
 * via `orgComplianceSummary.ts::computeOrgComplianceHeadline`, shared with
 * `ComplianceOrgOverviewTiles.tsx`'s `OrgOverviewPage.tsx` header tiles
 * (Phase 25b) so both surfaces report the exact same numbers from the same
 * rows rather than two independent copies of the same computation — and the
 * `statusRows` those numbers are computed from come from the shared
 * `useOrgComplianceStatus` hook rather than this component's own fetch, so
 * the two surfaces (which mount at the same time, since this Dashboard
 * group is `OrgOverviewPage.tsx`'s default `orgOverviewSections` entry)
 * share one request instead of firing the identical one twice.
 *
 * The "Download PDF report"/"Download CSV report" actions (Phase 15, §29)
 * hit `GET .../orgs/{id}/modules/compliance/reports/{pdf,csv}` directly via
 * `api.getForBlob` + `downloadBlob` — see `ProjectCompliancePage.tsx`'s own
 * identical Phase 15 note for why this reuses `pages/ReportsPage.tsx`'s
 * established fetch-a-blob-and-save-it idiom rather than a new one. Phase
 * 25b moved them from two permanently-visible adjacent buttons (Principle
 * 11's "two blocks competing for the same job," the exact shape the CSV
 * wizard's own Export/Download-template pair already had) behind one
 * "Export" `Popover` trigger, mirroring `CsvImportWizard.tsx`'s identical
 * fix.
 *
 * The nine `StatCard`s below (four headline + five detail) render as one
 * single `.grid.grid-metrics` grid (Phase 25c) rather than three separately
 * `flex-wrap`-ped rows of uneven size (4/5) — a consistent column count
 * across breakpoints regardless of how many cards happen to fit a given
 * row width.
 */
import { Download } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../../api/client";
import { activityActionLabel } from "../../api/types";
import { Popover } from "../../components/Popover";
import { Spinner } from "../../components/Spinner";
import { StatCard } from "../../components/StatCard";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { downloadBlob } from "../../utils/download";
import * as complianceApi from "./api";
import { computeOrgComplianceHeadline, distinctProjects } from "./orgComplianceSummary";
import {
  COMPLIANCE_REVIEW_SCHEDULE_STATE_LABEL,
  type ComplianceRecentActivity,
  type OrgExpiringEvidence,
  type OrgNonCompliantRequirement,
  type OrgPendingApproval,
  type OrgReviewDue,
  type OutstandingRequiredAction,
} from "./types";
import { useOrgComplianceStatus } from "./useOrgComplianceStatus";

interface DashboardData {
  nonCompliant: OrgNonCompliantRequirement[];
  pending: OrgPendingApproval[];
  outstandingActions: OutstandingRequiredAction[];
  expiringEvidence: OrgExpiringEvidence[];
  reviewsDue: OrgReviewDue[];
  reviewsIncludingUpcoming: OrgReviewDue[];
  recentActivity: ComplianceRecentActivity[];
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

export function OrgComplianceDashboard({ orgId }: { orgId: string }) {
  const { showToast } = useToast();
  const statusRows = useOrgComplianceStatus(orgId);
  const [data, setData] = useState<DashboardData | null>(null);
  const [downloading, setDownloading] = useState<"pdf" | "csv" | null>(null);
  const [exportMenuOpen, setExportMenuOpen] = useState(false);
  const exportTriggerRef = useRef<HTMLButtonElement>(null);

  async function downloadReport(kind: "pdf" | "csv") {
    setExportMenuOpen(false);
    setDownloading(kind);
    try {
      const blob = await api.getForBlob(`/api/v1/orgs/${orgId}/modules/compliance/reports/${kind}`);
      downloadBlob(blob, `organisation-compliance-report.${kind}`);
    } catch (err) {
      showToast(toErrorMessage(err, "Could not generate the organisation compliance report."), "error");
    } finally {
      setDownloading(null);
    }
  }

  useEffect(() => {
    Promise.all([
      complianceApi.listOrgNonCompliantRequirements(orgId),
      complianceApi.listOrgPendingApprovals(orgId),
      complianceApi.listOrgOutstandingRequiredActions(orgId),
      complianceApi.listOrgExpiringEvidence(orgId),
      complianceApi.listOrgReviewsDue(orgId, false),
      complianceApi.listOrgReviewsDue(orgId, true),
      complianceApi.listOrgRecentActivity(orgId, 10),
    ])
      .then(([nonCompliant, pending, outstandingActions, expiringEvidence, reviewsDue, reviewsIncludingUpcoming, recentActivity]) => {
        setData({ nonCompliant, pending, outstandingActions, expiringEvidence, reviewsDue, reviewsIncludingUpcoming, recentActivity });
      })
      .catch((err) => showToast(toErrorMessage(err, "Could not load the compliance dashboard."), "error"));
  }, [orgId, showToast]);

  if (data === null || statusRows === null) return <Spinner />;

  const { nonCompliant, pending, outstandingActions, expiringEvidence, reviewsDue, reviewsIncludingUpcoming, recentActivity } = data;

  const { activeStandardCount, overallCompliancePercentage, nonCompliantProjects } = computeOrgComplianceHeadline(statusRows);
  const projectsSubjectToCompliance = distinctProjects(statusRows);
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
      <div className="row" style={{ justifyContent: "flex-end" }}>
        <button
          ref={exportTriggerRef}
          type="button" className="btn"
          onClick={() => setExportMenuOpen((v) => !v)}
        >
          <Download size={16} /> {downloading ? "Exporting…" : "Export"}
        </button>
        {exportMenuOpen && (
          <Popover anchorRef={exportTriggerRef} title="Export" onClose={() => setExportMenuOpen(false)}>
            <div className="stack" style={{ gap: "0.25rem", minWidth: 180 }}>
              <button
                type="button" className="btn" style={{ justifyContent: "flex-start" }} disabled={downloading !== null}
                onClick={() => downloadReport("pdf")}
              >
                <Download size={14} /> {downloading === "pdf" ? "…" : "Download PDF report"}
              </button>
              <button
                type="button" className="btn" style={{ justifyContent: "flex-start" }} disabled={downloading !== null}
                onClick={() => downloadReport("csv")}
              >
                <Download size={14} /> {downloading === "csv" ? "…" : "Download CSV report"}
              </button>
            </div>
          </Popover>
        )}
      </div>
      <div className="grid grid-metrics">
        <StatCard label="Active compliance standards" value={activeStandardCount} />
        <StatCard label="Projects subject to compliance" value={projectsSubjectToCompliance.length}>
          <ProjectList projects={projectsSubjectToCompliance} />
        </StatCard>
        <StatCard label="Overall compliance" value={Math.round(overallCompliancePercentage)}>
          <span className="text-muted">%, weighted by applicable requirements</span>
        </StatCard>
        <StatCard label="Non-compliant projects" value={nonCompliantProjects.length}>
          <ProjectList projects={nonCompliantProjects} />
        </StatCard>
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
                  {event.requirement_name} — {activityActionLabel(event.action)}
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
