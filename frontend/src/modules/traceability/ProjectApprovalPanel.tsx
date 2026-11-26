/**
 * Module: modules/traceability/ProjectApprovalPanel
 *
 * The Approval policy section of Project Administration: for each record type with an approval gate, the roles that may
 * also approve it in the project, where each comes from, and a dialog for the project's own roles.
 *
 * Responsibilities: load the project's approval policy, show the effective approvers with their sources (a profile, this
 * project or the parent project), say whether the project's own row, an ancestor's or only profiles supply them, and save
 * the project's own roles or return to the inherited value.
 *
 * Design decisions: a person without `manage_project_governance` sees the same table with no row menu. A value inherited
 * from a tier names the tier (docs/ux-style-guide.md, Principle 2).
 *
 * Dependencies: `projectGovernanceApi` (`./api`), `PolicyTable`, `ApprovalRolesModal`.
 */
import { useCallback, useState } from "react";

import { Badge } from "../../components/Badge";
import { CellText } from "../../components/CellText";
import { LoadFailed } from "../../components/LoadFailed";
import { Spinner } from "../../components/Spinner";
import { useToast } from "../../context/ToastContext";
import { useLoadOnChange } from "../../hooks/useLoadOnChange";
import { projectGovernanceApi } from "./api";
import { ApprovalRolesModal } from "./ApprovalRolesModal";
import { sourceLabel } from "./approverRoles";
import { PolicyTable } from "./PolicyTable";
import type { ApproverRole, ProjectApproval, ProjectApprovalType } from "./types";

/**
 * @param type One record type's policy.
 * @returns Where the type's approvers come from, in words.
 */
function typeSource(type: ProjectApprovalType): string {
  if (type.own !== null) return "Own";
  if (type.inherited_from) return `Inherited from ${type.inherited_from}`;
  return "Profiles only";
}

/** @param projectId The project whose approval policy is shown. */
export function ProjectApprovalPanel({ projectId }: { projectId: string }) {
  const { showToast } = useToast();
  const [data, setData] = useState<ProjectApproval | null>(null);
  const [failed, setFailed] = useState(false);
  const [editing, setEditing] = useState<ProjectApprovalType | null>(null);

  const load = useCallback(async () => {
    setFailed(false);
    try {
      setData(await projectGovernanceApi.approval(projectId));
    } catch {
      setFailed(true);
    }
  }, [projectId]);
  useLoadOnChange(load, [projectId]);

  async function save(type: ProjectApprovalType, roles: ApproverRole[] | null) {
    setData(await projectGovernanceApi.setApprovalRoles(projectId, type.artefact_type, roles));
    showToast(roles === null ? `Approvers of ${type.label} now follow the inherited value.` : `Approvers of ${type.label} saved.`);
    setEditing(null);
  }

  if (failed && !data) return <LoadFailed message="The approval policy could not be loaded." onRetry={() => void load()} />;
  if (!data) return <Spinner />;

  return (
    <div className="stack">
      <PolicyTable
        ariaLabel="Approval policy by record type"
        rows={data.types}
        emptyText="No record type of this organisation has an approval gate."
        columns={[
          {
            key: "effective", label: "Effective approvers",
            sortValue: (row) => row.effective.map((e) => e.role.label).join(", "),
            render: (row) => row.effective.length === 0 ? <span className="text-muted">None</span> : (
              <div className="stack" style={{ gap: "var(--space-1)" }}>
                {row.effective.map((e) => (
                  <div key={`${e.role.kind}:${e.role.key}`} className="row" style={{ gap: "var(--space-2)" }}>
                    <Badge>{e.role.label}</Badge>
                    <CellText lines={2} maxWidth="14rem" className="text-muted" detail={`Given by: ${e.sources.map(sourceLabel).join(", ")}`}>
                      {e.sources.map(sourceLabel).join(", ")}
                    </CellText>
                  </div>
                ))}
              </div>
            ),
          },
          { key: "source", label: "Source", sortValue: typeSource, render: (row) => <CellText lines={2}>{typeSource(row)}</CellText> },
        ]}
        rowMenu={data.can_manage ? (row) => [{ label: "Edit approvers", onSelect: () => setEditing(row) }] : undefined}
        rowMenuLabel={(row) => `Actions for ${row.label} approvers`}
      />
      {editing && (
        <ApprovalRolesModal
          typeLabel={editing.label} options={data.role_options} initial={editing.own ?? []}
          onSave={(roles) => save(editing, roles)} onClose={() => setEditing(null)}
          allowFollowParent own={editing.own !== null} inheritedFrom={editing.inherited_from}
        />
      )}
    </div>
  );
}
