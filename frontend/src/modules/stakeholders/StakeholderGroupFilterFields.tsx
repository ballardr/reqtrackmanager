/**
 * Module: modules/stakeholders/StakeholderGroupFilterFields
 *
 * The "Group" filter and "Group by" selects shared by the Stakeholder list
 * (`StakeholderListView`) and the S1/S4 report views, so both read the group
 * tree the same way: the filter lists every group indented by depth, "Group by"
 * lists top-level groups only (a stakeholder is arranged by its branch under
 * one). The caller owns the values; a blank string means no group / no grouping.
 */
import { useMemo, type ReactNode } from "react";

import { FilterSelect } from "../../components/FilterSelect";
import { buildGroupTree, flattenGroupTree } from "./groupTree";
import type { StakeholderGroup } from "./types";
import { useStrings } from "../../context/TerminologyContext";

/**
 * @param props.groups Every group in view, flat; renders nothing when empty.
 * @param props.groupId The filtered group id, or "" for all groups.
 * @param props.groupBy The top-level group id the list is arranged by, or "" for none.
 * @param props.afterGroup Optional controls shown between the two selects (the list's "directly in the group only" switch).
 */
export function StakeholderGroupFilterFields({
  groups,
  groupId,
  onGroupIdChange,
  groupBy,
  onGroupByChange,
  afterGroup,
}: {
  groups: StakeholderGroup[];
  groupId: string;
  onGroupIdChange: (next: string) => void;
  groupBy: string;
  onGroupByChange: (next: string) => void;
  afterGroup?: ReactNode;
}) {
  const strings = useStrings();
  const options = useMemo(() => flattenGroupTree(buildGroupTree(groups)), [groups]);
  if (groups.length === 0) return null;
  return (
    <>
      <FilterSelect
        label={strings.filters.group}
        value={groupId}
        onChange={onGroupIdChange}
        allLabel="All groups"
        options={options.map(({ group, depth }) => ({ value: group.id, label: `${"  ".repeat(depth)}${group.name}` }))}
      />
      {afterGroup}
      <FilterSelect
        label={strings.filters.groupBy}
        value={groupBy}
        onChange={onGroupByChange}
        allLabel="No grouping"
        options={options.filter(({ depth }) => depth === 0).map(({ group }) => ({ value: group.id, label: group.name }))}
      />
    </>
  );
}
