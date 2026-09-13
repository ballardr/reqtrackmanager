/**
 * Module: modules/compliance/OutstandingPanel
 *
 * The Project Compliance View's "what remains outstanding" summary (§21's
 * own explicit goal — "The view should make it easy for a Project Manager
 * or Compliance Officer to determine what remains outstanding") — gathers
 * the four cross-assignment, read-only drillable listings §20/§21/§22 call
 * for as their own lists, not just counts: Non-Compliant requirements
 * (§20/§21), requirements Pending Approval (§12), outstanding Required
 * Actions (§22's own explicit "identifying projects with outstanding
 * Required Actions," added in Phase 14 alongside the org-wide equivalent
 * once a flattened, cross-assignment listing existed to show here — before
 * Phase 14 only the per-requirement nested endpoint existed, nothing to
 * power this section with), and scheduled reviews currently due/overdue
 * (§17/§21) across every one of this project's active standard
 * assignments, all in one place rather than requiring each assignment to
 * be opened in turn.
 *
 * Read-only by design — acting on a row (assessing, approving, completing
 * a review, completing a required action) happens in `ApplicabilityTree`/
 * `ReviewsPanel` via the Standards tab, not duplicated here.
 *
 * Phase 40 adds Standard/Standard version/Sub-section filtering — parity
 * with the org-wide `OrgComplianceOutstandingPanel`'s own Phase 40 filters,
 * minus a Project filter (this page is already scoped to one project). A
 * project with several standards assigned would otherwise show every
 * non-compliant requirement/pending approval/outstanding action/review
 * from all of them in one flat set of four sections; see
 * `OrgComplianceOutstandingPanel.tsx`'s own Phase 40 notes for why
 * Evidence and the per-requirement Sub-section filter are scoped the way
 * they are.
 *
 * Phase 43 adds an "Export" trigger (`ReportExportButton`) scoped to this
 * panel's current Standard/Standard version/Sub-section filters —
 * `complianceApi.downloadProjectComplianceReport` passes them through as
 * query params, matching `OrgComplianceOutstandingPanel.tsx`'s identical
 * convention (minus a Project filter, since this page is already
 * project-scoped by URL).
 */
import { useEffect, useMemo, useState } from "react";

import { FilterField, FilterPanel } from "../../components/FilterPanel";
import { ReportExportButton } from "../../components/ReportExportButton";
import { Spinner } from "../../components/Spinner";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { downloadBlob } from "../../utils/download";
import * as complianceApi from "./api";
import {
  COMPLIANCE_REVIEW_SCHEDULE_STATE_LABEL,
  COMPLIANCE_STATUS_LABEL,
  type ComplianceRequirement,
  type ComplianceReview,
  type NonCompliantRequirement,
  type OutstandingRequiredAction,
  type PendingApproval,
} from "./types";

