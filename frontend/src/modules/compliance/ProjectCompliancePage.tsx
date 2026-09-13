/**
 * Module: modules/compliance/ProjectCompliancePage
 *
 * The Compliance Module's project-scoped, Project-Manager/Compliance-
 * Officer-facing view (docs/compliance-module-plan.md Phase 13;
 * requirements doc §21, plus UI portions of §7-§10, §12, §13) — the route
 * component Phase 3's Tier A mechanism mounts at
 * `/projects/:projectId/modules/compliance` (see `modules/registry.ts`).
 *
 * Top-level shape: three `Tabs` — "Standards" (every standard assigned to
 * this project, §7, drilling into `ProjectComplianceDetail` for one
 * assignment's own applicability/assessment tree and reviews), "Evidence"
 * (`EvidencePanel`, project-wide per §13's own multi-assignment linkage),
 * and "Outstanding" (`OutstandingPanel` — the cross-assignment Non-
 * Compliant/Pending-Approval/Reviews-Due listings §20/§21 call for as their
 * own drillable lists, gathered in one place so "what remains outstanding"
 * doesn't require opening every assignment in turn, per §21's own "make it
 * easy... to determine what remains outstanding").
 *
 * Standard-to-project *assignment itself* is a Compliance Manager action on
 * the *org* router (`router.py::create_project_compliance`'s own Phase 7
 * design — see that endpoint's docstring), even though this whole page is
 * project-scoped; this page fetches the owning project's `organization_id`
 * once and passes it down wherever an org-router call is needed. Mirrors
 * `RequirementsPage.tsx`'s own "fetch the project, read `organization_id`
 * off it" convention (no `ProjectContext` provider exists in this codebase
 * — see that page's own link-types fetch for precedent) rather than
 * introducing one for this single page.
 *
 * Every mutating control always renders; the backend enforces
 * `require_module_role("compliance", "compliance_officer")`/
 * `_require_manage` and a 403 surfaces as a toast — the same "no client-side
 * can-i-manage precomputation" posture `ComplianceAdminPanel.tsx` (Phase 12)
 * established, since no "my effective roles including module roles" endpoint
 * exists to check against without adding one (flagged there, still true
 * here).
 *
 * The Standards tab's "Download PDF report"/"Download CSV report" buttons
 * (Phase 15, §29) hit `GET .../modules/compliance/reports/{pdf,csv}`
 * directly via `api.getForBlob` + `downloadBlob` — the exact same
 * fetch-a-blob-and-save-it idiom `pages/ReportsPage.tsx`'s own PDF/CSV
 * buttons already use for core requirement reports (that page's `generate`
 * function), reused rather than reinvented for this module's own report
 * generator (`app.modules.compliance.reports`).
 */
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import type { OrgUser, Project } from "../../api/types";
import { api } from "../../api/client";
import { DirectoryTable, type DirectoryColumn } from "../../components/DirectoryTable";
import { Modal } from "../../components/Modal";
import { Spinner } from "../../components/Spinner";
import { Tabs, tabPanelProps } from "../../components/Tabs";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { downloadBlob } from "../../utils/download";
import * as complianceApi from "./api";
import { EvidencePanel } from "./EvidencePanel";
import { OutstandingPanel } from "./OutstandingPanel";
import { ProjectComplianceDetail } from "./ProjectComplianceDetail";
import { complianceRiskLabel, type ComplianceStandard, type ComplianceStandardVersion, type ProjectCompliance, type ProjectComplianceStatus } from "./types";

type ComplianceTabKey = "standards" | "evidence" | "outstanding";

/** One row of the Standards tab's directory — a `ProjectCompliance`
 * assignment, decorated with its computed §20 status when active (archived
 * assignments have no status row — `GET .../status` only returns active
 * ones, see that endpoint's own docstring). */
interface AssignmentRow {
  assignment: ProjectCompliance;
  status: ProjectComplianceStatus | null;
}

