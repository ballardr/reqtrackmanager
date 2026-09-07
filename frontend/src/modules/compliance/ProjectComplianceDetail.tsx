/**
 * Module: modules/compliance/ProjectComplianceDetail
 *
 * One project's assignment to a single compliance standard version —
 * §20's overall status summary (always showing the raw counts alongside
 * the calculated percentage, per §20's explicit "the percentage cannot be
 * misleading" requirement) plus archive/unarchive, drilling into two
 * `Tabs`: "Requirements" (`ApplicabilityTree` — the applicability/
 * assessment/evidence/approval workspace, §8-§10, §12, §16) and "Reviews"
 * (`ReviewsPanel`, §17).
 *
 * Rendered full content-column width in place of the assignment list
 * (`ProjectCompliancePage`'s own `selected` state), mirroring
 * `StandardsPanel` -> `VersionWorkspace`'s identical "replace the tab's
 * content column in place, not a nested `SidePanel`" drill-down shape
 * (Phase 12 notes) — a requirement tree editor needs more width than a
 * 420px `SidePanel` allows.
 *
 * The version-migration action (§27, `POST .../migrate-version`) is
 * deliberately not surfaced here — see `api.ts`'s own module docstring for
 * why this is a flagged Phase 13 scope trim, not an oversight.
 */
import { useEffect, useState } from "react";

import type { OrgUser } from "../../api/types";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Tabs, tabPanelProps } from "../../components/Tabs";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { ApplicabilityTree } from "./ApplicabilityTree";
import * as complianceApi from "./api";
import { ReviewsPanel } from "./ReviewsPanel";
import {
  COMPLIANCE_APPROVAL_STATE_LABEL,
  COMPLIANCE_OVERALL_STATE_LABEL,
  COMPLIANCE_STATUS_LABEL,
  type ComplianceStatus,
  type ProjectCompliance,
  type ProjectComplianceStatus,
} from "./types";

type DetailTabKey = "requirements" | "reviews";

