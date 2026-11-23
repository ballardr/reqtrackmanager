/**
 * Module: modules/compliance/OrgComplianceOutstandingPanel
 *
 * The Outstanding tab of the Standards page (`StandardsTabs.tsx`, hosted by `ComplianceStatusPage.tsx`): the org-wide
 * counterpart of `OutstandingPanel.tsx`, listing what a Compliance Manager must identify across every project (§22):
 * Non-Compliant requirements, outstanding Required Actions, expired or expiring evidence, overdue reviews and assessments
 * awaiting approval. Each row names its project (`project_id`/`project_name`) and links to that project's Compliance page.
 * Read-only: acting on a row happens there.
 * - `?category=` picks which of the five sections renders and `?validity=` narrows the Evidence section (expired versus expiring
 *   soon), so `OrgComplianceWidgets.tsx`'s tiles link to the one section they count.
 * - The side filter panel of `ListPageLayout` filters by Project, Standard, Standard version and, once one standard is picked,
 *   Sub-section (client-derived options, as in `OrgComplianceStandardsPanel.tsx`). Standard, version and sub-section affect only
 *   the four requirement-adjacent sections; Evidence is not scoped to a standard (one row can link requirements of several), so
 *   Project and Evidence status govern it. Sub-section applies only to the three per-requirement sections ("section" is the
 *   top-level ancestor requirement, see `api.ts::findTopLevelAncestor`).
 * - Export (`ReportExportButton`) passes Project, Standard, Standard version and Sub-section to
 *   `complianceApi.downloadOrgComplianceReport`, matching the server's `_matches_requirement_filter`; `category` and
 *   `evidenceValidity` have no report equivalent and are not passed.
 */
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { FilterPanel } from "../../components/FilterPanel";
import { FilterSelect } from "../../components/FilterSelect";
import { ListPageLayout } from "../../components/ListPageLayout";
import { ReportExportButton } from "../../components/ReportExportButton";
import { Spinner } from "../../components/Spinner";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { downloadBlob } from "../../utils/download";
import * as complianceApi from "./api";
import { OrganisationLabel } from "./OrganisationCell";
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
import { Badge } from "../../components/Badge";
import { useResetOnChange } from "../../hooks/useResetOnChange";
import { useStrings } from "../../context/TerminologyContext";
import { t } from "../../i18n/strings";
import { useUrlChoice, useUrlText } from "../../hooks/useUrlFilter";
import type { ComplianceStatusFrame } from "./StandardsTabs";
import { COMPLIANCE_FILTER_LABEL } from "./filterLabels";
import { markdownPlainText } from "../../utils/markdownPlain";

type Category = "" | "non_compliant" | "pending" | "actions" | "evidence" | "reviews";
type EvidenceValidityFilter = "" | Extract<ComplianceEvidenceValidityState, "expired" | "expiring_soon">;

const CATEGORIES: Exclude<Category, "">[] = ["non_compliant", "pending", "actions", "evidence", "reviews"];
const EVIDENCE_VALIDITY_FILTERS: Exclude<EvidenceValidityFilter, "">[] = ["expired", "expiring_soon"];

function ProjectLink({ projectId, projectName }: { projectId: string; projectName: string }) {
  return <Link to={`/projects/${projectId}/modules/compliance`}>{projectName}</Link>;
}

/**
 * @param frame The Standards page's title-row parts (tab strip, tab panel attributes, Organisation filter) and the
 *   organisations whose outstanding items are shown.
 */
