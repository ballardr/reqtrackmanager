/**
 * Module: modules/compliance/OrgComplianceOutstandingPanel
 *
 * The org-wide counterpart to `OutstandingPanel.tsx` (Phase 13's per-
 * project "what remains outstanding" summary) — §22's own explicit list of
 * things a Compliance Manager must be able to identify across every
 * project at once: Non-Compliant requirements, outstanding Required
 * Actions, expired/expiring evidence, overdue compliance reviews, and
 * assessments awaiting approval. Each row is tagged with the project it
 * belongs to (every Phase 14 org-wide schema carries `project_id`/
 * `project_name` — see `types.ts`'s own Phase 14 section) and links back
 * to that project's Compliance page for further drill-down, the same
 * reuse-the-existing-page approach `OrgComplianceStandardsPanel` uses.
 *
 * Read-only by design, mirroring `OutstandingPanel`'s own posture — acting
 * on a row happens on the linked project's own Compliance page.
 */
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { Spinner } from "../../components/Spinner";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import * as complianceApi from "./api";
import {
  COMPLIANCE_EVIDENCE_VALIDITY_STATE_LABEL,
  COMPLIANCE_REVIEW_SCHEDULE_STATE_LABEL,
  COMPLIANCE_STATUS_LABEL,
  type OrgExpiringEvidence,
  type OrgNonCompliantRequirement,
  type OrgPendingApproval,
  type OrgReviewDue,
  type OutstandingRequiredAction,
} from "./types";

function ProjectLink({ projectId, projectName }: { projectId: string; projectName: string }) {
  return <Link to={`/projects/${projectId}/modules/compliance`}>{projectName}</Link>;
}

export function OrgComplianceOutstandingPanel({ orgId }: { orgId: string }) {
  const { showToast } = useToast();
  const [nonCompliant, setNonCompliant] = useState<OrgNonCompliantRequirement[] | null>(null);
  const [pending, setPending] = useState<OrgPendingApproval[] | null>(null);
  const [outstandingActions, setOutstandingActions] = useState<OutstandingRequiredAction[] | null>(null);
  const [expiringEvidence, setExpiringEvidence] = useState<OrgExpiringEvidence[] | null>(null);
  const [reviewsDue, setReviewsDue] = useState<OrgReviewDue[] | null>(null);

  useEffect(() => {
    Promise.all([
      complianceApi.listOrgNonCompliantRequirements(orgId),
      complianceApi.listOrgPendingApprovals(orgId),
      complianceApi.listOrgOutstandingRequiredActions(orgId),
      complianceApi.listOrgExpiringEvidence(orgId),
      complianceApi.listOrgReviewsDue(orgId),
    ])
      .then(([nc, pa, oa, ee, rd]) => {
        setNonCompliant(nc);
        setPending(pa);
        setOutstandingActions(oa);
        setExpiringEvidence(ee);
        setReviewsDue(rd);
      })
      .catch((err) => showToast(toErrorMessage(err, "Could not load organisation outstanding items."), "error"));
  }, [orgId, showToast]);

  if (nonCompliant === null || pending === null || outstandingActions === null || expiringEvidence === null || reviewsDue === null) {
    return <Spinner />;
  }

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
                <ProjectLink projectId={row.project_id} projectName={row.project_name} /> — <strong>{row.standard_reference}</strong> — {row.requirement_reference ? `${row.requirement_reference} — ` : ""}{row.requirement_name}
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
                <ProjectLink projectId={row.project_id} projectName={row.project_name} /> — <strong>{row.standard_reference}</strong> — {row.requirement_reference ? `${row.requirement_reference} — ` : ""}{row.requirement_name}
                <span className="text-muted"> ({COMPLIANCE_STATUS_LABEL[row.compliance_status]})</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="card stack">
        <h3 style={{ margin: 0 }}>Outstanding required actions ({outstandingActions.length})</h3>
        {outstandingActions.length === 0 ? (
          <p className="text-muted" style={{ margin: 0 }}>None.</p>
        ) : (
          <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
            {outstandingActions.map((row) => (
              <li key={row.required_action_assessment_id} style={{ borderBottom: "1px solid var(--color-border)", padding: "0.3rem 0" }}>
                <ProjectLink projectId={row.project_id} projectName={row.project_name} /> — <strong>{row.standard_reference}</strong> — {row.requirement_reference ? `${row.requirement_reference} — ` : ""}{row.requirement_name} — {row.required_action_name}
                {row.due_date && <span className="text-muted"> (due {row.due_date})</span>}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="card stack">
        <h3 style={{ margin: 0 }}>Evidence expired or expiring ({expiringEvidence.length})</h3>
        {expiringEvidence.length === 0 ? (
          <p className="text-muted" style={{ margin: 0 }}>None.</p>
        ) : (
          <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
            {expiringEvidence.map((row) => (
              <li key={row.id} style={{ borderBottom: "1px solid var(--color-border)", padding: "0.3rem 0" }}>
                <ProjectLink projectId={row.project_id} projectName={row.project_name} /> — {row.title}
                <span className="badge" style={{ marginLeft: "0.5rem" }}>{COMPLIANCE_EVIDENCE_VALIDITY_STATE_LABEL[row.validity_state]}</span>
                {row.expiry_date && <span className="text-muted"> (expires {row.expiry_date})</span>}
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
            {reviewsDue.map((row) => (
              <li key={`${row.project_id}-${row.review.id}`} style={{ borderBottom: "1px solid var(--color-border)", padding: "0.3rem 0" }}>
                <ProjectLink projectId={row.project_id} projectName={row.project_name} /> — {row.review.frequency_label} — due {row.review.next_due_date}
                {row.review.schedule_state && <span className="badge" style={{ marginLeft: "0.5rem" }}>{COMPLIANCE_REVIEW_SCHEDULE_STATE_LABEL[row.review.schedule_state]}</span>}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
