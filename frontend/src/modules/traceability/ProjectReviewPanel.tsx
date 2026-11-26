/**
 * Module: modules/traceability/ProjectReviewPanel
 *
 * The "Review policy" section of Project Administration: for each record type with a review schedule, the interval,
 * reminder lead and default owner in force for the project, where each comes from, and whether the project holds its own
 * settings or follows its parent project.
 *
 * Responsibilities:
 * - Show the effective settings with their sources (a governance profile, this project or the parent project) in each
 *   cell's tooltip, and the project's own setting in the last column.
 * - For a person who may manage the project's governance, edit one record type's own settings in
 *   `ReviewSettingsModal`, or return it to the parent project's settings.
 * - Read-only for everyone else.
 *
 * Dependencies: `projectGovernanceApi`, `PolicyTable`, `ReviewSettingsModal`, `useProjectPeople`.
 */
import { useCallback, useState } from "react";

import { CellText } from "../../components/CellText";
import { LoadFailed } from "../../components/LoadFailed";
import { PrincipalBadge } from "../../components/PrincipalBadge";
import { Spinner } from "../../components/Spinner";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { useLoadOnChange } from "../../hooks/useLoadOnChange";
import { useProjectPeople } from "../../hooks/useProjectPeople";
import { projectGovernanceApi } from "./api";
import { reviewValuesOf, sourceLabel } from "./policyText";
import { PolicyTable } from "./PolicyTable";
import { ReviewSettingsModal } from "./ReviewSettingsModal";
import type { ProjectReview, ProjectReviewType, ReviewSettingsValues } from "./types";

/**
 * @param row A record type's review policy for the project.
 * @returns How the project's own setting reads: "Own", "Inherited from <project>" or "None".
 */
function projectSetting(row: ProjectReviewType): string {
  if (row.own) return "Own";
  return row.inherited_from ? `Inherited from ${row.inherited_from}` : "None";
}

/**
 * @param projectId The project whose review policy is shown.
 */
export function ProjectReviewPanel({ projectId }: { projectId: string }) {
  const { showToast } = useToast();
  const [data, setData] = useState<ProjectReview | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [editing, setEditing] = useState<ProjectReviewType | null>(null);
  const { project, orgUsers } = useProjectPeople(projectId);

  const load = useCallback(async () => {
    try {
      setData(await projectGovernanceApi.review(projectId));
      setFailure(null);
    } catch (err) {
      setFailure(toErrorMessage(err, "The review policy could not be loaded."));
    }
  }, [projectId]);
  useLoadOnChange(load, [projectId]);

  async function save(row: ProjectReviewType, values: ReviewSettingsValues | null) {
    setData(await projectGovernanceApi.setReview(projectId, row.artefact_type, values));
    showToast(`Review settings for ${row.label} saved.`);
  }

  if (failure && !data) return <LoadFailed message={failure} onRetry={() => void load()} />;
  if (!data) return <Spinner />;
  const none = <span className="text-muted">Not set</span>;
  const withSource = (value: number | null, source: string | null) => (
    value === null ? none : <CellText detail={`Source: ${sourceLabel(source)}`}>{String(value)}</CellText>
  );

  return (
    <div className="stack">
      <PolicyTable
        ariaLabel="Review policy by record type" chooserKey="governance_project_review" rows={data.types} emptyText="No record type has a review schedule."
        columns={[
          {
            key: "interval", label: "Interval (days)", width: "9rem", sortValue: (row) => row.effective.interval_days,
            render: (row) => withSource(row.effective.interval_days, row.effective.interval_source),
          },
          {
            key: "lead", label: "Reminder lead (days)", width: "10rem", optional: true, sortValue: (row) => row.effective.lead_days,
            render: (row) => withSource(row.effective.lead_days, row.effective.lead_source),
          },
          {
            key: "owner", label: "Default owner", sortValue: (row) => row.effective.default_owner?.label ?? null,
            render: (row) => <div style={{ maxWidth: "16rem" }}><PrincipalBadge principal={row.effective.default_owner} placeholder="Not set" /></div>,
          },
          { key: "setting", label: "Project setting", optional: true, sortValue: projectSetting, render: (row) => <CellText lines={2}>{projectSetting(row)}</CellText> },
        ]}
        rowMenu={data.can_manage ? (row) => [{ label: "Edit review settings", onSelect: () => setEditing(row) }] : undefined}
        rowMenuLabel={(row) => `Actions for ${row.label}`}
      />
      {editing && (
        <ReviewSettingsModal
          typeLabel={editing.label} initial={reviewValuesOf(editing.own)} ownerDisplay={editing.own?.default_owner}
          orgUsers={orgUsers ?? []} organizationId={project?.organization_id} projectId={projectId}
          allowFollowParent={editing.own !== null} onSave={(values) => save(editing, values)} onClose={() => setEditing(null)}
        />
      )}
    </div>
  );
}
