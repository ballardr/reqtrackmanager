/**
 * Module: modules/compliance/StandardApplicabilityPanel
 *
 * Phase 20's "applies to all projects by default, except..." UI —
 * Compliance-Manager-only, rendered inside `StandardWorkspacePage.tsx`'s
 * Overview section (docs/compliance-module-plan.md Phase 20). This is
 * deliberately the *secondary*, org-wide-mandate surface: the *default,
 * primary* way a project acquires a standard is `ProjectCompliancePage.
 * tsx`'s own "Assign standard" flow (now calling `createProjectCompliance
 * AsProjectManager`, working for a plain Project Manager), unaffected by
 * anything on this panel.
 *
 * Two pieces:
 * - A `ToggleSwitch` for `ComplianceStandard.applicability_default` — the
 *   same control shape `MappingTypesPanel.tsx` already uses for
 *   `implies_equivalence` (docs/ux-style-guide.md's "one-component-per-
 *   pattern" principle: no bespoke toggle reimplementation).
 * - An excluded-projects list, using `DirectoryTable` per the style
 *   guide's directory pattern (small, caller-owned rows — no search/
 *   pagination props passed, since an org's exclusion list is expected to
 *   stay small; `DirectoryTable` itself has no minimum-scale requirement,
 *   see that component's own docstring), plus a Modal-based "Exclude a
 *   project" flow requiring a mandatory reason — mirroring `EvidencePanel.
 *   tsx`'s `RevalidateModal`'s own "reason textarea, Cancel/Confirm, no
 *   ConfirmDialog" shape for a *justification*-carrying action (not a
 *   plain irreversible-delete, which is what `ConfirmDialog`/its two
 *   confirmation tiers are for).
 */
import { useEffect, useState } from "react";

import type { OrgUser, ProjectListItem } from "../../api/types";
import { api } from "../../api/client";
import { DirectoryTable, type DirectoryColumn } from "../../components/DirectoryTable";
import { Modal } from "../../components/Modal";
import { Spinner } from "../../components/Spinner";
import { ToggleSwitch } from "../../components/ToggleSwitch";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import * as complianceApi from "./api";
import type { ComplianceStandard, ComplianceStandardDefaultExclusion } from "./types";
import { userDisplayName } from "./types";

