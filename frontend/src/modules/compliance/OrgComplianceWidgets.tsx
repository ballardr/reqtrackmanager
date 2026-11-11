/**
 * Module: modules/compliance/OrgComplianceWidgets
 *
 * The organisation's compliance posture as two widgets for the organisation overview dashboards
 * (`ModuleDefinition.org_overview_widgets`, registered on `TierAModuleDefinition.orgOverviewWidgets`), which replace the
 * former separate Compliance dashboard page: a summary of the headline tiles, and an attention card of the standards
 * with the most issues, the upcoming reviews and the recently changed assessments.
 *
 * Responsibilities:
 * - Read the module's own organisation endpoints (one shared, briefly cached request set, so two widgets on one
 *   dashboard do not fetch everything twice) and compute the headline figures with `computeOrgComplianceHeadline`.
 * - Link each tile to the pre-filtered Compliance by standard or Outstanding section it summarises.
 *
 * Design decisions: figures are counted per distinct project, as the Compliance sections count them; each list is
 * bounded to five rows so a widget keeps its height; the Export of the organisation report stays on the Compliance
 * sections, where it applies to what the person is looking at.
 */
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { activityActionLabel } from "../../api/types";
import { Badge } from "../../components/Badge";
import { MetricTile } from "../../components/MetricTile";
import { Spinner } from "../../components/Spinner";
import { StatCard } from "../../components/StatCard";
import { toErrorMessage, useToast } from "../../context/ToastContext";
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

/** How long one organisation's fetched detail is reused, so widgets mounted together (or a quick return) share a request set. */
const DETAIL_TTL_MS = 10_000;
const detailCache = new Map<string, { at: number; promise: Promise<DashboardData> }>();

function loadDetail(orgId: string): Promise<DashboardData> {
  const cached = detailCache.get(orgId);
  if (cached && Date.now() - cached.at < DETAIL_TTL_MS) return cached.promise;
  const promise = Promise.all([
    complianceApi.listOrgNonCompliantRequirements(orgId),
    complianceApi.listOrgPendingApprovals(orgId),
    complianceApi.listOrgOutstandingRequiredActions(orgId),
    complianceApi.listOrgExpiringEvidence(orgId),
    complianceApi.listOrgReviewsDue(orgId, false),
    complianceApi.listOrgReviewsDue(orgId, true),
    complianceApi.listOrgRecentActivity(orgId, 5),
  ]).then(([nonCompliant, pending, outstandingActions, expiringEvidence, reviewsDue, reviewsIncludingUpcoming, recentActivity]) => ({
    nonCompliant, pending, outstandingActions, expiringEvidence, reviewsDue, reviewsIncludingUpcoming, recentActivity,
  }));
  detailCache.set(orgId, { at: Date.now(), promise });
  // A failed load is not reused: the next widget or visit asks again.
  promise.catch(() => detailCache.delete(orgId));
  return promise;
}

/** The detail rows of the organisation's compliance, or `null` while loading (a failure is shown as a toast). */
function useDetail(orgId: string): DashboardData | null {
  const { showToast } = useToast();
  const [data, setData] = useState<DashboardData | null>(null);
  useEffect(() => {
    let active = true;
    loadDetail(orgId)
      .then((loaded) => active && setData(loaded))
      .catch((err) => active && showToast(toErrorMessage(err, "Could not load the compliance figures."), "error"));
    return () => {
      active = false;
    };
  }, [orgId, showToast]);
  return data;
}

/**
 * @param orgId The organisation.
 */
export function OrgComplianceSummaryWidget({ orgId }: { orgId: string }) {
  const statusRows = useOrgComplianceStatus(orgId);
  const data = useDetail(orgId);
  if (data === null || statusRows === null) return <div className="card"><Spinner /></div>;

  const { pending, outstandingActions, expiringEvidence, reviewsDue } = data;
  const { activeStandardCount, overallCompliancePercentage, nonCompliantProjects } = computeOrgComplianceHeadline(statusRows);
  const projectsSubjectToCompliance = distinctProjects(statusRows);
  const outstandingActionProjects = distinctProjects(outstandingActions);
  const expiredEvidenceProjects = distinctProjects(expiringEvidence.filter((e) => e.validity_state === "expired"));
  const expiringSoonEvidenceProjects = distinctProjects(expiringEvidence.filter((e) => e.validity_state === "expiring_soon"));
  const overdueReviewProjects = distinctProjects(reviewsDue);

  return (
    <div className="grid grid-metrics">
        <StatCard label="Active compliance standards" value={activeStandardCount} />
        <MetricTile
          label="Projects subject to compliance"
          value={projectsSubjectToCompliance.length}
          to={`/orgs/${orgId}/overview/compliance-by-standard?groupBy=project`}
        />
        <StatCard label="Overall compliance" value={Math.round(overallCompliancePercentage)}>
          <span className="text-muted">%, weighted by applicable requirements</span>
        </StatCard>
        <MetricTile
          label="Non-compliant projects"
          value={nonCompliantProjects.length}
          to={`/orgs/${orgId}/overview/compliance-by-standard?groupBy=project&state=non_compliant`}
        />
        <MetricTile
          label="Projects with outstanding actions"
          value={outstandingActionProjects.length}
          to={`/orgs/${orgId}/overview/compliance-outstanding?category=actions`}
        />
        <MetricTile
          label="Projects with expired evidence"
          value={expiredEvidenceProjects.length}
          to={`/orgs/${orgId}/overview/compliance-outstanding?category=evidence&validity=expired`}
        />
        <MetricTile
          label="Projects with evidence approaching expiry"
          value={expiringSoonEvidenceProjects.length}
          to={`/orgs/${orgId}/overview/compliance-outstanding?category=evidence&validity=expiring_soon`}
        />
        <MetricTile
          label="Projects with overdue compliance reviews"
          value={overdueReviewProjects.length}
          to={`/orgs/${orgId}/overview/compliance-outstanding?category=reviews`}
        />
        <MetricTile
          label="Assessments awaiting approval"
          value={pending.length}
          to={`/orgs/${orgId}/overview/compliance-outstanding?category=pending`}
        />
    </div>

  );
}

/**
 * @param orgId The organisation.
 */
export function OrgComplianceAttentionWidget({ orgId }: { orgId: string }) {
  const data = useDetail(orgId);
  if (data === null) return <div className="card"><Spinner /></div>;

  const { nonCompliant, pending, outstandingActions, reviewsIncludingUpcoming, recentActivity } = data;
  const upcomingReviews = reviewsIncludingUpcoming
    .filter((r) => r.review.schedule_state === "upcoming")
    .sort((a, b) => a.review.next_due_date.localeCompare(b.review.next_due_date))
    .slice(0, 5);
  const issuesByStandard = new Map<string, number>();
  for (const row of [...nonCompliant, ...pending, ...outstandingActions]) {
    issuesByStandard.set(row.standard_reference, (issuesByStandard.get(row.standard_reference) ?? 0) + 1);
  }
  const standardsWithMostIssues = [...issuesByStandard.entries()].sort((a, b) => b[1] - a[1]).slice(0, 5);

  return (
    <div className="stack">
      <div className="row" style={{ gap: "var(--space-5)", flexWrap: "wrap", alignItems: "flex-start" }}>
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
                    <Badge className="badge-after">{COMPLIANCE_REVIEW_SCHEDULE_STATE_LABEL[row.review.schedule_state]}</Badge>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <div className="card stack">
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
    </div>
  );
}
