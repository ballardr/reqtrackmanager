/**
 * Module: modules/compliance/OutstandingPanel
 *
 * The Project Compliance View's "what remains outstanding" summary (§21): the four read-only, drillable listings §20-§22 call
 * for, across every active standard assignment of the project, as lists and not only counts: Non-Compliant requirements,
 * requirements Pending Approval (§12), outstanding Required Actions (§22, from the flattened cross-assignment listing that
 * also powers the org-wide equivalent) and reviews due or overdue (§17). Acting on a row (assess, approve, complete a
 * review or required action) happens in `ApplicabilityTree` and `ReviewsPanel` on the Standards tab.
 * - Standard, Standard version and Sub-section filters match `OrgComplianceOutstandingPanel` without a Project filter (the
 *   page is project-scoped), so a project with several standards need not show everything in one flat set; that panel's notes
 *   explain how Evidence and the Sub-section filter are scoped.
 * - Export (`ReportExportButton`) passes the current filters to `complianceApi.downloadProjectComplianceReport`.
 */
import { useEffect, useMemo, useState } from "react";

import { FilterPanel } from "../../components/FilterPanel";
import { FilterSelect } from "../../components/FilterSelect";
import { ListActions } from "../../components/ListActions";
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
import { Badge } from "../../components/Badge";
import { useResetOnChange } from "../../hooks/useResetOnChange";
import { COMPLIANCE_FILTER_LABEL } from "./filterLabels";
import { markdownPlainText } from "../../utils/markdownPlain";

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

  useResetOnChange([orgId, standardFilter], () => setRequirementsById(new Map()));

  useEffect(() => {
    if (!standardFilter) return;
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

  /** The outstanding required actions list's filters by the names its export takes. */
  function actionFilterParams(): URLSearchParams {
    const params = new URLSearchParams({ outstanding: "true" });
    if (standardFilter) params.set("standard", standardFilter);
    if (versionFilter) params.set("version", versionFilter);
    if (subSectionFilter) params.set("section", subSectionFilter);
    return params;
  }

  async function downloadReport(kind: complianceApi.ComplianceReportKind) {
    try {
      // Scoped to the panel's current Standard, Standard version and Sub-section filters, as in
      // `OrgComplianceOutstandingPanel.tsx`; there is no Project filter because the URL scopes the page.
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
        <div className="row" style={{ justifyContent: "flex-end", gap: "var(--space-3)" }}>
          <ListActions
            projectId={projectId} recordType="compliance_required_action_assessment" kindLabel="outstanding required actions"
            filters={actionFilterParams().toString()}
          />
          <ReportExportButton onDownload={downloadReport} kinds={complianceApi.COMPLIANCE_REPORT_KINDS} />
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
                  {row.justification && <span className="text-muted"> — {markdownPlainText(row.justification)}</span>}
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
                  {review.schedule_state && <Badge className="badge-after">{COMPLIANCE_REVIEW_SCHEDULE_STATE_LABEL[review.schedule_state]}</Badge>}
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      <FilterPanel sectionKey="projectCompliance.outstanding">
        <FilterSelect
          label={COMPLIANCE_FILTER_LABEL.standard}
          value={standardFilter}
          onChange={(v) => {
              setStandardFilter(v);
              setVersionFilter("");
              setSubSectionFilter("");
            }}
          allLabel="All standards"
          options={standards.map((s) => ({ value: s.id, label: `${s.reference} — ${s.name}` }))}
        />
        <FilterSelect
          label={COMPLIANCE_FILTER_LABEL.standardVersion}
          value={versionFilter}
          onChange={setVersionFilter}
          allLabel="All versions"
          options={versions.map((v) => ({ value: v.id, label: v.label }))}
          disabled={!standardFilter}
        />
        {standardFilter && (
          <FilterSelect
            label={COMPLIANCE_FILTER_LABEL.subSection}
            value={subSectionFilter}
            onChange={setSubSectionFilter}
            allLabel="All sub-sections"
            options={subSections.map((s) => ({ value: s.id, label: s.reference ? `${s.reference} — ${s.name}` : s.name }))}
          />
        )}
      </FilterPanel>
    </div>
  );
}
