/**
 * Module: modules/compliance/ProjectCompliancePage
 *
 * The Compliance module's project-scoped view for a Project Manager or Compliance Officer (requirements doc §21 and the UI
 * parts of §7-§10, §12, §13), the route component mounted at `/projects/:projectId/modules/compliance` (`modules/registry.ts`).
 * Three `Tabs`: "Standards" (every standard assigned to the project, §7, drilling into `ProjectComplianceDetail`), "Evidence"
 * (`EvidencePanel`, project-wide per §13) and "Outstanding" (`OutstandingPanel`, §20/§21). `?tab=evidence|outstanding` opens
 * that tab on arrival (read once; the evidence detail page's Back link uses it).
 * - Assigning a standard to the project is a Compliance Manager action on the *org* router (`router.py::create_project_compliance`),
 *   so the page fetches the project's `organization_id` once and passes it to org-router calls (as `RequirementsPage.tsx` does;
 *   no `ProjectContext` provider exists for it).
 * - Every mutating control always renders; the backend enforces `require_module_role("compliance", "compliance_officer")` and
 *   `_require_manage` and a 403 surfaces as a toast, because no endpoint gives the person's effective roles including module roles.
 * - The Standards tab's Export (§29) calls `GET .../modules/compliance/reports?format=...` through `api.getForBlob` and
 *   `downloadBlob`, as `pages/ReportsPage.tsx` does, using the shared `ReportExportButton` (one trigger opening a PDF/CSV `Popover`).
 */
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import type { OrgUser, Project } from "../../api/types";
import { api } from "../../api/client";
import { DirectoryTable, type DirectoryColumn } from "../../components/DirectoryTable";
import { Modal } from "../../components/Modal";
import { ReportExportButton } from "../../components/ReportExportButton";
import { Spinner } from "../../components/Spinner";
import { Tabs, tabPanelProps } from "../../components/Tabs";
import { useCurrentNavLabelOverride } from "../../context/NavLabelValue";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { useSortState } from "../../hooks/useTableSort";
import { sortRows, type SortValue } from "../../utils/sortRows";
import { downloadBlob } from "../../utils/download";
import * as complianceApi from "./api";
import { EvidencePanel } from "./EvidencePanel";
import { OutstandingPanel } from "./OutstandingPanel";
import { ProjectComplianceDetail } from "./ProjectComplianceDetail";
import { complianceRiskLabel, type ComplianceStandard, type ComplianceStandardVersion, type ProjectCompliance, type ProjectComplianceStatus } from "./types";
import { DateField } from "../../components/FormFields";
import { FormActions } from "../../components/FormActions";
import { FormGrid } from "../../components/FormGrid";
import { LabeledSelect } from "../../components/LabeledSelect";
import { useResetOnChange } from "../../hooks/useResetOnChange";
import { useInitialSearchParams, oneOf } from "../../hooks/useInitialSearchParams";
import { useLoadOnChange } from "../../hooks/useLoadOnChange";
import { COMPLIANCE_HELP } from "./help";

const COMPLIANCE_TABS = ["standards", "evidence", "outstanding"] as const;
type ComplianceTabKey = (typeof COMPLIANCE_TABS)[number];

/** One row of the Standards tab's directory: a `ProjectCompliance` assignment decorated with its computed §20 status when
 * active (`GET .../status` returns active assignments only). */
interface AssignmentRow {
  assignment: ProjectCompliance;
  status: ProjectComplianceStatus | null;
}

/** Sortable value of each sortable column of the standards table. */
const ASSIGNMENT_SORT_VALUES: Record<string, (row: AssignmentRow) => SortValue> = {
  standard: (row) => (row.status ? `${row.status.standard_reference} ${row.status.standard_name}` : null),
  version: (row) => row.status?.version_label ?? null,
  compliance: (row) => (row.assignment.is_archived || !row.status ? null : row.status.compliance_percentage),
  outstanding: (row) => (row.status ? complianceRiskLabel(row.status) : null),
  target_date: (row) => row.assignment.target_compliance_date ?? null,
};

