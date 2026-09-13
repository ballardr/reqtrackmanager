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
 *
 * Phase 36 added a "Category"/"Evidence status" filter pair (reading an
 * initial value off `?category=`/`?validity=`) so `OrgComplianceDashboard.tsx`'s
 * top-grid tiles ("Projects with outstanding actions," "...expired
 * evidence," "...evidence approaching expiry," "...overdue compliance
 * reviews," "Assessments awaiting approval") can link straight to the one
 * relevant section here, rather than to an unfiltered page showing all five
 * at once — the tile counts one specific condition, so its destination
 * should show only that condition, not require the user to find it among
 * everything else. `category` picks which of the five sections below
 * renders at all; `validity` further narrows the Evidence section alone,
 * since that's the one section covering two distinct tile conditions
 * (expired vs. expiring soon) sharing one underlying list.
 */
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { FilterField, FilterPanel } from "../../components/FilterPanel";
import { Spinner } from "../../components/Spinner";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import * as complianceApi from "./api";
import {
  COMPLIANCE_EVIDENCE_VALIDITY_STATE_LABEL,
  COMPLIANCE_REVIEW_SCHEDULE_STATE_LABEL,
  COMPLIANCE_STATUS_LABEL,
  type ComplianceEvidenceValidityState,
  type OrgExpiringEvidence,
  type OrgNonCompliantRequirement,
  type OrgPendingApproval,
  type OrgReviewDue,
  type OutstandingRequiredAction,
} from "./types";

type Category = "" | "non_compliant" | "pending" | "actions" | "evidence" | "reviews";
type EvidenceValidityFilter = "" | Extract<ComplianceEvidenceValidityState, "expired" | "expiring_soon">;

const CATEGORIES: Category[] = ["non_compliant", "pending", "actions", "evidence", "reviews"];
const EVIDENCE_VALIDITY_FILTERS: EvidenceValidityFilter[] = ["expired", "expiring_soon"];

function ProjectLink({ projectId, projectName }: { projectId: string; projectName: string }) {
  return <Link to={`/projects/${projectId}/modules/compliance`}>{projectName}</Link>;
}

export function OrgComplianceOutstandingPanel({ orgId }: { orgId: string }) {
  const { showToast } = useToast();
  const [searchParams] = useSearchParams();
  const [category, setCategory] = useState<Category>(() => {
    const initial = searchParams.get("category");
    return initial && CATEGORIES.includes(initial as Category) ? (initial as Category) : "";
  });
  const [evidenceValidity, setEvidenceValidity] = useState<EvidenceValidityFilter>(() => {
    const initial = searchParams.get("validity");
    return initial && EVIDENCE_VALIDITY_FILTERS.includes(initial as EvidenceValidityFilter) ? (initial as EvidenceValidityFilter) : "";
  });
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

  const filteredEvidence = expiringEvidence.filter((e) => !evidenceValidity || e.validity_state === evidenceValidity);
  const evidenceHeading =
    evidenceValidity === "expired"
      ? "Evidence expired"
      : evidenceValidity === "expiring_soon"
        ? "Evidence expiring soon"
        : "Evidence expired or expiring";

  return (
    <div className="stack">
      <FilterPanel sectionKey="orgCompliance.outstanding" layout="top">
        <FilterField label="Category">
          <select className="input" value={category} onChange={(e) => setCategory(e.target.value as Category)}>
            <option value="">All categories</option>
            <option value="non_compliant">Non-compliant requirements</option>
            <option value="pending">Pending approval</option>
            <option value="actions">Outstanding required actions</option>
            <option value="evidence">Evidence expired or expiring</option>
            <option value="reviews">Reviews due or overdue</option>
          </select>
        </FilterField>
        <FilterField label="Evidence status">
          <select
            className="input"
            value={evidenceValidity}
            onChange={(e) => setEvidenceValidity(e.target.value as EvidenceValidityFilter)}
            disabled={category !== "" && category !== "evidence"}
          >
            <option value="">All</option>
            <option value="expired">Expired</option>
            <option value="expiring_soon">Expiring soon</option>
          </select>
        </FilterField>
      </FilterPanel>

      {(category === "" || category === "non_compliant") && (
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
      )}

      {(category === "" || category === "pending") && (
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
      )}

      {(category === "" || category === "actions") && (
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
      )}

      {(category === "" || category === "evidence") && (
        <section className="card stack">
          <h3 style={{ margin: 0 }}>{evidenceHeading} ({filteredEvidence.length})</h3>
          {filteredEvidence.length === 0 ? (
            <p className="text-muted" style={{ margin: 0 }}>None.</p>
          ) : (
            <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
              {filteredEvidence.map((row) => (
                <li key={row.id} style={{ borderBottom: "1px solid var(--color-border)", padding: "0.3rem 0" }}>
                  <ProjectLink projectId={row.project_id} projectName={row.project_name} /> — {row.title}
                  <span className="badge" style={{ marginLeft: "0.5rem" }}>{COMPLIANCE_EVIDENCE_VALIDITY_STATE_LABEL[row.validity_state]}</span>
                  {row.expiry_date && <span className="text-muted"> (expires {row.expiry_date})</span>}
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {(category === "" || category === "reviews") && (
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
      )}
    </div>
  );
}