export function ProjectComplianceDetail({
  orgId,
  projectId,
  assignment,
  status,
  orgUsers,
  onBack,
  onArchiveToggled,
}: {
  orgId: string;
  projectId: string;
  assignment: ProjectCompliance;
  status: ProjectComplianceStatus | null;
  orgUsers: OrgUser[];
  onBack: () => void;
  onArchiveToggled: (updated: ProjectCompliance) => void;
}) {
  const { showToast } = useToast();
  const [tab, setTab] = useState<DetailTabKey>("requirements");
  const [confirmingArchive, setConfirmingArchive] = useState(false);
  // `status` already carries `standard_id` for an active assignment; an
  // archived one (excluded from `GET .../status`) needs the client-side
  // fallback resolution — see `api.ts::resolveStandardIdForVersion`'s own
  // docstring for why no backend endpoint gives this directly.
  const [resolvedStandardId, setResolvedStandardId] = useState<string | null>(status?.standard_id ?? null);
  // Lifted into local state (not read directly off the `status` prop) so it
  // can be refreshed after a nested requirement change without the parent
  // (`ProjectCompliancePage`) needing to re-fetch its whole assignment list
  // — see `handleAssessmentChanged` below and `ApplicabilityTree`'s own
  // `onAssessmentChanged` docstring for the staleness this fixes.
  const [liveStatus, setLiveStatus] = useState<ProjectComplianceStatus | null>(status);

  useEffect(() => {
    setLiveStatus(status);
    if (status) {
      setResolvedStandardId(status.standard_id);
      return;
    }
    let cancelled = false;
    complianceApi.resolveStandardIdForVersion(orgId, assignment.standard_version_id).then((id) => {
      if (!cancelled) setResolvedStandardId(id);
    });
    return () => {
      cancelled = true;
    };
  }, [orgId, assignment.standard_version_id, status]);

  async function handleAssessmentChanged() {
    try {
      const statuses = await complianceApi.getProjectComplianceStatus(projectId);
      const updated = statuses.find((s) => s.project_compliance_id === assignment.id);
      if (updated) setLiveStatus(updated);
    } catch {
      // Best-effort refresh only — the tree's own badges are already the
      // authoritative live view; a failed status re-fetch here just leaves
      // this summary card at its previous value, not a broken page.
    }
  }

  async function handleArchiveToggle() {
    try {
      const updated = assignment.is_archived
        ? await complianceApi.unarchiveProjectCompliance(orgId, projectId, assignment.id)
        : await complianceApi.archiveProjectCompliance(orgId, projectId, assignment.id);
      showToast(assignment.is_archived ? "Assignment unarchived." : "Assignment archived.");
      setConfirmingArchive(false);
      onArchiveToggled(updated);
    } catch (err) {
      showToast(toErrorMessage(err, "Could not update this assignment."), "error");
    }
  }

  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <button className="btn" onClick={onBack}>← Back</button>
          <h2 style={{ margin: "0.5rem 0 0" }}>
            {liveStatus ? `${liveStatus.standard_reference} — ${liveStatus.standard_name}` : "Compliance assignment"}
          </h2>
          {liveStatus && <p className="text-muted" style={{ margin: 0 }}>{liveStatus.version_label}</p>}
        </div>
        <button className="btn btn-danger" onClick={() => setConfirmingArchive(true)}>
          {assignment.is_archived ? "Unarchive" : "Archive"}
        </button>
      </div>

      {assignment.is_archived && (
        <p className="text-muted">This assignment is archived. It is retained for history but no longer counted as active.</p>
      )}

      {liveStatus && (
        <div className="card stack" aria-label="Overall compliance status">
          <div className="row" style={{ flexWrap: "wrap", gap: "1.5rem" }}>
            <Stat label="Overall state" value={COMPLIANCE_OVERALL_STATE_LABEL[liveStatus.overall_compliance_state]} />
            <Stat label="Approval state" value={COMPLIANCE_APPROVAL_STATE_LABEL[liveStatus.overall_approval_state]} />
            <Stat
              label="Compliance"
              value={`${liveStatus.compliance_percentage.toFixed(1)}% (${liveStatus.applicable_count} of ${liveStatus.total_requirements} applicable)`}
            />
            <Stat label="Not applicable" value={String(liveStatus.not_applicable_count)} />
            <Stat label="Target date" value={liveStatus.target_compliance_date ?? "—"} />
            {liveStatus.has_non_compliant && (
              <span className="badge" style={{ background: "var(--color-danger)", color: "white" }}>
                Contains non-compliant requirements
              </span>
            )}
          </div>
          <div className="row" style={{ flexWrap: "wrap", gap: "0.75rem" }}>
            {Object.entries(liveStatus.counts_by_status).map(([key, count]) => (
              <span key={key} className="badge">
                {COMPLIANCE_STATUS_LABEL[key as ComplianceStatus] ?? key}: {count}
              </span>
            ))}
          </div>
        </div>
      )}

      <Tabs<DetailTabKey>
        idPrefix="project-compliance-detail"
        active={tab}
        onChange={setTab}
        tabs={[
          { key: "requirements", label: "Requirements" },
          { key: "reviews", label: "Reviews" },
        ]}
      />
      {tab === "requirements" && (
        <div {...tabPanelProps("project-compliance-detail", "requirements")}>
          {resolvedStandardId === null ? (
            <p className="text-muted">Loading…</p>
          ) : (
            <ApplicabilityTree
              orgId={orgId}
              projectId={projectId}
              standardId={resolvedStandardId}
              versionId={assignment.standard_version_id}
              projectComplianceId={assignment.id}
              orgUsers={orgUsers}
              onAssessmentChanged={handleAssessmentChanged}
            />
          )}
        </div>
      )}
      {tab === "reviews" && (
        <div {...tabPanelProps("project-compliance-detail", "reviews")}>
          <ReviewsPanel projectId={projectId} projectComplianceId={assignment.id} orgUsers={orgUsers} />
        </div>
      )}

      {confirmingArchive && (
        <ConfirmDialog
          title={assignment.is_archived ? "Unarchive this assignment?" : "Archive this assignment?"}
          message={
            assignment.is_archived
              ? "This assignment will count as active again and reappear in the project's overall status."
              : "This assignment will be hidden from the active list and excluded from the project's overall status. Nothing is deleted."
          }
          confirmLabel={assignment.is_archived ? "Unarchive" : "Archive"}
          onConfirm={handleArchiveToggle}
          onCancel={() => setConfirmingArchive(false)}
        />
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="stack" style={{ gap: "0.1rem" }}>
      <span className="text-muted" style={{ fontSize: "0.8rem" }}>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}