export function ProjectCompliancePage() {
  const navName = useCurrentNavLabelOverride();
  const { projectId } = useParams<{ projectId: string }>();
  const { showToast } = useToast();
  const initialParams = useInitialSearchParams();
  const [tab, setTab] = useState<ComplianceTabKey>(() => oneOf(initialParams.get("tab"), COMPLIANCE_TABS) || "standards");
  const [project, setProject] = useState<Project | null>(null);
  const [orgUsers, setOrgUsers] = useState<OrgUser[]>([]);
  const [assignments, setAssignments] = useState<ProjectCompliance[] | null>(null);
  const [statuses, setStatuses] = useState<ProjectComplianceStatus[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selected, setSelected] = useState<ProjectCompliance | null>(null);
  const [assigning, setAssigning] = useState(false);

  async function downloadReport(kind: complianceApi.ComplianceReportKind) {
    if (!projectId || !project) return;
    try {
      const blob = await api.getForBlob(`/api/v1/projects/${projectId}/modules/compliance/reports?format=${kind}`);
      const safeName = project.name.replace(/[\\/"\r\n\t]/g, "") || "project";
      downloadBlob(blob, `${safeName}-compliance-report.${kind}`);
    } catch (err) {
      showToast(toErrorMessage(err, "Could not generate the compliance report."), "error");
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
        toErrorMessage(err, "The Compliance module is not enabled for this project's organisation, or you do not have access to it.")
      );
    }
  }

  useLoadOnChange(() => {
    if (!projectId) return;
    api.get<Project>(`/api/v1/projects/${projectId}`).then((proj) => {
      setProject(proj);
      api.get<OrgUser[]>(`/api/v1/orgs/${proj.organization_id}/users`).then(setOrgUsers);
    });
    void reload();
  }, [projectId]);

  const sorting = useSortState();
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
      key: "standard", label: "Standard", sortable: true,
      render: (row) => (row.status ? `${row.status.standard_reference} — ${row.status.standard_name}` : "—"),
    },
    { key: "version", label: "Version", sortable: true, render: (row) => row.status?.version_label ?? "—" },
    {
      key: "compliance", label: "Compliance", sortable: true,
      render: (row) =>
        row.assignment.is_archived
          ? "Archived"
          : row.status
            ? `${row.status.compliance_percentage.toFixed(1)}% (${row.status.applicable_count} applicable)`
            : "—",
    },
    {
      key: "outstanding", label: "Non-compliant", sortable: true,
      render: (row) => (row.status ? complianceRiskLabel(row.status) : "—"),
    },
    { key: "target_date", label: "Target date", sortable: true, render: (row) => row.assignment.target_compliance_date ?? "—" },
  ];

  return (
    <div className="container stack">
      <h1 style={{ margin: 0 }}>{navName ?? "Compliance"}</h1>
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
          <div className="row" style={{ gap: "var(--space-3)", flexWrap: "wrap" }}>
            <button className="btn btn-primary" onClick={() => setAssigning(true)}>
              Assign standard
            </button>
            <ReportExportButton onDownload={downloadReport} kinds={complianceApi.COMPLIANCE_REPORT_KINDS} />
          </div>
          <DirectoryTable
            ariaLabel="Compliance standards assigned to this project"
            columns={columns}
            rows={sortRows(rows, sorting.sort, ASSIGNMENT_SORT_VALUES)}
            sort={sorting.sort}
            onSort={sorting.onSort}
            rowKey={(row) => row.assignment.id}
            onRowClick={(row) => setSelected(row.assignment)}
            emptyState={<p className="text-muted">No compliance standards assigned to this project yet.</p>}
          />
        </div>
      )}
      {tab === "evidence" && (
        <div {...tabPanelProps("project-compliance", "evidence")}>
          <EvidencePanel projectId={projectId} />
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
              // The default, primary assignment path — works for a
              // plain Project Manager with no `compliance_officer` grant,
              // not gated behind it.
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

  useResetOnChange([orgId, standardId], () => {
    setVersions(null);
    setVersionId("");
  });

  useEffect(() => {
    if (!standardId) return;
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
    <Modal title="Assign compliance standard" onClose={onCancel} size="lg">
      <div className="stack">
        {standards === null ? (
          <Spinner />
        ) : standards.length === 0 ? (
          <p className="text-muted">No compliance standards exist in this organisation yet.</p>
        ) : (
          <FormGrid minColumn="18rem">
            <LabeledSelect helpNotNeeded
              label="Standard"
              value={standardId}
              onChange={setStandardId}
              options={standards.filter((s) => !s.is_archived).map((s) => ({ value: s.id, label: `${s.reference} — ${s.name}` }))}
              placeholder="Select a standard…"
            />
            {standardId && (
              versions === null ? (
                <Spinner />
              ) : versions.length === 0 ? (
                <p className="text-muted" style={{ margin: 0 }}>This standard has no published version to assign.</p>
              ) : (
                <LabeledSelect helpNotNeeded
                  label="Version" ariaLabel="Standard version"
                  value={versionId} onChange={setVersionId}
                  options={versions.map((v) => ({ value: v.id, label: v.version_label }))} placeholder={null}
                />
              )
            )}
            <DateField help={COMPLIANCE_HELP.targetComplianceDate} label="Target compliance date" value={targetDate} onChange={setTargetDate} />
          </FormGrid>
        )}
        <FormActions
          onCancel={onCancel}
          onSave={() => onSave({ standard_id: standardId, standard_version_id: versionId, target_compliance_date: targetDate || null })}
          saveLabel="Assign"
          saveDisabled={!standardId || !versionId}
        />
      </div>
    </Modal>
  );
}
