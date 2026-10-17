/**
 * Module: modules/stakeholders/StakeholderGroupsField
 *
 * A Stakeholder's groups on its detail page: the group names as
 * badges (with their full path on hover) and a `TreeSelect` to change them,
 * applied with an explicit Save so a multi-group change lands in one request
 * (and an `exclusive_children` conflict rejects the whole set, not half of it).
 * Only the groups of the viewing tier are editable — organisation groups from an
 * organisation page, a project's own from a project page — the other tier's
 * nodes are shown disabled. Group membership is classification, not part of the
 * stakeholder's version history.
 */
import { useState } from "react";

import { TreeSelect } from "../../components/TreeSelect";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { RecordFieldGroup } from "../../components/RecordDetailParts";
import { buildGroupTree, groupPath, groupSelectNodes } from "./groupTree";
import type { StakeholderGroup, StakeholderGroupRef } from "./types";
import { Badge } from "../../components/Badge";

export function StakeholderGroupsField({
  current,
  groups,
  tier,
  onSave,
}: {
  /** The stakeholder's direct groups. */
  current: StakeholderGroupRef[];
  /** Every group this view can see, flat. */
  groups: StakeholderGroup[];
  tier: "organization" | "project";
  /** Sets the tier's groups to exactly these ids; resolves to the stakeholder's resulting groups. */
  onSave: (groupIds: string[]) => Promise<StakeholderGroupRef[]>;
}) {
  const { showToast } = useToast();
  const mine = current.filter((g) => g.scope === tier).map((g) => g.id);
  const [selected, setSelected] = useState<string[] | null>(null);
  const draft = selected ?? mine;
  const dirty = selected !== null && (selected.length !== mine.length || selected.some((id) => !mine.includes(id)));

  async function save() {
    try {
      await onSave(draft);
      showToast("Groups updated.");
      setSelected(null);
    } catch (err) {
      showToast(toErrorMessage(err, "Could not update this Stakeholder's groups."), "error");
    }
  }

  return (
    <RecordFieldGroup label="Groups">
      {current.length === 0 ? (
        <span className="text-muted">Not in any group.</span>
      ) : (
        <span className="row" style={{ gap: "0.35rem" }}>
          {current.map((g) => (
            <Badge key={g.id} title={groupPath(groups, g.id)}>{g.name}</Badge>
          ))}
        </span>
      )}
      <div className="row" style={{ gap: "0.5rem", alignItems: "center" }}>
        <TreeSelect
          triggerLabel={tier === "project" ? "Project groups" : "Organisation groups"}
          nodes={groupSelectNodes(
            buildGroupTree(groups), tier,
            tier === "project" ? "Organisation groups are changed from the organisation view." : "Only organisation groups apply here.",
          )}
          selectedIds={draft}
          onChange={setSelected}
          emptyLabel="No groups"
        />
        <button className="btn" disabled={!dirty} onClick={save}>Save groups</button>
      </div>
    </RecordFieldGroup>
  );
}