export function OutstandingPanel({ projectId, orgId }: { projectId: string; orgId: string }) {
  const { showToast } = useToast();
  const [nonCompliant, setNonCompliant] = useState<NonCompliantRequirement[] | null>(null);
  const [pending, setPending] = useState<PendingApproval[] | null>(null);
  const [outstandingActions, setOutstandingActions] = useState<OutstandingRequiredAction[] | null>(null);
  const [reviewsDue, setReviewsDue] = useState<ComplianceReview[] | null>(null);
  const [standardFilter, setStandardFilter] = useState("");
  const [versionFilter, setVersionFilter] = useState("");
  const [subSectionFilter, setSubSectionFilter] = useState("");
  const [requirementsById, setRequirementsById] = useState<Map<string, ComplianceRequirement>>(new Map());

  useEffect(() => {
    Promise.all([
      complianceApi.listNonCompliantRequirements(projectId),
      complianceApi.listPendingApprovals(projectId),
      complianceApi.listOutstandingRequiredActions(projectId),
      complianceApi.listReviewsDue(projectId),
    ])
      .then(([nc, pa, oa, rd]) => {
        setNonCompliant(nc);
        setPending(pa);
        setOutstandingActions(oa);
        setReviewsDue(rd);
      })
      .catch((err) => showToast(toErrorMessage(err, "Could not load outstanding items."), "error"));
  }, [projectId, showToast]);

  useEffect(() => {
    if (!standardFilter) {
      setRequirementsById(new Map());
      return;
    }
    let cancelled = false;
    complianceApi
      .listStandardVersions(orgId, standardFilter)
      .then((versions) => Promise.all(versions.map((v) => complianceApi.listRequirements(orgId, standardFilter, v.id))))
      .then((lists) => {
        if (cancelled) return;
        const map = new Map<string, ComplianceRequirement>();
        for (const list of lists) for (const req of list) map.set(req.id, req);
        setRequirementsById(map);
      })
      .catch((err) => showToast(toErrorMessage(err, "Could not load this standard's requirement structure."), "error"));
    return () => {
      cancelled = true;
    };
  }, [orgId, standardFilter, showToast]);

  const standards = useMemo(() => {
    const map = new Map<string, { id: string; reference: string; name: string }>();
    for (const row of nonCompliant ?? []) map.set(row.standard_id, { id: row.standard_id, reference: row.standard_reference, name: row.standard_name });
    for (const row of pending ?? []) map.set(row.standard_id, { id: row.standard_id, reference: row.standard_reference, name: row.standard_name });
    for (const row of outstandingActions ?? []) map.set(row.standard_id, { id: row.standard_id, reference: row.standard_reference, name: row.standard_name });
    for (const row of reviewsDue ?? []) {
      if (row.standard_id && row.standard_reference) {
        map.set(row.standard_id, { id: row.standard_id, reference: row.standard_reference, name: row.standard_name ?? "" });
      }
    }
    return [...map.values()].sort((a, b) => a.reference.localeCompare(b.reference));
  }, [nonCompliant, pending, outstandingActions, reviewsDue]);

  const versions = useMemo(() => {
    const map = new Map<string, { id: string; label: string }>();
    const add = (standardId: string, versionId: string, reference: string, label: string) => {
      if (standardFilter && standardId !== standardFilter) return;
      map.set(versionId, { id: versionId, label: `${reference} ${label}` });
    };
    for (const row of nonCompliant ?? []) add(row.standard_id, row.standard_version_id, row.standard_reference, row.version_label);
    for (const row of pending ?? []) add(row.standard_id, row.standard_version_id, row.standard_reference, row.version_label);
    for (const row of outstandingActions ?? []) add(row.standard_id, row.standard_version_id, row.standard_reference, row.version_label);
    for (const row of reviewsDue ?? []) {
      if (row.standard_id && row.standard_version_id && row.standard_reference && row.version_label) {
        add(row.standard_id, row.standard_version_id, row.standard_reference, row.version_label);
      }
    }
    return [...map.values()].sort((a, b) => a.label.localeCompare(b.label));
  }, [nonCompliant, pending, outstandingActions, reviewsDue, standardFilter]);

  const subSections = useMemo(() => {
    return [...requirementsById.values()]
      .filter((r) => r.parent_requirement_id === null)
      .sort((a, b) => a.sort_order - b.sort_order);
  }, [requirementsById]);

  function matchesStandardVersion(standardId: string | null, versionId: string | null): boolean {
    if (standardFilter && standardId !== standardFilter) return false;
    if (versionFilter && versionId !== versionFilter) return false;
    return true;
  }

  function matchesSubSection(requirementId: string): boolean {
    if (!subSectionFilter) return true;
    const top = complianceApi.findTopLevelAncestor(requirementsById, requirementId);
    return top !== null && top.id === subSectionFilter;
  }

  async function downloadReport(kind: "pdf" | "csv") {
    try {
      // Scoped to this panel's own current Standard/Standard version/Sub-
      // section filters (Phase 43) — matches `OrgComplianceOutstandingPanel.tsx`'s
      // identical convention. No Project filter here to pass through (this
      // page is already scoped to one project by URL).
      const blob = await complianceApi.downloadProjectComplianceReport(projectId, kind, {
        standardId: standardFilter || undefined,
        standardVersionId: versionFilter || undefined,
        requirementId: subSectionFilter || undefined,
      });
      downloadBlob(blob, `outstanding-compliance-items-report.${kind}`);
    } catch (err) {
      showToast(toErrorMessage(err, "Could not generate the outstanding items report."), "error");
    }
  }

  if (nonCompliant === null || pending === null || outstandingActions === null || reviewsDue === null) return <Spinner />;

  const filteredNonCompliant = nonCompliant.filter(
    (row) => matchesStandardVersion(row.standard_id, row.standard_version_id) && matchesSubSection(row.requirement_id)
  );
  const filteredPending = pending.filter(
    (row) => matchesStandardVersion(row.standard_id, row.standard_version_id) && matchesSubSection(row.requirement_id)
  );
  const filteredActions = outstandingActions.filter(
    (row) => matchesStandardVersion(row.standard_id, row.standard_version_id) && matchesSubSection(row.requirement_id)
  );
  const filteredReviewsDue = reviewsDue.filter((row) => matchesStandardVersion(row.standard_id, row.standard_version_id));

  return (
    <div className="side-grid">
      <div className="stack">
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <ReportExportButton onDownload={downloadReport} />
        </div>
        <section className="card stack">
          <h3 style={{ margin: 0 }}>Non-compliant requirements ({filteredNonCompliant.length})</h3>
          {filteredNonCompliant.length === 0 ? (
            <p className="text-muted" style={{ margin: 0 }}>None.</p>
          ) : (
            <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
              {filteredNonCompliant.map((row) => (
                <li key={row.project_compliance_requirement_id} style={{ borderBottom: "1px solid var(--color-border)", padding: "0.3rem 0" }}>
                  <strong>{row.standard_reference}</strong> — {row.requirement_reference ? `${row.requirement_reference} — ` : ""}{row.requirement_name}
                  {row.justification && <span className="text-muted"> — {row.justification}</span>}
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="card stack">
          <h3 style={{ margin: 0 }}>Pending approval ({filteredPending.length})</h3>
          {filteredPending.length === 0 ? (
            <p className="text-muted" style={{ margin: 0 }}>None.</p>
          ) : (
            <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
              {filteredPending.map((row) => (
                <li key={row.project_compliance_requirement_id} style={{ borderBottom: "1px solid var(--color-border)", padding: "0.3rem 0" }}>
                  <strong>{row.standard_reference}</strong> — {row.requirement_reference ? `${row.requirement_reference} — ` : ""}{row.requirement_name}
                  <span className="text-muted"> ({COMPLIANCE_STATUS_LABEL[row.compliance_status]})</span>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="card stack">
          <h3 style={{ margin: 0 }}>Outstanding required actions ({filteredActions.length})</h3>
          {filteredActions.length === 0 ? (
            <p className="text-muted" style={{ margin: 0 }}>None.</p>
          ) : (
            <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
              {filteredActions.map((row) => (
                <li key={row.required_action_assessment_id} style={{ borderBottom: "1px solid var(--color-border)", padding: "0.3rem 0" }}>
                  <strong>{row.standard_reference}</strong> — {row.requirement_reference ? `${row.requirement_reference} — ` : ""}{row.requirement_name} — {row.required_action_name}
                  {row.due_date && <span className="text-muted"> (due {row.due_date})</span>}
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="card stack">
          <h3 style={{ margin: 0 }}>Reviews due or overdue ({filteredReviewsDue.length})</h3>
          {filteredReviewsDue.length === 0 ? (
            <p className="text-muted" style={{ margin: 0 }}>None.</p>
          ) : (
            <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
              {filteredReviewsDue.map((review) => (
                <li key={review.id} style={{ borderBottom: "1px solid var(--color-border)", padding: "0.3rem 0" }}>
                  {review.frequency_label} — due {review.next_due_date}
                  {review.schedule_state && <span className="badge" style={{ marginLeft: "0.5rem" }}>{COMPLIANCE_REVIEW_SCHEDULE_STATE_LABEL[review.schedule_state]}</span>}
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      <FilterPanel sectionKey="projectCompliance.outstanding">
        <FilterField label="Standard">
          <select
            className="input"
            value={standardFilter}
            onChange={(e) => {
              setStandardFilter(e.target.value);
              setVersionFilter("");
              setSubSectionFilter("");
            }}
          >
            <option value="">All standards</option>
            {standards.map((s) => (
              <option key={s.id} value={s.id}>{s.reference} — {s.name}</option>
            ))}
          </select>
        </FilterField>
        <FilterField label="Standard version">
          <select className="input" value={versionFilter} onChange={(e) => setVersionFilter(e.target.value)} disabled={!standardFilter}>
            <option value="">All versions</option>
            {versions.map((v) => (
              <option key={v.id} value={v.id}>{v.label}</option>
            ))}
          </select>
        </FilterField>
        {standardFilter && (
          <FilterField label="Sub-section">
            <select className="input" value={subSectionFilter} onChange={(e) => setSubSectionFilter(e.target.value)}>
              <option value="">All sub-sections</option>
              {subSections.map((s) => (
                <option key={s.id} value={s.id}>{s.reference ? `${s.reference} — ${s.name}` : s.name}</option>
              ))}
            </select>
          </FilterField>
        )}
      </FilterPanel>
    </div>
  );
}
