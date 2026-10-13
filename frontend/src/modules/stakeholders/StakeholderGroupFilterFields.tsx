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

import { FilterField } from "../../components/FilterPanel";
import { buildGroupTree, flattenGroupTree } from "./groupTree";
import type { StakeholderGroup } from "./types";

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
  const options = useMemo(() => flattenGroupTree(buildGroupTree(groups)), [groups]);
  if (groups.length === 0) return null;
  return (
    <>
      <FilterField label="Group">
        <select className="input" aria-label="Group" value={groupId} onChange={(e) => onGroupIdChange(e.target.value)}>
          <option value="">All groups</option>
          {options.map(({ group, depth }) => (
            <option key={group.id} value={group.id}>{`${"  ".repeat(depth)}${group.name}`}</option>
          ))}
        </select>
      </FilterField>
      {afterGroup}
      <FilterField label="Group by">
        <select className="input" aria-label="Group by" value={groupBy} onChange={(e) => onGroupByChange(e.target.value)}>
          <option value="">No grouping</option>
          {options.filter(({ depth }) => depth === 0).map(({ group }) => (
            <option key={group.id} value={group.id}>{group.name}</option>
          ))}
        </select>
      </FilterField>
    </>
  );
}