export function StandardApplicabilityPanel({
  standard,
  onStandardChanged,
}: {
  standard: ComplianceStandard;
  onStandardChanged: (updated: ComplianceStandard) => void;
}) {
  const { showToast } = useToast();
  const [exclusions, setExclusions] = useState<ComplianceStandardDefaultExclusion[] | null>(null);
  const [projects, setProjects] = useState<ProjectListItem[] | null>(null);
  const [orgUsers, setOrgUsers] = useState<OrgUser[]>([]);
  const [toggling, setToggling] = useState(false);
  const [excluding, setExcluding] = useState(false);

  const appliesToAll = standard.applicability_default === "applies_to_all_projects";

  async function reload() {
    const [loadedExclusions, loadedProjects, loadedUsers] = await Promise.all([
      complianceApi.listStandardDefaultExclusions(standard.organization_id, standard.id),
      api.get<ProjectListItem[]>(`/api/v1/projects?organization_id=${standard.organization_id}`),
      api.get<OrgUser[]>(`/api/v1/orgs/${standard.organization_id}/users`),
    ]);
    setExclusions(loadedExclusions);
    setProjects(loadedProjects);
    setOrgUsers(loadedUsers);
  }

  useEffect(() => {
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [standard.organization_id, standard.id]);

  async function handleToggle(next: boolean) {
    setToggling(true);
    try {
      const updated = await complianceApi.updateStandardApplicabilityDefault(
        standard.organization_id, standard.id, next ? "applies_to_all_projects" : "opt_in"
      );
      onStandardChanged(updated);
      showToast(
        next
          ? "This standard now applies to all projects by default."
          : "This standard is back to opt-in, per-project assignment."
      );
      await reload();
    } catch (err) {
      showToast(toErrorMessage(err, "Could not update the applicability default."), "error");
    } finally {
      setToggling(false);
    }
  }

  async function handleRemoveExclusion(projectId: string) {
    try {
      await complianceApi.removeStandardDefaultExclusion(standard.organization_id, standard.id, projectId);
      showToast("Project removed from the exclusion list.");
      await reload();
    } catch (err) {
      showToast(toErrorMessage(err, "Could not remove the exclusion."), "error");
    }
  }

  const excludedProjectIds = new Set((exclusions ?? []).map((e) => e.project_id));
  const projectName = (projectId: string) => projects?.find((p) => p.id === projectId)?.name ?? projectId;

  const columns: DirectoryColumn<ComplianceStandardDefaultExclusion>[] = [
    { key: "project", label: "Project", render: (row) => projectName(row.project_id) },
    { key: "reason", label: "Reason", render: (row) => row.reason },
    { key: "excluded_by", label: "Excluded by", render: (row) => userDisplayName(orgUsers, row.excluded_by) },
    {
      key: "actions",
      label: "",
      render: (row) => (
        <button className="btn" onClick={() => handleRemoveExclusion(row.project_id)}>
          Remove
        </button>
      ),
    },
  ];

  return (
    <div className="card stack">
      <h2 style={{ margin: 0, fontSize: "1rem" }}>Applicability default</h2>
      <p className="text-muted" style={{ margin: 0 }}>
        By default, projects opt in to this standard one at a time (the ordinary, everyday path — see "Assign
        standard" on a project's own Compliance page). Switch this on to make it a centrally-mandated standard that
        applies to every project in this organisation by default, except any you explicitly exclude below.
      </p>
      <ToggleSwitch
        checked={appliesToAll}
        onChange={handleToggle}
        disabled={toggling}
        label="Applies to all projects by default"
      />
      {appliesToAll && (
        <div className="stack">
          <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
            <h3 style={{ margin: 0, fontSize: "0.9rem" }}>Excluded projects</h3>
            <button className="btn" onClick={() => setExcluding(true)} disabled={projects === null}>
              Exclude a project
            </button>
          </div>
          {exclusions === null ? (
            <Spinner />
          ) : (
            <DirectoryTable
              ariaLabel="Projects excluded from this standard's default"
              columns={columns}
              rows={exclusions}
              rowKey={(row) => row.id}
              emptyState={<p className="text-muted">No projects are excluded — every project in this organisation is in scope.</p>}
            />
          )}
        </div>
      )}
      {excluding && projects && (
        <ExcludeProjectModal
          candidateProjects={projects.filter((p) => !excludedProjectIds.has(p.id))}
          onCancel={() => setExcluding(false)}
          onSave={async (values) => {
            try {
              await complianceApi.excludeProjectFromStandardDefault(standard.organization_id, standard.id, values);
              showToast("Project excluded.");
              setExcluding(false);
              await reload();
            } catch (err) {
              showToast(toErrorMessage(err, "Could not exclude this project."), "error");
            }
          }}
        />
      )}
    </div>
  );
}

function ExcludeProjectModal({
  candidateProjects,
  onCancel,
  onSave,
}: {
  candidateProjects: ProjectListItem[];
  onCancel: () => void;
  onSave: (values: { project_id: string; reason: string }) => void;
}) {
  const [projectId, setProjectId] = useState("");
  const [reason, setReason] = useState("");

  return (
    <Modal title="Exclude a project" onClose={onCancel}>
      <div className="stack">
        {candidateProjects.length === 0 ? (
          <p className="text-muted">Every project in this organisation is already excluded, or none exist.</p>
        ) : (
          <label className="stack" style={{ gap: "0.25rem" }}>
            <span>Project</span>
            <select className="input" value={projectId} onChange={(e) => setProjectId(e.target.value)} aria-label="Project">
              <option value="">Select a project…</option>
              {candidateProjects.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
          </label>
        )}
        <label className="stack" style={{ gap: "0.25rem" }}>
          <span>Reason (required)</span>
          <textarea className="input" rows={2} value={reason} onChange={(e) => setReason(e.target.value)} />
        </label>
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn" onClick={onCancel}>Cancel</button>
          <button
            className="btn btn-primary"
            disabled={!projectId || !reason.trim()}
            onClick={() => onSave({ project_id: projectId, reason })}
          >
            Exclude
          </button>
        </div>
      </div>
    </Modal>
  );
}
