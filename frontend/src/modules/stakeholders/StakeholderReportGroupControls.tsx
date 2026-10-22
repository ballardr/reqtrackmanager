/**
 * Module: modules/stakeholders/StakeholderReportGroupControls
 *
 * The group filter and "Group by" controls of the S1 and S4 reports. The report
 * views own the `group_id` and `group_by` parameters (`reportViews[...].ownedParams`),
 * so the generic parameter form, which would show a raw id box, hides them and
 * this draws the same selects the Stakeholder list uses
 * (`StakeholderGroupFilterFields`), re-running the report on each change.
 */
import { useProjectStakeholderGroups } from "./useProjectStakeholderGroups";
import { StakeholderGroupFilterFields } from "./StakeholderGroupFilterFields";

/**
 * @param props.projectId The project whose groups are offered; nothing renders when it has none (or on an organisation run).
 * @param props.values The report's current run values (`group_id`, `group_by`).
 * @param props.onValueChange Sets one value and re-runs the report.
 */
export function StakeholderReportGroupControls({
  projectId,
  values,
  onValueChange,
}: {
  projectId: string | null;
  values: Record<string, string | number | boolean | null | undefined>;
  onValueChange: (name: string, value: string | null) => void;
}) {
  const groups = useProjectStakeholderGroups(projectId);
  if (groups.length === 0) return null;
  return (
    <div className="row" style={{ gap: "var(--space-5)", alignItems: "flex-end", flexWrap: "wrap" }}>
      <StakeholderGroupFilterFields
        groups={groups}
        groupId={typeof values.group_id === "string" ? values.group_id : ""}
        onGroupIdChange={(next) => onValueChange("group_id", next || null)}
        groupBy={typeof values.group_by === "string" ? values.group_by : ""}
        onGroupByChange={(next) => onValueChange("group_by", next || null)}
      />
    </div>
  );
}