export function OrgComplianceOutstandingPanel({ frame }: { frame: ComplianceStatusFrame }) {
  const { orgs, showOrg } = frame;
  // Export is a per-organisation report; it is offered once the Organisation filter narrows to one.
  const exportOrgId = orgs.length === 1 ? orgs[0].id : null;
  const strings = useStrings();
  const { showToast } = useToast();
  // Every filter is in the URL, so the view comes back as it was left after a visit to a project's page, and the
  // summary widget's tiles open it already narrowed (`?category=evidence&validity=expired`).
  const [category, setCategory] = useUrlChoice<Exclude<Category, "">>("category", CATEGORIES);
  const [evidenceValidity, setEvidenceValidity] = useUrlChoice<Exclude<EvidenceValidityFilter, "">>("validity", EVIDENCE_VALIDITY_FILTERS);
  const [projectFilter, setProjectFilter] = useUrlText("project");
  const [standardFilter, setStandardFilter] = useUrlText("standard");
  const [versionFilter, setVersionFilter] = useUrlText("version");
  const [subSectionFilter, setSubSectionFilter] = useUrlText("section");
  const [loadFailed, setLoadFailed] = useState(false);
  const [requirementsById, setRequirementsById] = useState<Map<string, ComplianceRequirement>>(new Map());
  const [nonCompliant, setNonCompliant] = useState<complianceApi.InOrganization<OrgNonCompliantRequirement>[] | null>(null);
  const [pending, setPending] = useState<complianceApi.InOrganization<OrgPendingApproval>[] | null>(null);
  const [outstandingActions, setOutstandingActions] = useState<complianceApi.InOrganization<OutstandingRequiredAction>[] | null>(null);
  const [expiringEvidence, setExpiringEvidence] = useState<complianceApi.InOrganization<OrgExpiringEvidence>[] | null>(null);
  const [reviewsDue, setReviewsDue] = useState<complianceApi.InOrganization<OrgReviewDue>[] | null>(null);

  useEffect(() => {
    Promise.all([
      complianceApi.collectAcrossOrgs(orgs, (orgId) => complianceApi.listOrgNonCompliantRequirements(orgId)),
      complianceApi.collectAcrossOrgs(orgs, (orgId) => complianceApi.listOrgPendingApprovals(orgId)),
      complianceApi.collectAcrossOrgs(orgs, (orgId) => complianceApi.listOrgOutstandingRequiredActions(orgId)),
      complianceApi.collectAcrossOrgs(orgs, (orgId) => complianceApi.listOrgExpiringEvidence(orgId)),
      complianceApi.collectAcrossOrgs(orgs, (orgId) => complianceApi.listOrgReviewsDue(orgId)),
    ])
      .then(([nc, pa, oa, ee, rd]) => {
        setNonCompliant(nc);
        setPending(pa);
        setOutstandingActions(oa);
        setExpiringEvidence(ee);
        setReviewsDue(rd);
      })
      .catch((err) => {
        setLoadFailed(true);
        showToast(toErrorMessage(err, "Could not load organisation outstanding items."), "error");
      });
  }, [orgs, showToast]);

  // Sub-section options come from every version of the selected standard's requirement tree, fetched when the standard filter
  // changes rather than derived from the on-screen rows, so changing the version filter needs no second fetch.
  useResetOnChange([standardFilter], () => setRequirementsById(new Map()));

  const standards = useMemo(() => {
    const map = new Map<string, { id: string; reference: string; name: string; orgId: string; orgName: string }>();
    for (const row of nonCompliant ?? []) map.set(row.standard_id, { id: row.standard_id, reference: row.standard_reference, name: row.standard_name, orgId: row.organization_id, orgName: row.organization_name });
    for (const row of pending ?? []) map.set(row.standard_id, { id: row.standard_id, reference: row.standard_reference, name: row.standard_name, orgId: row.organization_id, orgName: row.organization_name });
    for (const row of outstandingActions ?? []) map.set(row.standard_id, { id: row.standard_id, reference: row.standard_reference, name: row.standard_name, orgId: row.organization_id, orgName: row.organization_name });
    for (const row of reviewsDue ?? []) {
      if (row.review.standard_id && row.review.standard_reference) {
        map.set(row.review.standard_id, { id: row.review.standard_id, reference: row.review.standard_reference, name: row.review.standard_name ?? "", orgId: row.organization_id, orgName: row.organization_name });
      }
    }
    return [...map.values()].sort((a, b) => a.reference.localeCompare(b.reference));
  }, [nonCompliant, pending, outstandingActions, reviewsDue]);

  // A standard belongs to one organisation; its requirement structure is read from that organisation.
  const standardOrgId = standards.find((s) => s.id === standardFilter)?.orgId ?? "";

  useEffect(() => {
    if (!standardFilter || !standardOrgId) return;
    let cancelled = false;
    complianceApi
      .listStandardVersions(standardOrgId, standardFilter)
      .then((versions) => Promise.all(versions.map((v) => complianceApi.listRequirements(standardOrgId, standardFilter, v.id))))
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
  }, [standardOrgId, standardFilter, showToast]);

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

  async function downloadReport(kind: complianceApi.ComplianceReportKind) {
    try {
      // Scoped to the panel's current filters, as in `OrgComplianceStandardsPanel.tsx`; `category` and `evidenceValidity`
      // have no report equivalent (the report covers every category) and are not passed.
      if (!exportOrgId) return;
      const blob = await complianceApi.downloadOrgComplianceReport(exportOrgId, kind, {
        projectId: projectFilter || undefined,
        standardId: standardFilter || undefined,
        standardVersionId: versionFilter || undefined,
        requirementId: subSectionFilter || undefined,
      });
      downloadBlob(blob, `outstanding-compliance-items-report.${kind}`);
    } catch (err) {
      showToast(toErrorMessage(err, "Could not generate the outstanding items report."), "error");
    }
  }

  const loading =
    nonCompliant === null || pending === null || outstandingActions === null || expiringEvidence === null || reviewsDue === null;
  if (loading) {
    return (
      <ListPageLayout
        title={t().standardsPage.title} tabs={frame.tabs} contentProps={frame.contentProps} ready={false}
        filter={<FilterPanel sectionKey="orgCompliance.outstanding">{frame.orgFilter}</FilterPanel>}
      >
        {loadFailed ? <p className="text-muted">{t().standardsPage.noStatusAccess}</p> : <Spinner />}
      </ListPageLayout>
    );
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

  const filter = (
    <FilterPanel sectionKey="orgCompliance.outstanding">
      {frame.orgFilter}

        <FilterSelect
          label="Category"
          value={category}
          onChange={setCategory}
          allLabel="All categories"
          options={[{ value: "non_compliant", label: "Non-compliant requirements" }, { value: "pending", label: "Pending approval" }, { value: "actions", label: "Outstanding required actions" }, { value: "evidence", label: "Evidence expired or expiring" }, { value: "reviews", label: "Reviews due or overdue" }]}
        />
        <FilterSelect
          label="Evidence status"
          value={evidenceValidity}
          onChange={setEvidenceValidity}
          allLabel="All"
          options={[{ value: "expired", label: "Expired" }, { value: "expiring_soon", label: "Expiring soon" }]}
          disabled={category !== "" && category !== "evidence"}
        />
        <FilterSelect
          label={strings.filters.project}
          value={projectFilter}
          onChange={setProjectFilter}
          allLabel={strings.filters.allProjects}
          options={projects.map((p) => ({ value: p.id, label: p.name }))}
        />
        <FilterSelect
          label={COMPLIANCE_FILTER_LABEL.standard}
          value={standardFilter}
          onChange={(v) => {
              setStandardFilter(v);
              setVersionFilter("");
              setSubSectionFilter("");
            }}
          allLabel="All standards"
          options={standards.map((s) => ({ value: s.id, label: `${s.reference} — ${s.name}${showOrg ? ` (${s.orgName})` : ""}` }))}
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
  );

  return (
    <ListPageLayout
      title={t().standardsPage.title}
      actions={exportOrgId && <ReportExportButton onDownload={downloadReport} kinds={complianceApi.COMPLIANCE_REPORT_KINDS} />}
      tabs={frame.tabs}
      contentProps={frame.contentProps}
      filter={filter}
    >
        {(category === "" || category === "non_compliant") && (
          <section className="card stack">
            <h3 style={{ margin: 0 }}>Non-compliant requirements ({filteredNonCompliant.length})</h3>
            {filteredNonCompliant.length === 0 ? (
              <p className="text-muted" style={{ margin: 0 }}>None.</p>
            ) : (
              <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
                {filteredNonCompliant.map((row) => (
                  <li key={row.project_compliance_requirement_id} style={{ borderBottom: "1px solid var(--color-border)", padding: "0.3rem 0" }}>
                    <OrganisationLabel name={row.organization_name} show={showOrg} /><ProjectLink projectId={row.project_id} projectName={row.project_name} /> — <strong>{row.standard_reference}</strong> — {row.requirement_reference ? `${row.requirement_reference} — ` : ""}{row.requirement_name}
                    {row.justification && <span className="text-muted"> — {markdownPlainText(row.justification)}</span>}
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
                    <OrganisationLabel name={row.organization_name} show={showOrg} /><ProjectLink projectId={row.project_id} projectName={row.project_name} /> — <strong>{row.standard_reference}</strong> — {row.requirement_reference ? `${row.requirement_reference} — ` : ""}{row.requirement_name}
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
                    <OrganisationLabel name={row.organization_name} show={showOrg} /><ProjectLink projectId={row.project_id} projectName={row.project_name} /> — <strong>{row.standard_reference}</strong> — {row.requirement_reference ? `${row.requirement_reference} — ` : ""}{row.requirement_name} — {row.required_action_name}
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
                    <OrganisationLabel name={row.organization_name} show={showOrg} /><ProjectLink projectId={row.project_id} projectName={row.project_name} /> — {row.title}
                    <Badge className="badge-after">{COMPLIANCE_EVIDENCE_VALIDITY_STATE_LABEL[row.validity_state]}</Badge>
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
                    <OrganisationLabel name={row.organization_name} show={showOrg} /><ProjectLink projectId={row.project_id} projectName={row.project_name} /> — {row.review.frequency_label} — due {row.review.next_due_date}
                    {row.review.schedule_state && <Badge className="badge-after">{COMPLIANCE_REVIEW_SCHEDULE_STATE_LABEL[row.review.schedule_state]}</Badge>}
                  </li>
                ))}
              </ul>
            )}
          </section>
        )}
    </ListPageLayout>
  );
}