export function ProjectCompliancePage() {
  const { projectId } = useParams<{ projectId: string }>();
  const { showToast } = useToast();
  const [tab, setTab] = useState<ComplianceTabKey>("standards");
  const [project, setProject] = useState<Project | null>(null);
  const [orgUsers, setOrgUsers] = useState<OrgUser[]>([]);
  const [assignments, setAssignments] = useState<ProjectCompliance[] | null>(null);
  const [statuses, setStatuses] = useState<ProjectComplianceStatus[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selected, setSelected] = useState<ProjectCompliance | null>(null);
  const [assigning, setAssigning] = useState(false);
  const [downloading, setDownloading] = useState<"pdf" | "csv" | null>(null);

  async function downloadReport(kind: "pdf" | "csv") {
    if (!projectId || !project) return;
    setDownloading(kind);
    try {
      const blob = await api.getForBlob(`/api/v1/projects/${projectId}/modules/compliance/reports/${kind}`);
      const safeName = project.name.replace(/[\\/"\r\n\t]/g, "") || "project";
      downloadBlob(blob, `${safeName}-compliance-report.${kind}`);
    } catch (err) {
      showToast(toErrorMessage(err, "Could not generate the compliance report."), "error");
    } finally {
      setDownloading(null);
    }
  }

  async function reload() {
    if (!projectId) return;
    try {
      const [assignmentList, statusList] = await Promise.all([
        complianceApi.listProjectCompliance(projectId),
        complianceApi.getProjectComplianceStatus(projectId),
      ]);
      setAssignments(assignmentList);
      setStatuses(statusList);
      setLoadError(null);
    } catch (err) {
      setLoadError(
        toErrorMessage(err, "The Compliance module isn't enabled for this project's organisation, or you don't have access to it.")
      );
    }
  }

  useEffect(() => {
    if (!projectId) return;
    api.get<Project>(`/api/v1/projects/${projectId}`).then((proj) => {
      setProject(proj);
      api.get<OrgUser[]>(`/api/v1/orgs/${proj.organization_id}/users`).then(setOrgUsers);
    });
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  if (!projectId) return null;
  if (loadError) return <p className="text-muted">{loadError}</p>;
  if (assignments === null || project === null) return <Spinner />;

  if (selected) {
    const status = statuses.find((s) => s.project_compliance_id === selected.id) ?? null;
    return (
      <div className="container stack">
        <ProjectComplianceDetail
          orgId={project.organization_id}
          projectId={projectId}
          assignment={selected}
          status={status}
          orgUsers={orgUsers}
          onBack={() => setSelected(null)}
          onArchiveToggled={async (updated) => {
            setSelected(updated);
            await reload();
          }}
        />
      </div>
    );
  }

  const rows: AssignmentRow[] = assignments.map((assignment) => ({
    assignment,
    status: statuses.find((s) => s.project_compliance_id === assignment.id) ?? null,
  }));

  const columns: DirectoryColumn<AssignmentRow>[] = [
    {
      key: "standard", label: "Standard",
      render: (row) => (row.status ? `${row.status.standard_reference} — ${row.status.standard_name}` : "—"),
    },
    { key: "version", label: "Version", render: (row) => row.status?.version_label ?? "—" },
    {
      key: "compliance", label: "Compliance",
      render: (row) =>
        row.assignment.is_archived
          ? "Archived"
          : row.status
            ? `${row.status.compliance_percentage.toFixed(1)}% (${row.status.applicable_count} applicable)`
            : "—",
    },
    {
      key: "outstanding", label: "Non-compliant",
      render: (row) => (row.status ? complianceRiskLabel(row.status) : "—"),
    },
    { key: "target_date", label: "Target date", render: (row) => row.assignment.target_compliance_date ?? "—" },
  ];

  return (
    <div className="container stack">
      <h1 style={{ margin: 0 }}>Compliance</h1>
      <Tabs<ComplianceTabKey>
        idPrefix="project-compliance"
        active={tab}
        onChange={setTab}
        tabs={[
          { key: "standards", label: "Standards" },
          { key: "evidence", label: "Evidence" },
          { key: "outstanding", label: "Outstanding" },
        ]}
      />
      {tab === "standards" && (
        <div className="stack" {...tabPanelProps("project-compliance", "standards")}>
          <div className="row" style={{ gap: "0.5rem", flexWrap: "wrap" }}>
            <button className="btn btn-primary" onClick={() => setAssigning(true)}>
              Assign standard
            </button>
            <button className="btn" onClick={() => downloadReport("pdf")} disabled={downloading !== null}>
              {downloading === "pdf" ? "…" : "Download PDF report"}
            </button>
            <button className="btn" onClick={() => downloadReport("csv")} disabled={downloading !== null}>
              {downloading === "csv" ? "…" : "Download CSV report"}
            </button>
          </div>
          <DirectoryTable
            ariaLabel="Compliance standards assigned to this project"
            columns={columns}
            rows={rows}
            rowKey={(row) => row.assignment.id}
            onRowClick={(row) => setSelected(row.assignment)}
            emptyState={<p className="text-muted">No compliance standards assigned to this project yet.</p>}
          />
        </div>
      )}
      {tab === "evidence" && (
        <div {...tabPanelProps("project-compliance", "evidence")}>
          <EvidencePanel projectId={projectId} orgId={project.organization_id} />
        </div>
      )}
      {tab === "outstanding" && (
        <div {...tabPanelProps("project-compliance", "outstanding")}>
          <OutstandingPanel projectId={projectId} orgId={project.organization_id} />
        </div>
      )}

      {assigning && (
        <AssignStandardModal
          orgId={project.organization_id}
          onCancel={() => setAssigning(false)}
          onSave={async (values) => {
            try {
              // Phase 20's default, primary assignment path — works for a
              // plain Project Manager with no `compliance_officer` grant,
              // not gated behind it (see docs/compliance-module-plan.md
              // Phase 20).
              await complianceApi.createProjectComplianceAsProjectManager(projectId, values);
              showToast("Standard assigned to project.");
              setAssigning(false);
              await reload();
            } catch (err) {
              showToast(toErrorMessage(err, "Could not assign standard."), "error");
            }
          }}
        />
      )}
    </div>
  );
}

function AssignStandardModal({
  orgId,
  onCancel,
  onSave,
}: {
  orgId: string;
  onCancel: () => void;
  onSave: (values: { standard_id: string; standard_version_id: string; target_compliance_date: string | null }) => void;
}) {
  const { showToast } = useToast();
  const [standards, setStandards] = useState<ComplianceStandard[] | null>(null);
  const [standardId, setStandardId] = useState("");
  const [versions, setVersions] = useState<ComplianceStandardVersion[] | null>(null);
  const [versionId, setVersionId] = useState("");
  const [targetDate, setTargetDate] = useState("");

  useEffect(() => {
    complianceApi.listStandards(orgId).then(setStandards).catch((err) => {
      showToast(toErrorMessage(err, "Could not load compliance standards."), "error");
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orgId]);

  useEffect(() => {
    if (!standardId) {
      setVersions(null);
      setVersionId("");
      return;
    }
    complianceApi.listStandardVersions(orgId, standardId).then((all) => {
      const published = all.filter((v) => v.status === "published");
      setVersions(published);
      setVersionId(published[0]?.id ?? "");
    }).catch((err) => {
      showToast(toErrorMessage(err, "Could not load standard versions."), "error");
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orgId, standardId]);

  return (
    <Modal title="Assign compliance standard" onClose={onCancel}>
      <div className="stack">
        {standards === null ? (
          <Spinner />
        ) : standards.length === 0 ? (
          <p className="text-muted">No compliance standards exist in this organisation yet.</p>
        ) : (
          <>
            <label className="stack" style={{ gap: "0.25rem" }}>
              <span>Standard</span>
              <select className="input" value={standardId} onChange={(e) => setStandardId(e.target.value)} aria-label="Standard">
                <option value="">Select a standard…</option>
                {standards.filter((s) => !s.is_archived).map((s) => (
                  <option key={s.id} value={s.id}>{s.reference} — {s.name}</option>
                ))}
              </select>
            </label>
            {standardId && (
              <label className="stack" style={{ gap: "0.25rem" }}>
                <span>Version</span>
                {versions === null ? (
                  <Spinner />
                ) : versions.length === 0 ? (
                  <p className="text-muted" style={{ margin: 0 }}>This standard has no published version to assign.</p>
                ) : (
                  <select className="input" value={versionId} onChange={(e) => setVersionId(e.target.value)} aria-label="Standard version">
                    {versions.map((v) => (
                      <option key={v.id} value={v.id}>{v.version_label}</option>
                    ))}
                  </select>
                )}
              </label>
            )}
            <label className="stack" style={{ gap: "0.25rem" }}>
              <span>Target compliance date (optional)</span>
              <input className="input" type="date" value={targetDate} onChange={(e) => setTargetDate(e.target.value)} />
            </label>
          </>
        )}
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn" onClick={onCancel}>Cancel</button>
          <button
            className="btn btn-primary"
            disabled={!standardId || !versionId}
            onClick={() => onSave({ standard_id: standardId, standard_version_id: versionId, target_compliance_date: targetDate || null })}
          >
            Assign
          </button>
        </div>
      </div>
    </Modal>
  );
}
