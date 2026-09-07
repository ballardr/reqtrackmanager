/**
 * Module: modules/compliance/OutstandingPanel
 *
 * The Project Compliance View's "what remains outstanding" summary (§21's
 * own explicit goal — "The view should make it easy for a Project Manager
 * or Compliance Officer to determine what remains outstanding") — gathers
 * the three cross-assignment, read-only drillable listings §20/§21 call
 * for as their own lists, not just counts: Non-Compliant requirements
 * (§20/§21), requirements Pending Approval (§12), and scheduled reviews
 * currently due/overdue (§17/§21) across every one of this project's
 * active standard assignments, all in one place rather than requiring each
 * assignment to be opened in turn.
 *
 * Read-only by design — acting on a row (assessing, approving, completing
 * a review) happens in `ApplicabilityTree`/`ReviewsPanel` via the
 * Standards tab, not duplicated here.
 */
import { useEffect, useState } from "react";

import { COMPLIANCE_REVIEW_SCHEDULE_STATE_LABEL, COMPLIANCE_STATUS_LABEL } from "../../api/types";
import { Spinner } from "../../components/Spinner";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import * as complianceApi from "./api";
import type { ComplianceReview, NonCompliantRequirement, PendingApproval } from "./types";

export function OutstandingPanel({ projectId }: { projectId: string }) {
  const { showToast } = useToast();
  const [nonCompliant, setNonCompliant] = useState<NonCompliantRequirement[] | null>(null);
  const [pending, setPending] = useState<PendingApproval[] | null>(null);
  const [reviewsDue, setReviewsDue] = useState<ComplianceReview[] | null>(null);

  useEffect(() => {
    Promise.all([
      complianceApi.listNonCompliantRequirements(projectId),
      complianceApi.listPendingApprovals(projectId),
      complianceApi.listReviewsDue(projectId),
    ])
      .then(([nc, pa, rd]) => {
        setNonCompliant(nc);
        setPending(pa);
        setReviewsDue(rd);
      })
      .catch((err) => showToast(toErrorMessage(err, "Could not load outstanding items."), "error"));
  }, [projectId, showToast]);

  if (nonCompliant === null || pending === null || reviewsDue === null) return <Spinner />;

  return (
    <div className="stack">
      <section className="card stack">
        <h3 style={{ margin: 0 }}>Non-compliant requirements ({nonCompliant.length})</h3>
        {nonCompliant.length === 0 ? (
          <p className="text-muted" style={{ margin: 0 }}>None.</p>
        ) : (
          <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
            {nonCompliant.map((row) => (
              <li key={row.project_compliance_requirement_id} style={{ borderBottom: "1px solid var(--color-border)", padding: "0.3rem 0" }}>
                <strong>{row.standard_reference}</strong> — {row.requirement_reference ? `${row.requirement_reference} — ` : ""}{row.requirement_name}
                {row.justification && <span className="text-muted"> — {row.justification}</span>}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="card stack">
        <h3 style={{ margin: 0 }}>Pending approval ({pending.length})</h3>
        {pending.length === 0 ? (
          <p className="text-muted" style={{ margin: 0 }}>None.</p>
        ) : (
          <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
            {pending.map((row) => (
              <li key={row.project_compliance_requirement_id} style={{ borderBottom: "1px solid var(--color-border)", padding: "0.3rem 0" }}>
                <strong>{row.standard_reference}</strong> — {row.requirement_reference ? `${row.requirement_reference} — ` : ""}{row.requirement_name}
                <span className="text-muted"> ({COMPLIANCE_STATUS_LABEL[row.compliance_status]})</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="card stack">
        <h3 style={{ margin: 0 }}>Reviews due or overdue ({reviewsDue.length})</h3>
        {reviewsDue.length === 0 ? (
          <p className="text-muted" style={{ margin: 0 }}>None.</p>
        ) : (
          <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
            {reviewsDue.map((review) => (
              <li key={review.id} style={{ borderBottom: "1px solid var(--color-border)", padding: "0.3rem 0" }}>
                {review.frequency_label} — due {review.next_due_date}
                {review.schedule_state && <span className="badge" style={{ marginLeft: "0.5rem" }}>{COMPLIANCE_REVIEW_SCHEDULE_STATE_LABEL[review.schedule_state]}</span>}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
