/**
 * Module: modules/compliance/OrgComplianceOutstandingPanel
 *
 * The org-wide counterpart to `OutstandingPanel.tsx` (Phase 13's own
 * per-project "what remains outstanding" summary) — §22's own explicit
 * list of things a Compliance Manager must be able to identify across
 * every project at once: Non-Compliant requirements, outstanding Required
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
 *
 * Phase 40 adds real filtering on top of the category picker: Project,
 * Standard, Standard version, and (once a single standard is picked)
 * Sub-section — following `OrgComplianceStandardsPanel.tsx`'s own
 * client-side-derived-options pattern — and moves the filter panel from a
 * `layout="top"` bar to the standard `layout="side"` sidebar (`side-grid`),
 * per `FilterPanel.tsx`'s own documented placement rule: `"top"` is for
 * wide, many-column *tables*, and this panel is a stack of card sections,
 * exactly the shape `OrgComplianceStandardsPanel` already uses `"side"`
 * for. Standard/Standard version/Sub-section only affect the four
 * requirement-adjacent sections (Non-compliant, Pending approval,
 * Outstanding actions, Reviews) — `Evidence` isn't scoped to a standard at
 * all in the data model (an evidence row can be linked to requirements
 * across more than one standard), so it stays governed by Project +
 * Evidence status alone, unaffected by the new filters (Decided by:
 * Agent). Sub-section further only applies to the three
 * per-requirement sections (Reviews aren't tied to one specific
 * requirement, only to a standard/version as a whole) — see
 * `api.ts::findTopLevelAncestor`'s own docstring for why "section" means
 * "top-level ancestor requirement" here.
 */
import { useEffect, useMemo, useState } from "react";
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
  type ComplianceRequirement,
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
  const [projectFilter, setProjectFilter] = useState("");
  const [standardFilter, setStandardFilter] = useState("");
  const [versionFilter, setVersionFilter] = useState("");
  const [subSectionFilter, setSubSectionFilter] = useState("");
  const [requirementsById, setRequirementsById] = useState<Map<string, ComplianceRequirement>>(new Map());
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

  // Sub-section options come from every version of the selected standard's
  // own requirement tree — fetched fresh whenever the standard filter
  // changes, not derived from the (possibly already version-narrowed) rows
  // already on screen, so switching the version filter afterward doesn't
  // require a second fetch.
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
      if (row.review.standard_id && row.review.standard_reference) {
        map.set(row.review.standard_id, { id: row.review.standard_id, reference: row.review.standard_reference, name: row.review.standard_name ?? "" });
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
      const r = row.review;
      if (r.standard_id && r.standard_version_id && r.standard_reference && r.version_label) {
        add(r.standard_id, r.standard_version_id, r.standard_reference, r.version_label);
      }
    }
    return [...map.values()].sort((a, b) => a.label.localeCompare(b.label));
  }, [nonCompliant, pending, outstandingActions, reviewsDue, standardFilter]);

  const projects = useMemo(() => {
    const map = new Map<string, { id: string; name: string }>();
    for (const row of nonCompliant ?? []) map.set(row.project_id, { id: row.project_id, name: row.project_name });
    for (const row of pending ?? []) map.set(row.project_id, { id: row.project_id, name: row.project_name });
    for (const row of outstandingActions ?? []) map.set(row.project_id, { id: row.project_id, name: row.project_name });
    for (const row of expiringEvidence ?? []) map.set(row.project_id, { id: row.project_id, name: row.project_name });
    for (const row of reviewsDue ?? []) map.set(row.project_id, { id: row.project_id, name: row.project_name });
    return [...map.values()].sort((a, b) => a.name.localeCompare(b.name));
  }, [nonCompliant, pending, outstandingActions, expiringEvidence, reviewsDue]);

  const subSections = useMemo(() => {
    return [...requirementsById.values()]
      .filter((r) => r.parent_requirement_id === null)
      .sort((a, b) => a.sort_order - b.sort_order);
  }, [requirementsById]);

  function matchesProject(projectId: string): boolean {
    return !projectFilter || projectId === projectFilter;
  }

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

  if (nonCompliant === null || pending === null || outstandingActions === null || expiringEvidence === null || reviewsDue === null) {
    return <Spinner />;
  }

  const filteredNonCompliant = nonCompliant.filter(
    (row) => matchesProject(row.project_id) && matchesStandardVersion(row.standard_id, row.standard_version_id) && matchesSubSection(row.requirement_id)
  );
  const filteredPending = pending.filter(
    (row) => matchesProject(row.project_id) && matchesStandardVersion(row.standard_id, row.standard_version_id) && matchesSubSection(row.requirement_id)
  );
  const filteredActions = outstandingActions.filter(
    (row) => matchesProject(row.project_id) && matchesStandardVersion(row.standard_id, row.standard_version_id) && matchesSubSection(row.requirement_id)
  );
  const filteredReviewsDue = reviewsDue.filter(
    (row) => matchesProject(row.project_id) && matchesStandardVersion(row.review.standard_id, row.review.standard_version_id)
  );
  const filteredEvidence = expiringEvidence.filter(
    (e) => matchesProject(e.project_id) && (!evidenceValidity || e.validity_state === evidenceValidity)
  );
  const evidenceHeading =
    evidenceValidity === "expired"
      ? "Evidence expired"
      : evidenceValidity === "expiring_soon"
        ? "Evidence expiring soon"
        : "Evidence expired or expiring";

  return (
    <div className="side-grid">
      <div className="stack">
        {(category === "" || category === "non_compliant") && (
          <section className="card stack">
            <h3 style={{ margin: 0 }}>Non-compliant requirements ({filteredNonCompliant.length})</h3>
            {filteredNonCompliant.length === 0 ? (
              <p className="text-muted" style={{ margin: 0 }}>None.</p>
            ) : (
              <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
                {filteredNonCompliant.map((row) => (
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
            <h3 style={{ margin: 0 }}>Pending approval ({filteredPending.length})</h3>
            {filteredPending.length === 0 ? (
              <p className="text-muted" style={{ margin: 0 }}>None.</p>
            ) : (
              <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
                {filteredPending.map((row) => (
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
            <h3 style={{ margin: 0 }}>Outstanding required actions ({filteredActions.length})</h3>
            {filteredActions.length === 0 ? (
              <p className="text-muted" style={{ margin: 0 }}>None.</p>
            ) : (
              <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
                {filteredActions.map((row) => (
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
            <h3 style={{ margin: 0 }}>Reviews due or overdue ({filteredReviewsDue.length})</h3>
            {filteredReviewsDue.length === 0 ? (
              <p className="text-muted" style={{ margin: 0 }}>None.</p>
            ) : (
              <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
                {filteredReviewsDue.map((row) => (
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

      <FilterPanel sectionKey="orgCompliance.outstanding">
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
        <FilterField label="Project">
          <select className="input" value={projectFilter} onChange={(e) => setProjectFilter(e.target.value)}>
            <option value="">All projects</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
        </FilterField>
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
